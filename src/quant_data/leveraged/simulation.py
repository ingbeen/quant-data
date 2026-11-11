"""레버리지 ETF 시뮬레이션 모듈

QQQ와 같은 기초 자산 데이터로부터 TQQQ와 같은 레버리지 ETF를 시뮬레이션한다.
일일 리밸런싱 기반의 3배 레버리지 ETF 동작을 재현한다.
"""

# 1. 표준 라이브러리 임포트
import math
import re
from datetime import date

# 2. 서드파티 라이브러리 임포트
import pandas as pd

from quant_data.constants import (
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    REQUIRED_COLUMNS,
    TRADING_DAYS_PER_YEAR,
)
from quant_data.leveraged.constants import (
    COL_FFR_DATE,
    COL_FFR_VALUE,
    MONTH_KEY_PATTERN,
)
from quant_data.leveraged.monthly_data import (
    lookup_expense,
    lookup_ffr,
    lookup_funding_spread,
)
from quant_data.logger import get_logger

logger = get_logger(__name__)

# ============================================================
# Softplus 동적 스프레드 모델 함수
# ============================================================


def _softplus(x: float) -> float:
    """
    수치 안정 버전 softplus 함수를 계산한다.

    softplus(x) = log(1 + exp(x)) 를 수치적으로 안정하게 계산한다.
    x가 크면 overflow, x가 작으면 underflow를 방지하는 변환 사용.

    수치 안정 수식:
        softplus(x) = log1p(exp(-abs(x))) + max(x, 0)

    특성:
        - 항상 양수 반환 (> 0)
        - x -> -inf: 결과 -> 0 (점근)
        - x -> +inf: 결과 -> x (점근)
        - 부드러운 ReLU 근사 (미분 가능)

    Args:
        x: 입력 값

    Returns:
        softplus(x) 값 (항상 > 0)
    """
    # 수치 안정 계산: log1p(exp(-|x|)) + max(x, 0)
    # 이 공식은 x의 부호에 관계없이 안정적으로 계산된다.
    return math.log1p(math.exp(-abs(x))) + max(x, 0.0)


def _compute_softplus_spread(a: float, b: float, ffr_ratio: float) -> float:
    """
    softplus 기반 동적 spread를 계산한다.

    수식: spread = softplus(a + b * ffr_pct)
    여기서 ffr_pct = 100.0 * ffr_ratio (0~1 비율을 % 단위로 변환)

    예시:
        a = -5.0, b = 1.0, ffr_ratio = 0.05 (5%)
        ffr_pct = 5.0
        spread = softplus(-5.0 + 1.0 * 5.0) = softplus(0.0) ≈ 0.693

    Args:
        a: 절편 파라미터 (음수일 때 저금리 구간 spread 감소)
        b: 기울기 파라미터 (양수일 때 고금리 구간 spread 증가)
        ffr_ratio: 연방기금금리 (0~1 비율, 예: 0.05 = 5%)

    Returns:
        계산된 spread 값 (항상 > 0)

    Raises:
        ValueError: spread <= 0인 경우 (softplus는 이론적으로 항상 > 0이므로 방어적 체크)
    """
    # 1. FFR을 % 단위로 변환 (softplus 모델은 FFR_pct 기준)
    ffr_pct = 100.0 * ffr_ratio

    # 2. softplus 계산
    spread = _softplus(a + b * ffr_pct)

    # 3. 방어적 체크 (softplus는 항상 > 0이지만 수치 오류 대비)
    if spread <= 0:
        raise ValueError(
            f"_compute_softplus_spread 결과가 유효하지 않음: spread={spread} <= 0\n"
            f"파라미터: a={a}, b={b}, ffr_ratio={ffr_ratio}, ffr_pct={ffr_pct}\n"
            f"조치: 파라미터 값 확인 필요"
        )

    return spread


def build_monthly_spread_map(
    ffr_df: pd.DataFrame,
    a: float,
    b: float,
) -> dict[str, float]:
    """
    FFR 데이터로부터 월별 softplus spread 맵을 생성한다.

    각 월의 FFR 값에 대해 softplus(a + b * ffr_pct) 공식을 적용하여
    월별 spread 딕셔너리를 생성한다. 이 딕셔너리는 simulate() 함수의
    funding_spread 파라미터로 전달할 수 있다.

    Args:
        ffr_df: FFR DataFrame (DATE: str (yyyy-mm), VALUE: float (0~1 비율))
        a: softplus 절편 파라미터
        b: softplus 기울기 파라미터

    Returns:
        {"YYYY-MM": spread} 형태의 딕셔너리

    Raises:
        ValueError: FFR DataFrame이 비어있거나 필수 컬럼 누락 시
        ValueError: spread 계산 결과가 유효하지 않을 때
    """
    # 1. 필수 컬럼 검증
    if ffr_df.empty:
        raise ValueError("FFR DataFrame이 비어있습니다")

    required_cols = {COL_FFR_DATE, COL_FFR_VALUE}
    missing_cols = required_cols - set(ffr_df.columns)
    if missing_cols:
        raise ValueError(f"FFR DataFrame 필수 컬럼 누락: {missing_cols}")

    # 2. 월별 spread 계산
    spread_map: dict[str, float] = {}
    for _, row in ffr_df.iterrows():
        month_key = str(row[COL_FFR_DATE])
        ffr_ratio = float(row[COL_FFR_VALUE])

        # softplus spread 계산
        spread = _compute_softplus_spread(a, b, ffr_ratio)
        spread_map[month_key] = spread

    logger.debug(
        f"월별 spread 맵 생성 완료: {len(spread_map)}개월, "
        f"a={a}, b={b}, spread 범위=[{min(spread_map.values()):.6f}, {max(spread_map.values()):.6f}]"
    )

    return spread_map


def cap_spread_through(spread_map: dict[str, float], cap: float, last_month: str) -> dict[str, float]:
    """
    last_month 까지의 달은 cap 을 넘는 가산금리를 cap 으로 낮추고, 그 뒤 달은 그대로 둔 새 딕셔너리를 만든다.

    Args:
        spread_map: 월별 가산금리 ({"YYYY-MM": spread}, build_monthly_spread_map)
        cap: 가산금리 상한 (비율, 0.016 = 1.6%)
        last_month: 상한을 거는 마지막 달 (yyyy-mm, 그달 포함)

    Returns:
        상한을 건 월별 가산금리 (입력은 바꾸지 않는다)

    Raises:
        ValueError: cap 이 0 이하일 때, last_month 가 YYYY-MM 이 아닐 때
    """
    if cap <= 0:
        raise ValueError(f"가산금리 상한은 0 보다 커야 합니다(0.016 = 1.6%): {cap}")
    if not re.fullmatch(MONTH_KEY_PATTERN, last_month):
        raise ValueError(f"상한을 거는 마지막 달은 YYYY-MM 이어야 합니다: {last_month!r}")

    return {month: min(spread, cap) if month <= last_month else spread for month, spread in spread_map.items()}


def _resolve_spread(d: date, spread_dict: dict[str, float]) -> float:
    """
    특정 날짜의 funding_spread 값을 월별 딕셔너리에서 조회하고 검증한다.

    키가 없으면 MAX_FFR_MONTHS_DIFF 이내 이전 월 값을 쓴다(lookup_funding_spread).

    제약 조건:
    - 반환 spread는 항상 > 0 (음수 불허, 0도 불허)
    - NaN/inf 반환 시 ValueError
    - min/max 클리핑 금지 (검증만 수행)

    Args:
        d: 대상 날짜
        spread_dict: 월별 spread 딕셔너리 ({"YYYY-MM": spread})

    Returns:
        해당 날짜의 spread 값 (> 0)

    Raises:
        ValueError: 이전 월 없음, 월 차이 초과, NaN/inf 반환, spread <= 0 등
    """
    spread = lookup_funding_spread(d, spread_dict)

    if math.isnan(spread):
        raise ValueError(f"funding_spread 반환값이 유효하지 않음: NaN (날짜: {d})\n" f"조치: spread dict 값 확인 필요")

    if math.isinf(spread):
        raise ValueError(f"funding_spread 반환값이 유효하지 않음: inf (날짜: {d})\n" f"조치: spread dict 값 확인 필요")

    if spread <= 0:
        raise ValueError(f"funding_spread는 양수여야 합니다 (> 0): {spread} (날짜: {d})\n" f"조치: spread 값을 양수로 수정")

    return spread


def _calculate_daily_cost(
    date_value: date,
    ffr_dict: dict[str, float],
    expense_dict: dict[str, float],
    funding_spread: dict[str, float],
    leverage: float,
) -> float:
    """
    특정 날짜의 일일 비용률을 계산한다.

    Args:
        date_value: 계산 대상 날짜
        ffr_dict: 연방기금금리 딕셔너리 ({"YYYY-MM": ffr_value})
        expense_dict: 운용비용 딕셔너리 ({"YYYY-MM": expense_value}, 0~1 비율)
        funding_spread: FFR에 더해지는 월별 스프레드 ({"YYYY-MM": spread})
        leverage: 레버리지 배율 (예: 3.0 = 3배 레버리지)

    Returns:
        일일 비용률 (소수, 예: 0.0001905 = 0.01905%)

    Raises:
        ValueError: FFR · Expense · funding_spread 의 그 달 값이 없고 허용 개월 수 안의 이전 달 값도 없을 때
        ValueError: funding_spread가 유효하지 않을 때 (NaN, inf, <= 0)
    """
    # 1. 해당 월의 FFR 조회 (딕셔너리 O(1) 조회)
    ffr = lookup_ffr(date_value, ffr_dict)

    # 2. 해당 월의 Expense Ratio 조회 (딕셔너리 O(1) 조회)
    expense_ratio = lookup_expense(date_value, expense_dict)

    # 3. 동적 spread 해석
    spread = _resolve_spread(date_value, funding_spread)

    # 4. All-in funding rate 계산
    # FFR은 0~1 비율이므로 직접 사용 (예: 0.05 = 5.0%)
    funding_rate = ffr + spread

    # 5. 레버리지 비용 (차입 비율 = leverage - 1)
    # 레버리지 배율에 따라 빌린 돈의 비율 계산
    # 예: 3배 레버리지 = 자기 자본 1배 + 빌린 돈 2배 → leverage - 1 = 2
    # 예: 2배 레버리지 = 자기 자본 1배 + 빌린 돈 1배 → leverage - 1 = 1
    leverage_cost = funding_rate * (leverage - 1)

    # 6. 총 연간 비용
    # 레버리지 비용 + 운용 비용
    annual_cost = leverage_cost + expense_ratio

    # 7. 일별 비용 (연간 거래일 수로 환산)
    # 연간 비용을 거래일 수로 나눔 (약 252일)
    daily_cost = annual_cost / TRADING_DAYS_PER_YEAR

    # 계산된 일일 비용 반환
    return daily_cost


def simulate(
    underlying_df: pd.DataFrame,
    leverage: float,
    initial_price: float,
    *,
    ffr_dict: dict[str, float],
    expense_dict: dict[str, float],
    funding_spread: dict[str, float],
) -> pd.DataFrame:
    """
    기초 자산 데이터로부터 레버리지 ETF를 시뮬레이션한다.

    일일 리밸런싱을 가정하여 각 거래일마다 기초 자산 수익률의
    레버리지 배수만큼 움직이도록 계산한다. 스왑비용은 연방기금금리와
    스프레드를 기반으로 동적으로 계산하며, 운용비용은 월별 데이터를 사용한다.

    월별 값은 둘째 거래일부터 날마다 조회한다 — 그 달 값이 없으면 허용 개월 수 안의 이전 달 값을 쓰고,
    없으면 ValueError 다(data_loader 의 lookup_*). 첫 거래일은 비용을 계산하지 않는다.

    Args:
        underlying_df: 기초 자산 DataFrame (Date, Open, High, Low, Close 컬럼 필수)
        leverage: 레버리지 배수 (예: 3.0)
        initial_price: 첫 거래일의 시가 · 종가
        ffr_dict: 월별 연방기금금리 ({"YYYY-MM": 0~1 비율}, create_ffr_dict)
        expense_dict: 월별 운용비율 ({"YYYY-MM": 0~1 비율}, create_expense_dict · build_extended_expense_dict)
        funding_spread: FFR에 더해지는 월별 스프레드 ({"YYYY-MM": spread}, build_monthly_spread_map)

    Returns:
        시뮬레이션된 레버리지 ETF DataFrame (Date, Open, High, Low, Close, Volume 컬럼)

    Raises:
        ValueError: 파라미터가 유효하지 않을 때
        ValueError: 필수 컬럼이 누락되었을 때
        ValueError: 월별 값(FFR · 운용비율 · funding_spread)이 그 날짜를 덮지 못할 때
        ValueError: funding_spread가 유효하지 않을 때 (NaN, inf, <= 0)
        ValueError: 시뮬레이션 가격이 0 이하가 될 때
    """
    # 1. 파라미터 검증
    if leverage <= 0:
        raise ValueError(f"leverage는 양수여야 합니다: {leverage}")

    if initial_price <= 0:
        raise ValueError(f"initial_price는 양수여야 합니다: {initial_price}")

    # 2. 필수 컬럼 검증
    required_cols = {COL_DATE, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE}
    missing_cols = required_cols - set(underlying_df.columns)
    if missing_cols:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {missing_cols}")

    if underlying_df.empty:
        raise ValueError("underlying_df가 비어있습니다")

    # 3. 데이터 복사 (원본 보존)
    df = underlying_df[[COL_DATE, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE]].copy()

    # 4. 일일 수익률 계산
    df["underlying_return"] = df[COL_CLOSE].pct_change()

    # 5. 레버리지 ETF 가격 계산 (복리, 동적 비용 반영)
    leveraged_prices = [initial_price]

    for i in range(1, len(df)):
        underlying_return = df.iloc[i]["underlying_return"]

        if pd.isna(underlying_return):
            # 시세 로더가 결측 · 0 이하 가격을 막으므로 둘째 행부터는 수익률이 늘 있다
            raise RuntimeError(f"내부 불변조건 위반: 기초 자산 수익률이 NaN (날짜 {df.iloc[i][COL_DATE]})")
        else:
            # 동적 비용 계산
            current_date = df.iloc[i][COL_DATE]
            daily_cost = _calculate_daily_cost(current_date, ffr_dict, expense_dict, funding_spread, leverage)

            # 레버리지 수익률 = 기초 자산 수익률 × 배율 - 일일 비용
            # 예: 기초 자산 +1%, 3배 레버리지 -> +3% - 비용
            leveraged_return = underlying_return * leverage - daily_cost

            # 가격 업데이트 (복리 효과)
            new_price = leveraged_prices[-1] * (1 + leveraged_return)
            leveraged_prices.append(new_price)

    # 6. 기초 자산 Close 보존 (오버나이트 수익률 계산에 필요)
    underlying_close_series = df[COL_CLOSE].copy()

    # 계산된 가격 리스트를 DataFrame 컬럼에 할당
    df[COL_CLOSE] = leveraged_prices

    # 7. OHLV 데이터 구성
    # Open · High · Low: 장중 노출은 전날 종가에 고정 → 펀드 값은 기초 자산에 선형
    # 수식: TQQQ_X(t) = TQQQ_Close(t-1) × (1 + (QQQ_X(t)/QQQ_Close(t-1) - 1) × leverage)
    underlying_prev_close = underlying_close_series.shift(1)
    for col in (COL_OPEN, COL_HIGH, COL_LOW):
        leveraged_price = df[COL_CLOSE].shift(1) * (1 + (df[col] / underlying_prev_close - 1) * leverage)
        # 첫날은 전날 종가가 없어 시작 가격으로 둔다 — 다른 날의 결측은 메우지 않는다
        leveraged_price.iloc[0] = initial_price
        df[col] = leveraged_price

    # 일일 비용은 종가에서만 빠짐 → 기초 자산이 저가에 마감한 날 식의 저가가 종가 위로 나가 몸통으로 맞춤
    df[COL_HIGH] = df[[COL_HIGH, COL_OPEN, COL_CLOSE]].max(axis=1, skipna=False)
    df[COL_LOW] = df[[COL_LOW, COL_OPEN, COL_CLOSE]].min(axis=1, skipna=False)

    # 부르는 쪽마다 저장 전 시세 검사가 있다고 기대지 않음 → 계산한 자리에서 멈춤
    non_positive_dates = df.loc[df[COL_LOW] <= 0, COL_DATE].tolist()
    if non_positive_dates:
        raise ValueError(f"시뮬레이션 가격이 0 이하입니다 — 날짜: {non_positive_dates[:5]}. 기초 자산 시세의 저가를 확인하세요")

    # Volume: 합성 데이터이므로 0
    df[COL_VOLUME] = 0

    # 8. 불필요한 컬럼 제거 및 순서 정렬
    result_df = df[REQUIRED_COLUMNS].copy()

    return result_df
