"""대용 시계열 유틸리티

실물 ETF 가 상장하기 전 기간을 비슷하게 움직이는 다른 시세(대용)로 채운다.
이음매는 실물 첫 거래일이고, 대용은 그날 종가 비율로 스케일해 잇는다.
"""

import pandas as pd

from quant_data.constants import (
    ANNUAL_DAYS,
    COL_CLOSE,
    COL_DATE,
    COL_OPEN,
    COL_VOLUME,
    PRICE_COLUMNS,
    REQUIRED_COLUMNS,
)


def require_strictly_increasing_dates(df: pd.DataFrame, name: str) -> None:
    if df.empty:
        raise ValueError(f"{name} 시세가 비어 있습니다")
    dates = df[COL_DATE]
    if not (dates.is_monotonic_increasing and dates.is_unique):
        raise ValueError(f"{name} 시세의 날짜가 중복 없는 오름차순이 아닙니다 — load_stock_data 로 읽은 시세를 넘기세요")


def compute_seam_scale(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> float:
    """실물 첫 거래일(이음매) 종가 ÷ 그날 대용 종가.

    Raises:
        ValueError: 날짜가 중복 없는 오름차순이 아니거나, 이음매 날짜가 대용에 없을 때
    """
    require_strictly_increasing_dates(proxy_df, "대용")
    require_strictly_increasing_dates(actual_df, "실물")
    seam_date = actual_df[COL_DATE].iloc[0]
    seam_rows = proxy_df[proxy_df[COL_DATE] == seam_date]
    if seam_rows.empty:
        raise ValueError(f"이음매(실물 첫 거래일 {seam_date})가 대용 시세에 없습니다 — 대용 시세의 기간을 확인하세요")
    return float(actual_df[COL_CLOSE].iloc[0]) / float(seam_rows[COL_CLOSE].iloc[0])


def rescale_to_actual(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """대용 전 구간의 가격을 이음매 종가에 맞춘다. 수익률과 거래량은 바뀌지 않는다.

    Raises:
        ValueError: compute_seam_scale 과 같다
    """
    scale = compute_seam_scale(proxy_df, actual_df)
    result = proxy_df[REQUIRED_COLUMNS].copy()
    result[PRICE_COLUMNS] = result[PRICE_COLUMNS] * scale
    return result


def splice_proxy(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """이음매 앞은 스케일한 대용(거래량 0), 이음매부터는 실물 행 그대로인 시계열.

    이음매 날의 종가 수익률은 대용의 수익률이고, 그 다음 날부터 실물 수익률이다.

    Raises:
        ValueError: compute_seam_scale 과 같은 경우, 이음매 앞 대용 행이 없을 때
    """
    rescaled = rescale_to_actual(proxy_df, actual_df)
    seam_date = actual_df[COL_DATE].iloc[0]
    before_seam = rescaled[rescaled[COL_DATE] < seam_date].copy()
    if before_seam.empty:
        raise ValueError(f"이음매(실물 첫 거래일 {seam_date}) 앞의 대용 시세가 없어 채울 구간이 없습니다")
    # 대용의 거래량은 실물 거래량이 아니다
    before_seam[COL_VOLUME] = 0
    return pd.concat([before_seam, actual_df[REQUIRED_COLUMNS]], ignore_index=True)


def deduct_annual_fee(proxy_df: pd.DataFrame, annual_fee_rate: float) -> pd.DataFrame:
    """대용에서 상품의 연 보수를 뺀다 — 첫 행부터 달력일로 잰 경과 연수 t 마다 가격 넷 × (1 − 보수)^t.

    보수가 빠진 대용(금값처럼 상품이 아닌 시세)을 그 상품처럼 만든다. 거래량 · 날짜는 그대로다.

    Args:
        proxy_df: 날짜가 중복 없는 오름차순인 대용 시세
        annual_fee_rate: 연 보수 비율 (0.004 = 0.4%)

    Raises:
        ValueError: 보수가 0 이상 1 미만이 아니거나, 날짜가 중복 없는 오름차순이 아닐 때
    """
    if not 0 <= annual_fee_rate < 1:
        raise ValueError(f"연 보수(annual_fee_rate)는 0 이상 1 미만의 비율이어야 합니다(0.004 = 0.4%): {annual_fee_rate}")
    require_strictly_increasing_dates(proxy_df, "대용")
    dates = pd.to_datetime(proxy_df[COL_DATE])
    # 보수는 해마다 매김 → 거래일 수가 아니라 달력일로 셈 (빈 거래일이 있어도 해마다 같은 보수)
    elapsed_years = (dates - dates.iloc[0]).dt.days / ANNUAL_DAYS
    result = proxy_df.copy()
    result[PRICE_COLUMNS] = result[PRICE_COLUMNS].mul((1 - annual_fee_rate) ** elapsed_years, axis=0)
    return result


def build_proxy_synthetic(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """1배 대용 합성 시세 — 이음매 앞은 시가를 그날 종가로 바꾼 대용, 이음매부터는 실물 행 그대로.

    지수 · 펀드 대용에는 진짜 시가가 없어 그날 종가로 둔다 — 신호 다음 날 시가 체결이 그날 종가 체결이 된다
    (근거: `docs/research/합성_시세_연장.md` 결정 3).

    Raises:
        ValueError: splice_proxy 와 같다
        RuntimeError: 이어 붙인 결과의 이음매 뒤 행이 실물과 다를 때 (내부 불변조건 위반 — 저장 전에 멈춘다)
    """
    proxy = proxy_df.copy()
    proxy[COL_OPEN] = proxy[COL_CLOSE]
    spliced = splice_proxy(proxy, actual_df)
    require_rows_from_seam_equal_actual(spliced, actual_df)
    return spliced


def require_rows_from_seam_equal_actual(spliced: pd.DataFrame, actual_df: pd.DataFrame) -> None:
    """이어 붙인 시세의 이음매(실물 첫 거래일)부터 행이 실물 행과 같은지 본다 — 저장 전 검사 (불변 조건 ⑥).

    Raises:
        RuntimeError: 다를 때 (내부 불변조건 위반)
    """
    seam_date = actual_df[COL_DATE].iloc[0]
    from_seam = spliced[spliced[COL_DATE] >= seam_date].reset_index(drop=True)
    expected = actual_df[REQUIRED_COLUMNS].reset_index(drop=True)
    if not from_seam.equals(expected):
        raise RuntimeError(f"내부 불변조건 위반: 이음매({seam_date}) 뒤 행이 실물과 다릅니다 — 실물 {len(expected)}행, 결과 {len(from_seam)}행")
