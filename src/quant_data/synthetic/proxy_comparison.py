"""대용 ↔ 실물 비교 유틸리티

대용 시세가 실물 ETF 를 얼마나 잘 따르는지 잰다.
비교는 실물 첫 거래일부터 두 시세가 모두 있는 날만 쓴다 — 상장 전 구간은 대조할 실물이 없고,
시장 달력이 다른 선물 · 펀드의 빈 날을 메우면 이틀 수익률이 하루로 합쳐진다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from quant_data.constants import ANNUAL_DAYS, COL_CLOSE, COL_DATE, ROUND_PERCENT, ROUND_RATIO, TRADING_DAYS_PER_YEAR
from quant_data.synthetic.proxy_series import require_strictly_increasing_dates

COL_PROXY: Final = "proxy"
COL_ACTUAL: Final = "actual"
ROLLING_WINDOW_DAYS: Final = TRADING_DAYS_PER_YEAR  # 12개월 이동 상관의 창 (거래일)

# 결과 표의 열 이름
DISPLAY_START: Final = "비교 시작일"
DISPLAY_END: Final = "비교 끝날"
DISPLAY_TRADING_DAYS: Final = "거래일 수"
DISPLAY_DAILY_CORR: Final = "일간 상관"
DISPLAY_MONTHLY_CORR: Final = "월간 상관"
DISPLAY_MONTHS: Final = "비교 달 수"
DISPLAY_PROXY_CAGR: Final = "대용 CAGR(%)"
DISPLAY_ACTUAL_CAGR: Final = "실물 CAGR(%)"
DISPLAY_CAGR_DIFF: Final = "CAGR 차(%p)"
DISPLAY_PROXY_MDD: Final = "대용 MDD(%)"
DISPLAY_ACTUAL_MDD: Final = "실물 MDD(%)"
DISPLAY_MDD_DIFF: Final = "MDD 차(%p)"
DISPLAY_ROLLING_MIN: Final = "12개월 상관 최저"
DISPLAY_ROLLING_MIN_DATE: Final = "최저 날짜"
DISPLAY_PERIOD: Final = "기간"
DISPLAY_PROXY_RETURN: Final = "대용 수익률(%)"
DISPLAY_ACTUAL_RETURN: Final = "실물 수익률(%)"
DISPLAY_RETURN_DIFF: Final = "수익률 차(%p)"
DISPLAY_PROXY_ONLY_DAYS: Final = "대용에만 있는 날"
DISPLAY_ACTUAL_ONLY_DAYS: Final = "실물에만 있는 날"
# 저장 · 표시할 때 자릿수를 고르는 열 종류 (상관 = 비율, 나머지 = %)
RATIO_DISPLAY_COLUMNS: Final = (DISPLAY_DAILY_CORR, DISPLAY_MONTHLY_CORR, DISPLAY_ROLLING_MIN)
PERCENT_DISPLAY_COLUMNS: Final = (
    DISPLAY_PROXY_CAGR,
    DISPLAY_ACTUAL_CAGR,
    DISPLAY_CAGR_DIFF,
    DISPLAY_PROXY_MDD,
    DISPLAY_ACTUAL_MDD,
    DISPLAY_MDD_DIFF,
    DISPLAY_PROXY_RETURN,
    DISPLAY_ACTUAL_RETURN,
    DISPLAY_RETURN_DIFF,
)


@dataclass(frozen=True)
class Period:
    """비교 기간 하나 (양 끝 포함)."""

    name: str
    start: date
    end: date


@dataclass(frozen=True)
class PairSummary:
    """겹치는 기간 전체의 비교. CAGR · MDD 는 % (MDD 는 음수), 계산할 수 없는 값은 None."""

    start: date
    end: date
    trading_days: int
    daily_corr: float | None
    monthly_corr: float | None
    months: int
    proxy_cagr: float
    actual_cagr: float
    proxy_mdd: float
    actual_mdd: float
    rolling_corr_min: float | None
    rolling_corr_min_date: date | None

    @property
    def cagr_diff(self) -> float:
        return self.proxy_cagr - self.actual_cagr

    @property
    def mdd_diff(self) -> float:
        return self.proxy_mdd - self.actual_mdd


@dataclass(frozen=True)
class PeriodSummary:
    """기간 하나의 비교. start · end 는 겹치는 범위로 자른 실제 날짜, 수익률은 %."""

    name: str
    start: date
    end: date
    trading_days: int
    daily_corr: float | None
    proxy_return: float
    actual_return: float

    @property
    def return_diff(self) -> float:
        return self.proxy_return - self.actual_return


def _require_aligned(aligned: pd.DataFrame) -> None:
    """align_closes 가 만든 표인지 확인한다 — 날짜가 어긋난 표를 받으면 전날 종가 · 월 묶음이 조용히 틀린다."""
    expected = [COL_DATE, COL_PROXY, COL_ACTUAL]
    if list(aligned.columns) != expected:
        raise ValueError(f"align_closes 가 만든 표(열 {expected})를 넘기세요: 받은 열 {list(aligned.columns)}")
    if len(aligned) < 2:
        raise ValueError(f"비교할 날이 2개 이상 필요합니다: {len(aligned)}개")
    dates = aligned[COL_DATE]
    if not (dates.is_monotonic_increasing and dates.is_unique):
        raise ValueError("비교 표의 날짜가 중복 없는 오름차순이 아닙니다 — align_closes 가 만든 표를 그대로 넘기세요")


def _ratio_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """종가 수익률 (첫 행 NaN). pct_change 는 결측을 앞 값으로 메우는 기본값이 있어 쓰지 않는다."""
    return closes / closes.shift(1) - 1.0


def _correlation(a: pd.Series, b: pd.Series) -> float | None:
    """피어슨 상관. 값이 2쌍 미만이거나 한쪽이 움직이지 않으면(분산 0) 정의되지 않아 None."""
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 2:
        return None
    first, second = pair.iloc[:, 0], pair.iloc[:, 1]
    if float(first.std()) == 0.0 or float(second.std()) == 0.0:
        return None
    return float(first.corr(second))


def align_closes(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """실물 첫 거래일부터 두 시세의 끝 중 이른 날까지, 두 시세 모두 있는 날의 종가 (열: 날짜 · 대용 · 실물).

    Raises:
        ValueError: 날짜가 중복 없는 오름차순이 아닐 때, 겹치는 날이 2개 미만일 때
    """
    require_strictly_increasing_dates(proxy_df, "대용")
    require_strictly_increasing_dates(actual_df, "실물")

    proxy = proxy_df[[COL_DATE, COL_CLOSE]].rename(columns={COL_CLOSE: COL_PROXY})
    actual = actual_df[[COL_DATE, COL_CLOSE]].rename(columns={COL_CLOSE: COL_ACTUAL})
    merged = proxy.merge(actual, on=COL_DATE, how="inner")
    if len(merged) < 2:
        start = actual_df[COL_DATE].iloc[0]
        raise ValueError(f"두 시세의 겹치는 날이 2개 미만입니다({len(merged)}개) — 실물 첫 거래일 {start} 이후에 대용 시세가 있는지 확인하세요")
    return merged[[COL_DATE, COL_PROXY, COL_ACTUAL]]


@dataclass(frozen=True)
class UnmatchedDays:
    """align_closes 가 견주는 기간 안에서 한쪽 시세에만 있는 날 수 — 비교에서 빠진 날."""

    proxy_only: int
    actual_only: int


def count_unmatched_days(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> UnmatchedDays:
    """실물 첫 거래일 ~ 두 시세의 끝 중 이른 날 안에서 대용에만 · 실물에만 있는 날을 센다.

    시장 달력이 다른 대용(금 · 선물)은 상관이 몇 날로 계산됐는지가 이 수로 드러난다.

    Raises:
        ValueError: 날짜가 중복 없는 오름차순이 아닐 때
    """
    require_strictly_increasing_dates(proxy_df, "대용")
    require_strictly_increasing_dates(actual_df, "실물")
    start = actual_df[COL_DATE].iloc[0]
    end = min(proxy_df[COL_DATE].iloc[-1], actual_df[COL_DATE].iloc[-1])

    def within(df: pd.DataFrame) -> set[date]:
        dates = df[COL_DATE]
        return set(dates[(dates >= start) & (dates <= end)].tolist())

    proxy_dates, actual_dates = within(proxy_df), within(actual_df)
    return UnmatchedDays(proxy_only=len(proxy_dates - actual_dates), actual_only=len(actual_dates - proxy_dates))


def unmatched_days_record(unmatched: UnmatchedDays) -> dict[str, object]:
    """비교에서 빠진 날의 결과 표 열."""
    return {DISPLAY_PROXY_ONLY_DAYS: unmatched.proxy_only, DISPLAY_ACTUAL_ONLY_DAYS: unmatched.actual_only}


def rolling_correlation(aligned: pd.DataFrame, window: int) -> pd.Series:
    """일간 수익률의 이동 상관 (인덱스 = 날짜). 창이 차기 전은 NaN.

    Raises:
        ValueError: 창이 2 미만일 때, align_closes 가 만든 표가 아닐 때
    """
    if window < 2:
        raise ValueError(f"이동 상관의 창은 2 이상이어야 합니다: {window}")
    _require_aligned(aligned)
    returns = _ratio_returns(aligned[[COL_PROXY, COL_ACTUAL]])
    corr = returns[COL_PROXY].rolling(window).corr(returns[COL_ACTUAL])
    corr.index = pd.Index(aligned[COL_DATE].tolist())
    return corr


def summarize_pair(aligned: pd.DataFrame, rolling_window: int = ROLLING_WINDOW_DAYS) -> PairSummary:
    """겹치는 기간 전체의 상관 · CAGR · MDD · 이동 상관 최저값.

    월간 상관은 월 마지막 거래일 종가의 수익률이라 첫 달의 부분 수익은 빠진다.

    Raises:
        ValueError: align_closes 가 만든 표가 아닐 때 (열 · 2행 이상 · 날짜 순서)
    """
    _require_aligned(aligned)
    closes = aligned[[COL_PROXY, COL_ACTUAL]]
    dates = aligned[COL_DATE]

    daily = _ratio_returns(closes)
    month_key = pd.to_datetime(dates).dt.to_period("M")
    monthly = _ratio_returns(closes.groupby(month_key).last()).dropna()

    days = (dates.iloc[-1] - dates.iloc[0]).days
    cagr = ((closes.iloc[-1] / closes.iloc[0]) ** (ANNUAL_DAYS / days) - 1.0) * 100.0
    mdd = (closes / closes.cummax() - 1.0).min() * 100.0

    rolling = rolling_correlation(aligned, rolling_window).dropna()
    rolling_min: float | None = None
    min_date: date | None = None
    if not rolling.empty:
        position = int(np.argmin(rolling.to_numpy()))
        rolling_min = float(rolling.iloc[position])
        min_date = rolling.index[position]

    return PairSummary(
        start=dates.iloc[0],
        end=dates.iloc[-1],
        trading_days=len(aligned),
        daily_corr=_correlation(daily[COL_PROXY], daily[COL_ACTUAL]),
        monthly_corr=_correlation(monthly[COL_PROXY], monthly[COL_ACTUAL]),
        months=len(monthly),
        proxy_cagr=float(cagr[COL_PROXY]),
        actual_cagr=float(cagr[COL_ACTUAL]),
        proxy_mdd=float(mdd[COL_PROXY]),
        actual_mdd=float(mdd[COL_ACTUAL]),
        rolling_corr_min=rolling_min,
        rolling_corr_min_date=min_date,
    )


def summarize_periods(aligned: pd.DataFrame, periods: Sequence[Period]) -> list[PeriodSummary]:
    """기간마다 겹치는 범위로 잘라 상관 · 수익률을 잰다. 자른 범위의 거래일이 2개 미만인 기간은 뺀다.

    수익률의 기준은 기간 첫날의 전날 종가다 — 그날 하루의 움직임도 그 기간에 넣기 위해서다.
    전날이 없으면(겹치는 기간의 첫날) 첫날 종가를 기준으로 한다.

    Raises:
        ValueError: 시작이 끝보다 늦은 기간이 있을 때, align_closes 가 만든 표가 아닐 때
    """
    _require_aligned(aligned)
    closes = aligned[[COL_PROXY, COL_ACTUAL]]
    daily = _ratio_returns(closes)
    dates = aligned[COL_DATE]
    summaries: list[PeriodSummary] = []
    for period in periods:
        if period.start > period.end:
            raise ValueError(f"기간의 시작이 끝보다 늦습니다: {period}")
        mask = ((dates >= period.start) & (dates <= period.end)).to_numpy()
        positions = np.flatnonzero(mask)
        if len(positions) < 2:
            continue
        first, last = int(positions[0]), int(positions[-1])
        base_position = first - 1 if first > 0 else first
        period_return = (closes.iloc[last] / closes.iloc[base_position] - 1.0) * 100.0
        summaries.append(
            PeriodSummary(
                name=period.name,
                start=dates.iloc[first],
                end=dates.iloc[last],
                trading_days=len(positions),
                daily_corr=_correlation(daily[COL_PROXY][mask], daily[COL_ACTUAL][mask]),
                proxy_return=float(period_return[COL_PROXY]),
                actual_return=float(period_return[COL_ACTUAL]),
            )
        )
    return summaries


def calendar_year_periods(start: date, end: date) -> list[Period]:
    """연도 기간 목록. 첫 해 · 마지막 해는 start · end 로 자른 부분 연도다.

    Raises:
        ValueError: 시작이 끝보다 늦을 때
    """
    if start > end:
        raise ValueError(f"시작이 끝보다 늦습니다: {start} > {end}")
    return [
        Period(str(year), max(date(year, 1, 1), start), min(date(year, 12, 31), end))
        for year in range(start.year, end.year + 1)
    ]


def pair_summary_record(summary: PairSummary) -> dict[str, object]:
    """전체 비교 한 행 — 표시용 열 이름, 반올림 전 값. 차이는 대용 − 실물."""
    return {
        DISPLAY_START: summary.start,
        DISPLAY_END: summary.end,
        DISPLAY_TRADING_DAYS: summary.trading_days,
        DISPLAY_DAILY_CORR: summary.daily_corr,
        DISPLAY_MONTHLY_CORR: summary.monthly_corr,
        DISPLAY_MONTHS: summary.months,
        DISPLAY_PROXY_CAGR: summary.proxy_cagr,
        DISPLAY_ACTUAL_CAGR: summary.actual_cagr,
        DISPLAY_CAGR_DIFF: summary.cagr_diff,
        DISPLAY_PROXY_MDD: summary.proxy_mdd,
        DISPLAY_ACTUAL_MDD: summary.actual_mdd,
        DISPLAY_MDD_DIFF: summary.mdd_diff,
        DISPLAY_ROLLING_MIN: summary.rolling_corr_min,
        DISPLAY_ROLLING_MIN_DATE: summary.rolling_corr_min_date,
    }


def round_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """결과 표의 비율 열은 ROUND_RATIO, % 열은 ROUND_PERCENT 자리로 반올림한다. 표에 없는 열은 건너뛴다
    (전체 표와 기간별 표의 열이 다르다)."""
    digits = {col: ROUND_RATIO for col in RATIO_DISPLAY_COLUMNS} | {
        col: ROUND_PERCENT for col in PERCENT_DISPLAY_COLUMNS
    }
    return df.round({col: digit for col, digit in digits.items() if col in df.columns})


def period_summary_records(summaries: Sequence[PeriodSummary]) -> list[dict[str, object]]:
    """기간별 비교 행 — 표시용 열 이름, 반올림 전 값. 차이는 대용 − 실물."""
    return [
        {
            DISPLAY_PERIOD: summary.name,
            DISPLAY_START: summary.start,
            DISPLAY_END: summary.end,
            DISPLAY_TRADING_DAYS: summary.trading_days,
            DISPLAY_DAILY_CORR: summary.daily_corr,
            DISPLAY_PROXY_RETURN: summary.proxy_return,
            DISPLAY_ACTUAL_RETURN: summary.actual_return,
            DISPLAY_RETURN_DIFF: summary.return_diff,
        }
        for summary in summaries
    ]
