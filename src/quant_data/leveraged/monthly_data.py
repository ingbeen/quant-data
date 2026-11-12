"""레버리지 합성의 월별 데이터 — 연방기금금리 · 운용비율

주요 기능:
1. 월별 데이터(연방기금금리 · 운용비율) 로딩 · 저장
2. 월별 데이터 딕셔너리 생성 및 조회 (FFR, Expense Ratio)
3. 운용비율 딕셔너리 확장 (합성 데이터 생성용)
4. FRED 월별 연방기금금리 받기와, 다시 받은 금리의 덧붙이기 판정 (결정 Q36 — 지난 달이 그대로면 새 달만 붙인다)

받기는 파일을 쓰지 않는다 — 쓰기는 모든 판정이 끝난 뒤 update 가 한다(결정 Q17).
"""

import io
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final
from urllib.request import urlopen

import pandas as pd

from quant_data.constants import FRED_DATE_COLUMN
from quant_data.leveraged.constants import (
    COL_EXPENSE_DATE,
    COL_EXPENSE_VALUE,
    COL_FFR_DATE,
    COL_FFR_VALUE,
    DEFAULT_PRE_LISTING_EXPENSE_RATIO,
    MONTH_KEY_PATTERN,
)
from quant_data.logger import get_logger
from quant_data.revision import RevisionKind

# 모듈 레벨 로거 생성
logger = get_logger(__name__)

# 월별 값의 상한 — 손으로 고치는 운용비율 · % 를 바꿔 쓰는 금리에서 % 그대로인 값(금리 3.63 · 설명서 표기 그대로의 운용비율 0.82)을 잡는다.
# 금리는 1980년대 초 최고치(비율 약 0.19 = 19%), 운용비율은 레버리지 ETF 의 비율 0.01(= 1%) 안팎보다 넉넉히 높게 둔다
MAX_FFR_VALUE = 0.25  # 비율 (0.25 = 25%)
MAX_EXPENSE_VALUE = 0.05  # 비율 (0.05 = 5%)

# 그 달 값이 없을 때 쓸 수 있는 이전 달 값의 최대 차이 (개월) — 넘으면 ValueError
MAX_FFR_MONTHS_DIFF = 2
MAX_EXPENSE_MONTHS_DIFF = 12

# FRED 월별 연방기금금리 (월평균, %)
FRED_FFR_CSV_URL: Final = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
_FRED_COLUMNS: Final = (FRED_DATE_COLUMN, "FEDFUNDS")
_FRED_MONTH_START_PATTERN: Final = rf"{MONTH_KEY_PATTERN}-01"
_FRED_TIMEOUT_SECONDS: Final = 60
# FRED 는 % 2자리 → 비율 4자리라 손실 없음. 더 깊은 값이 와도 잃지 않게 넉넉히 둠
ROUND_MONTHLY_RATE: Final = 6
# 금리 파일이 git 에 CRLF 로 들어 있음 → 같은 줄 끝이어야 diff 에 새 달만 보임
_MONTHLY_CSV_LINE_END: Final = "\r\n"


def load_monthly_data(path: Path) -> pd.DataFrame:
    """
    월별 데이터 CSV(연방기금금리 · 운용비율)를 로드한다. 값 검사는 딕셔너리를 만들 때 한다
    (create_ffr_dict · create_expense_dict).

    Args:
        path: CSV 파일 경로

    Returns:
        월별 DataFrame (DATE: str (yyyy-mm), VALUE: float)

    Raises:
        FileNotFoundError: 파일이 존재하지 않을 때
    """
    if not path.exists():
        raise FileNotFoundError(f"월별 데이터 파일을 찾을 수 없습니다: {path} — git 이 추적하는 파일이니 지워졌다면 저장소에서 되살리세요")

    df = pd.read_csv(path)
    logger.debug(f"월별 데이터 로드 완료: {path} ({len(df)}개월)")

    return df


# ============================================================
# 월별 데이터 딕셔너리 생성 및 조회 함수
# ============================================================


def _create_monthly_data_dict(
    df: pd.DataFrame, date_col: str, value_col: str, data_type: str, max_value: float
) -> dict[str, float]:
    """
    월별 데이터 DataFrame을 딕셔너리로 변환한다 (O(1) 조회용).

    FFR, Expense Ratio 등 월별 데이터를 공통으로 처리하는 제네릭 함수이다.

    Args:
        df: 월별 데이터 DataFrame
        date_col: 날짜 컬럼명 (yyyy-mm 문자열 형식)
        value_col: 값 컬럼명
        data_type: 데이터 타입 ("FFR", "Expense" 등, 에러 메시지용)
        max_value: 값의 상한 (비율, 이 값 이상이면 ValueError)

    Returns:
        {"YYYY-MM": value} 형태의 딕셔너리

    Raises:
        ValueError: 빈 DataFrame, yyyy-mm 이 아닌 월 키, 중복 월, 또는 NaN · inf · max_value 이상인 값 발견 시
    """
    # 1. 빈 DataFrame 검증
    if df.empty:
        raise ValueError(f"{data_type} 데이터가 비어있습니다")

    # 2. 딕셔너리 생성 및 중복 월 검증
    data_dict: dict[str, float] = {}
    for _, row in df.iterrows():
        month_key = str(row[date_col])
        value = float(row[value_col])

        # 조회는 이전 달을 문자열 비교로 고름 → 「2026-3」 같은 키는 에러 없이 안 쓰이고 직전 값이 쓰임
        if not re.fullmatch(MONTH_KEY_PATTERN, month_key):
            raise ValueError(
                f"{data_type} 데이터 오류: 월 키 {month_key!r} 가 yyyy-mm 이 아닙니다 — 파일의 그 줄을 yyyy-mm 으로 고치세요 (예: 2026-3 → 2026-03)"
            )

        # % 로 적은 값이나 빈 칸을 그대로 쓰면 시뮬 종가가 0 이하 · NaN 이 되거나 비용이 수십 배가 된다.
        # 하한은 두지 않는다(음수 금리를 그대로 쓰는 계약)
        if not (math.isfinite(value) and value < max_value):
            raise ValueError(
                f"{data_type} 데이터 오류: 월 {month_key}의 값 {value} — 비율로 {max_value} 미만이어야 합니다"
                f"(% 로 적었는지 확인, 예: 3.63% → 0.0363)"
            )

        # 중복 월 발견 시 즉시 예외 (데이터 무결성 보장)
        if month_key in data_dict:
            raise ValueError(
                f"{data_type} 데이터 무결성 오류: 월 {month_key}이(가) 중복 존재합니다. " f"기존 값: {data_dict[month_key]}, 중복 값: {value}"
            )

        data_dict[month_key] = value

    return data_dict


def _lookup_monthly_data(date_value: date, data_dict: dict[str, float], max_months_diff: int, data_type: str) -> float:
    """
    특정 날짜의 월별 데이터 값을 딕셔너리에서 조회한다.

    FFR, Expense Ratio 등 월별 데이터를 공통으로 조회하는 제네릭 함수이다.

    Args:
        date_value: 조회할 날짜
        data_dict: 월별 데이터 딕셔너리 ({"YYYY-MM": value})
        max_months_diff: 최대 허용 월 차이 (예: FFR=2, Expense=12)
        data_type: 데이터 타입 ("FFR", "Expense" 등, 에러 메시지용)

    Returns:
        해당 월 또는 가장 가까운 이전 월의 값

    Raises:
        ValueError: 월 키 없음 + 이전 월 없음, 또는 월 차이 초과 시
    """
    # 1. 해당 월의 키 생성
    year_month_str = f"{date_value.year:04d}-{date_value.month:02d}"

    # 2. 딕셔너리에서 직접 조회 시도
    if year_month_str in data_dict:
        return data_dict[year_month_str]

    # 3. 월 키가 없으면 이전 월 중 가장 가까운 값 사용
    previous_months = [key for key in data_dict.keys() if key < year_month_str]

    if not previous_months:
        raise ValueError(f"{data_type} 데이터 부족: {year_month_str} 이전의 {data_type} 데이터가 존재하지 않습니다.")

    # 4. 가장 가까운 이전 월 찾기
    closest_month = max(previous_months)

    # 5. 월 차이 계산
    query_year, query_month = date_value.year, date_value.month
    closest_year, closest_month_num = map(int, closest_month.split("-"))
    total_months = (query_year - closest_year) * 12 + (query_month - closest_month_num)

    # 6. 월 차이가 max_months_diff 초과 시 예외
    if total_months > max_months_diff:
        raise ValueError(
            f"{data_type} 데이터 부족: 필요 월 {year_month_str}의 {data_type} 데이터가 없으며, "
            f"가장 가까운 이전 데이터는 {closest_month} ({total_months}개월 전)입니다. "
            f"최대 {max_months_diff}개월 이내의 데이터만 사용 가능합니다."
        )

    # 7. 가장 가까운 이전 월의 값 반환
    return data_dict[closest_month]


def create_ffr_dict(ffr_df: pd.DataFrame) -> dict[str, float]:
    """
    FFR DataFrame을 딕셔너리로 변환한다 (O(1) 조회용).

    내부적으로 제네릭 월별 데이터 함수를 사용한다.

    Args:
        ffr_df: FFR DataFrame (DATE: str (yyyy-mm), VALUE: float)

    Returns:
        {"YYYY-MM": ffr_value} 형태의 딕셔너리

    Raises:
        ValueError: 빈 DataFrame, yyyy-mm 이 아닌 월 키, 중복 월, 또는 NaN · inf · MAX_FFR_VALUE 이상인 값 발견 시
    """
    return _create_monthly_data_dict(ffr_df, COL_FFR_DATE, COL_FFR_VALUE, "FFR", MAX_FFR_VALUE)


def lookup_ffr(date_value: date, ffr_dict: dict[str, float]) -> float:
    """
    특정 날짜의 FFR 값을 딕셔너리에서 조회한다.

    내부적으로 제네릭 월별 데이터 함수를 사용한다.

    Args:
        date_value: 조회할 날짜
        ffr_dict: FFR 딕셔너리 ({"YYYY-MM": ffr_value})

    Returns:
        FFR 값 (0~1 비율, 예: 0.045 = 4.5%)

    Raises:
        ValueError: 월 키 없음 + 이전 월 없음, 또는 월 차이 초과 시
    """
    return _lookup_monthly_data(date_value, ffr_dict, MAX_FFR_MONTHS_DIFF, "FFR")


def create_expense_dict(expense_df: pd.DataFrame) -> dict[str, float]:
    """
    Expense Ratio DataFrame을 딕셔너리로 변환한다 (O(1) 조회용).

    내부적으로 제네릭 월별 데이터 함수를 사용한다.

    Args:
        expense_df: Expense Ratio DataFrame (DATE: str (yyyy-mm), VALUE: float (0~1 비율))

    Returns:
        {"YYYY-MM": expense_value} 형태의 딕셔너리

    Raises:
        ValueError: 빈 DataFrame, yyyy-mm 이 아닌 월 키, 중복 월, 또는 NaN · inf · MAX_EXPENSE_VALUE 이상인 값 발견 시
    """
    return _create_monthly_data_dict(expense_df, COL_EXPENSE_DATE, COL_EXPENSE_VALUE, "Expense", MAX_EXPENSE_VALUE)


def lookup_expense(date_value: date, expense_dict: dict[str, float]) -> float:
    """
    특정 날짜의 Expense Ratio 값을 딕셔너리에서 조회한다.

    내부적으로 제네릭 월별 데이터 함수를 사용한다.

    Args:
        date_value: 조회할 날짜
        expense_dict: Expense Ratio 딕셔너리 ({"YYYY-MM": expense_value})

    Returns:
        Expense Ratio 값 (0~1 비율, 예: 0.0095 = 0.95%)

    Raises:
        ValueError: 월 키 없음 + 이전 월 없음, 또는 월 차이 초과 시
    """
    return _lookup_monthly_data(date_value, expense_dict, MAX_EXPENSE_MONTHS_DIFF, "Expense")


def lookup_funding_spread(date_value: date, spread_dict: dict[str, float]) -> float:
    """
    특정 날짜의 funding spread 값을 딕셔너리에서 조회한다.

    내부적으로 제네릭 월별 데이터 함수를 사용한다.

    Args:
        date_value: 조회할 날짜
        spread_dict: funding spread 딕셔너리 ({"YYYY-MM": spread_value})

    Returns:
        funding spread 값

    Raises:
        ValueError: 월 키 없음 + 이전 월 없음, 또는 월 차이 초과 시
    """
    return _lookup_monthly_data(date_value, spread_dict, MAX_FFR_MONTHS_DIFF, "funding_spread")


def build_extended_expense_dict(expense_df: pd.DataFrame, first_month: str) -> dict[str, float]:
    """
    운용비율 딕셔너리를 생성하고, first_month 부터 파일 첫 달 직전까지 상장 전 고정값으로 채운다.

    운용비율 파일은 TQQQ 상장(2010-02)부터라, 그 앞을 시뮬레이션하는 합성은
    DEFAULT_PRE_LISTING_EXPENSE_RATIO 를 쓴다. first_month 가 파일 첫 달과 같거나 뒤면 채우지 않는다.

    Args:
        expense_df: Expense Ratio DataFrame (DATE: str (yyyy-mm), VALUE: float)
        first_month: 시뮬레이션할 기초 시세의 첫 달 (yyyy-mm)

    Returns:
        first_month 부터 덮는 expense 딕셔너리

    Raises:
        ValueError: first_month 가 YYYY-MM 이 아닐 때, create_expense_dict 와 같은 경우
    """
    if not re.fullmatch(MONTH_KEY_PATTERN, first_month):
        raise ValueError(f"운용비율을 채울 시작 달은 YYYY-MM 이어야 합니다: {first_month!r}")

    expense_dict = create_expense_dict(expense_df)
    fill_months = pd.period_range(first_month, min(expense_dict), freq="M").strftime("%Y-%m")[:-1]
    return {month: DEFAULT_PRE_LISTING_EXPENSE_RATIO for month in fill_months} | expense_dict


# ============================================================
# FRED 월별 연방기금금리 받기
# ============================================================


def parse_fred_ffr_csv(csv_text: str) -> pd.DataFrame:
    """
    FRED 월별 연방기금금리 CSV(%)를 금리 파일 형식으로 바꾼다.

    Args:
        csv_text: FRED fredgraph.csv 본문 (열 observation_date · FEDFUNDS)

    Returns:
        월별 DataFrame (DATE: str (yyyy-mm), VALUE: float (0~1 비율))

    Raises:
        ValueError: 헤더가 다를 때, 값이 하나도 없을 때, 날짜가 그달 1일이 아닐 때, 달이 빠짐없이 이어지지 않을 때,
            값이 비었거나 숫자가 아닐 때(FRED 의 결측 표기 「.」 포함) — 메우지 않는다
    """
    raw = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    if tuple(raw.columns) != _FRED_COLUMNS:
        raise ValueError(f"FRED 금리 CSV 의 헤더가 {list(_FRED_COLUMNS)} 가 아닙니다: {list(raw.columns)} — FRED 형식이 바뀌었는지 확인하세요")
    if raw.empty:
        raise ValueError("FRED 금리 CSV 에 값이 비어 있습니다")

    date_col, value_col = _FRED_COLUMNS
    bad_dates = raw.loc[~raw[date_col].str.fullmatch(_FRED_MONTH_START_PATTERN), date_col].tolist()
    if bad_dates:
        raise ValueError(f"FRED 금리의 날짜가 그달 1일(YYYY-MM-01)이 아닙니다: {bad_dates[:5]} — 월별 시리즈인지 확인하세요")

    # 빠진 달은 조회가 이전 달 값으로 조용히 메움 → 받을 때 막음
    months = raw[date_col].str[:7].tolist()
    gaps = [
        (prev, cur)
        for prev, cur in zip(months, months[1:], strict=False)
        if int(cur[:4]) * 12 + int(cur[5:7]) - (int(prev[:4]) * 12 + int(prev[5:7])) != 1
    ]
    if gaps:
        raise ValueError(f"FRED 금리의 달이 빠짐없이 이어지지 않습니다 (앞 달, 다음 달): {gaps[:5]} — 메우지 않습니다")

    percents = pd.to_numeric(raw[value_col], errors="coerce")
    missing = raw.loc[percents.isna(), date_col].str[:7].tolist()
    if missing:
        raise ValueError(f"FRED 금리 값이 비었거나 숫자가 아닌 달: {missing[:5]} — 메우지 않습니다")

    return pd.DataFrame(
        {
            COL_FFR_DATE: months,
            COL_FFR_VALUE: (percents / 100.0).round(ROUND_MONTHLY_RATE),
        }
    )


def fetch_ffr_monthly() -> pd.DataFrame:
    """
    FRED 월별 연방기금금리 전체 기간을 받아 금리 파일 형식으로 돌려준다 — 파일은 쓰지 않는다.

    Raises:
        ValueError: parse_fred_ffr_csv · create_ffr_dict 와 같은 경우
        urllib.error.URLError: 받지 못했을 때
    """
    with urlopen(FRED_FFR_CSV_URL, timeout=_FRED_TIMEOUT_SECONDS) as response:
        csv_text = response.read().decode("utf-8")

    ffr_df = parse_fred_ffr_csv(csv_text)
    create_ffr_dict(ffr_df)
    logger.debug(f"FRED 연방기금금리 받음: {len(ffr_df)}개월, {ffr_df[COL_FFR_DATE].iloc[0]} ~ {ffr_df[COL_FFR_DATE].iloc[-1]}")
    return ffr_df


def save_monthly_data(df: pd.DataFrame, path: Path) -> None:
    """월별 데이터를 기존 금리 파일과 같은 글자(헤더 DATE,VALUE · 줄 끝 CRLF)로 쓴다. 상위 폴더가 없으면 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator=_MONTHLY_CSV_LINE_END)
    logger.debug(f"월별 데이터 저장: {path} ({len(df)}개월)")


@dataclass(frozen=True)
class MonthlyRevision:
    """덧붙이기 판정 — values 는 이 판정대로 저장할 표(비정상이면 사람이 --accept 했을 때 저장할 응답)."""

    kind: RevisionKind
    values: pd.DataFrame
    issues: tuple[str, ...]


def judge_monthly_append(existing: pd.DataFrame | None, response: pd.DataFrame) -> MonthlyRevision:
    """
    다시 받은 월별 금리를 기존 파일과 견준다 — 지난 달 값이 저장 자릿수의 반 단위 안에서 그대로이고 빠진 달이 없으면
    기존 행 그대로에 기존 마지막 달 뒤의 새 달만 붙이고(NOISE), 아니면 비정상이다. 기존 파일이 없으면 응답 그대로(NEW).

    Args:
        existing: 기존 파일 (load_monthly_data 모양). 없으면 None
        response: 받은 금리 (fetch_ffr_monthly 모양)

    Returns:
        MonthlyRevision
    """
    if existing is None:
        return MonthlyRevision(RevisionKind.NEW, response.reset_index(drop=True), ())

    stored = dict(zip(existing[COL_FFR_DATE].astype(str), existing[COL_FFR_VALUE].astype(float), strict=True))
    received = dict(zip(response[COL_FFR_DATE].astype(str), response[COL_FFR_VALUE].astype(float), strict=True))
    last_month = max(stored)
    half_unit = 0.5 * 10.0**-ROUND_MONTHLY_RATE

    issues: list[str] = []
    missing = sorted(set(stored) - set(received))
    if missing:
        issues.append(f"기존 달 {len(missing)}개가 응답에 없음 — {_month_span(missing)}")
    changed = sorted(m for m in set(stored) & set(received) if abs(received[m] - stored[m]) > half_unit)
    if changed:
        shown = " · ".join(f"{m} {stored[m]:g} → {received[m]:g}" for m in changed[:5])
        issues.append(f"기존 달 {len(changed)}개의 값이 바뀜 — {shown}")
    inside = sorted(m for m in set(received) - set(stored) if m < last_month)
    if inside:
        issues.append(f"기존 마지막 달({last_month}) 앞에 새 달 {len(inside)}개가 생김 — {_month_span(inside)}")
    if issues:
        return MonthlyRevision(RevisionKind.ABNORMAL, response.reset_index(drop=True), tuple(issues))

    new_rows = response[response[COL_FFR_DATE].astype(str) > last_month]
    kept = pd.concat([existing, new_rows], ignore_index=True)
    return MonthlyRevision(RevisionKind.NOISE, kept, ())


def _month_span(months: list[str]) -> str:
    return months[0] if len(months) == 1 else f"{months[0]} ~ {months[-1]}"
