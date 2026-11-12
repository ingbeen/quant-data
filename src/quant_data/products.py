"""가공 — 합성 시세와 그 검증 표를 만든다 (갱신이 받은 표를 받고, 파일은 쓰지 않는다)

1. 1배 대용 합성 (PROXY_TARGETS 와 GLD): 실물 첫 거래일 앞은 그날 종가 비율로 맞춘 대용(시가 = 그날 종가), 그날부터
   실물 행 그대로. GLD 의 대용은 미국 거래일에 붙인 금 사슬 「Perth 호주달러 × 환율 → Perth 달러 → 금 선물」에서 GLD
   운용보수를 뺀 것이다. 검증 ① 대용 ↔ 실물 — 금 사슬은 이음매마다
2. 레버리지 합성 (leveraged.constants.LEVERAGED_SYNTHETIC_TARGETS): 저장할 값(6자리)으로 반올림한 1배 합성을 상장일까지
   굴려 잇는다
3. 검증 ④ 가정만 바꾼 시나리오. ② 추적 · ③ 펀드 대조는 고정 시점 기록이라 만들지 않는다(결정 Q32)
4. 국내 수정주가(C-2): 표의 국내 ETF 마다 KRX 원본가 · 야후 분배 기록으로 `_adjusted` 를 만들고 야후 분배 대조를 붙인다

검증 숫자로는 멈추지 않는다 — 멈추는 것은 이어 붙인 결과의 이음매 뒤 행이 실물과 다를 때와, 상품 표와 ④ 대상 표의
기초가 어긋날 때다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.catalog import CATALOG, Dataset, Kind, kr_adjusted_path
from quant_data.constants import (
    AUD_USD_DATA_PATH,
    COL_DATE,
    EXPENSE_RATIO_DATA_PATH,
    FFR_DATA_PATH,
    PERTH_MINT_GOLD_DATA_PATH,
    ROUND_PERCENT,
    VALIDATION_DIR,
)
from quant_data.domestic import build_kr_adjusted
from quant_data.leveraged.comparison import SCENARIO_ADOPTED, AssumptionResult, annual_gap_rate, assumption_scenarios
from quant_data.leveraged.monthly_data import load_monthly_data
from quant_data.leveraged.synthetic import LeveragedRun, build_leveraged_synthetics
from quant_data.logger import get_logger
from quant_data.prices import PriceBasis, load_prices, price_path, round_prices
from quant_data.series import load_series
from quant_data.synthetic.gold_proxy import build_gold_proxy, load_gold_proxy_sources
from quant_data.synthetic.proxy_comparison import (
    DISPLAY_END,
    DISPLAY_START,
    PairSummary,
    align_closes,
    calendar_year_periods,
    count_unmatched_days,
    pair_summary_record,
    period_summary_records,
    round_for_display,
    summarize_pair,
    summarize_periods,
    unmatched_days_record,
)
from quant_data.synthetic.proxy_series import build_proxy_synthetic, deduct_annual_fee
from quant_data.update import Products

logger = get_logger(__name__)

_RAW = PriceBasis.RAW
_ADJUSTED = PriceBasis.ADJUSTED
_SYNTHETIC = PriceBasis.SYNTHETIC

# 1배 대용 합성 대상 — (이름, 대용 시세, 실물 시세, 저장 경로)
PROXY_TARGETS: Final[tuple[tuple[str, Path, Path, Path], ...]] = (
    ("QQQ", price_path("^NDX", _RAW), price_path("QQQ", _ADJUSTED), price_path("QQQ", _SYNTHETIC)),
    ("SPY", price_path("VFINX", _ADJUSTED), price_path("SPY", _ADJUSTED), price_path("SPY", _SYNTHETIC)),
    ("TLT", price_path("VUSTX", _ADJUSTED), price_path("TLT", _ADJUSTED), price_path("TLT", _SYNTHETIC)),
)

GLD_ACTUAL_PATH: Final = price_path("GLD", _ADJUSTED)
GLD_SYNTHETIC_PATH: Final = price_path("GLD", _SYNTHETIC)
GOLD_FUTURES_PATH: Final = price_path("GC=F", _ADJUSTED)
# 금 사슬을 붙일 미국 거래일 — 1980-01-02 부터 있는 저장소 시세는 VFINX 뿐이고, 첫날이 금 합성의 첫날 (결정 6)
US_CALENDAR_DATA_PATH: Final = price_path("VFINX", _ADJUSTED)
# 금 사슬은 금값이라 상품 보수가 없음 → GLD 처럼 덜 좋게 잡으려고 뺌 (결정 13)
GLD_EXPENSE_RATIO: Final = 0.004  # GLD 운용보수 비율 (0.004 = 0.4%)

# 검증 ④ 대상 — (1배 기초, 구간 끝을 정하는 첫 레버리지 상품, 배당 보정 폭을 잴 1배 대상 — None 이면 배당 보정 시나리오 없음)
ASSUMPTION_TARGETS: Final[tuple[tuple[Path, Path, str | None], ...]] = (
    (price_path("QQQ", _SYNTHETIC), price_path("UOPIX", _ADJUSTED), "QQQ"),
    # VFINX 는 배당을 담음 → 보정할 것이 없음
    (price_path("SPY", _SYNTHETIC), price_path("RYNVX", _ADJUSTED), None),
)

SUMMARY_PATH: Final = VALIDATION_DIR / "summary.csv"  # ① 요약
YEARS_PATH: Final = VALIDATION_DIR / "years.csv"  # ① 연도별
ASSUMPTIONS_PATH: Final = VALIDATION_DIR / "assumptions.csv"  # ④

DISPLAY_TARGET: Final = "대상"
DISPLAY_PROXY_FILE: Final = "대용 파일"
DISPLAY_ACTUAL_FILE: Final = "실물 파일"
DISPLAY_PROXY_FIRST_DATE: Final = "대용 첫날"
DISPLAY_SCENARIO: Final = "시나리오"
DISPLAY_PRODUCT: Final = "상품"
DISPLAY_LEVERAGE: Final = "배율"
DISPLAY_CAGR: Final = "CAGR(%)"
DISPLAY_MDD: Final = "MDD(%)"
DISPLAY_SCENARIO_CAGR_DIFF: Final = "채택 대비 CAGR 차(%p)"
DISPLAY_SCENARIO_MDD_DIFF: Final = "채택 대비 MDD 차(%p)"


@dataclass(frozen=True)
class _ProxyPair:
    """검증 ① 한 줄의 재료 — 대용 · 실물과 그 이름."""

    name: str
    proxy_label: str
    actual_label: str
    proxy: pd.DataFrame
    actual: pd.DataFrame


class _Inputs:
    """가공 입력 — 이번에 쓸 표가 있으면 그것, 없으면 저장소의 파일. 시세는 저장된 값(6자리)과 같다."""

    def __init__(self, root: Path, updated: Mapping[Path, pd.DataFrame]) -> None:
        self._root = root
        self._updated = updated
        self._made: dict[Path, pd.DataFrame] = {}

    def prices(self, path: Path) -> pd.DataFrame:
        if path in self._made:
            return self._made[path].copy()
        if path in self._updated:
            return self._updated[path].copy()
        return load_prices(self._root / path)

    def monthly(self, path: Path) -> pd.DataFrame:
        if path in self._updated:
            return self._updated[path].copy()
        return load_monthly_data(self._root / path)

    def series(self, path: Path) -> pd.DataFrame:
        if path in self._updated:
            return self._updated[path].copy()
        return load_series(self._root / path)

    def remember(self, path: Path, synthetic: pd.DataFrame) -> None:
        """만든 합성을 저장될 값으로 반올림해 둔다 — 레버리지 합성이 파일만으로 다시 만든 결과와 마지막 자리까지 같게."""
        self._made[path] = round_prices(synthetic)


def build_products(root: Path, updated: Mapping[Path, pd.DataFrame]) -> Products:
    """
    합성 시세 전부와 검증 표 ① · ④ 를 만든다.

    Args:
        root: 저장소 루트
        updated: 이번 갱신이 쓸 표 (저장소 루트 기준 경로 → 표)

    Raises:
        ValueError: 입력 파일이 없거나 검사에 걸릴 때, 이어 붙일 수 없을 때, 검증 ④ 대상 표와 상품 표의 기초가 어긋날 때
        RuntimeError: 이어 붙인 결과의 이음매 뒤 행이 실물과 다를 때 (내부 불변조건 위반)
    """
    inputs = _Inputs(root, updated)
    prices: dict[Path, pd.DataFrame] = {}

    pairs: list[_ProxyPair] = []
    for name, proxy_path, actual_path, output_path in PROXY_TARGETS:
        proxy_df = inputs.prices(proxy_path)
        actual_df = inputs.prices(actual_path)
        prices[output_path] = _proxy_synthetic(name, proxy_df, actual_df, proxy_path.name)
        inputs.remember(output_path, prices[output_path])
        pairs.append(_ProxyPair(name, proxy_path.name, actual_path.name, proxy_df, actual_df))
    gold_pairs = _gold_pairs(root, inputs)
    prices[GLD_SYNTHETIC_PATH] = _proxy_synthetic(
        "GLD", gold_pairs[0].proxy, gold_pairs[0].actual, f"금 사슬 ({gold_pairs[0].proxy_label})"
    )
    pairs.extend(gold_pairs)
    summaries, summary_table, years_table = _proxy_tables(pairs)

    ffr_df = inputs.monthly(FFR_DATA_PATH)
    expense_df = inputs.monthly(EXPENSE_RATIO_DATA_PATH)
    runs = build_leveraged_synthetics(ffr_df, expense_df, inputs.prices)
    for run in runs:
        prices[run.output_path] = run.synthetic

    tables = {
        SUMMARY_PATH: summary_table,
        YEARS_PATH: years_table,
        ASSUMPTIONS_PATH: _assumptions_table(runs, ffr_df, expense_df, summaries, inputs),
    }
    kr_prices, kr_notes = build_kr_products(root, updated, [d for d in CATALOG if d.kind is Kind.KRX_ETF])
    prices.update(kr_prices)
    return Products(prices=prices, tables=tables, notes=kr_notes)


def build_kr_products(
    root: Path, updated: Mapping[Path, pd.DataFrame], datasets: Sequence[Dataset]
) -> tuple[dict[Path, pd.DataFrame], dict[Path, tuple[str, ...]]]:
    """
    국내 ETF 마다 원본가 · 야후 분배 기록(이번 표, 없으면 파일)으로 국내 수정주가를 만든다 — (시세, 야후 분배 대조 어긋남).

    Raises:
        FileNotFoundError: 원본가 · 분배 기록 파일이 없을 때
        ValueError: 기준가가 0 이하일 때 (build_kr_adjusted)
    """
    inputs = _Inputs(root, updated)
    prices: dict[Path, pd.DataFrame] = {}
    notes: dict[Path, tuple[str, ...]] = {}
    for dataset in datasets:
        raw_path, dividends_path = dataset.files
        result = build_kr_adjusted(inputs.prices(raw_path), inputs.series(dividends_path))
        output = kr_adjusted_path(dataset.name)
        prices[output] = result.prices
        notes[output] = result.notes
        logger.debug(f"국내 수정주가 {dataset.name}: {len(result.prices):,}행, 야후 분배 대조 어긋남 {len(result.notes)}건")
    return prices, notes


def _proxy_synthetic(name: str, proxy_df: pd.DataFrame, actual_df: pd.DataFrame, proxy_label: str) -> pd.DataFrame:
    synthetic_df = build_proxy_synthetic(proxy_df, actual_df)
    logger.debug(
        f"{name}: 이음매 {actual_df[COL_DATE].iloc[0]} 앞 {len(synthetic_df) - len(actual_df):,}행을 "
        f"{proxy_label} 로 채움, 이음매 뒤 {len(actual_df):,}행은 실물과 같음"
    )
    return synthetic_df


def _gold_pairs(root: Path, inputs: _Inputs) -> list[_ProxyPair]:
    """GLD 의 대용(보수를 뺀 금 사슬)과 사슬 안 이음매 둘 — 첫 줄이 GLD.

    사슬 안 이음매 둘(GC=F 앞 · 1991년 앞)은 합성 파일이 없어, 다음 고리와 견주는 검증 ① 이 유일한 검증이다.
    """
    perth_df, aud_usd_df = load_gold_proxy_sources(root / PERTH_MINT_GOLD_DATA_PATH, root / AUD_USD_DATA_PATH)
    futures_df = inputs.prices(GOLD_FUTURES_PATH)
    us_dates = inputs.prices(US_CALENDAR_DATA_PATH)[COL_DATE].tolist()
    gold = build_gold_proxy(perth_df, aud_usd_df, futures_df, us_dates)
    # 합성과 ① 이 같은 사슬을 씀 → ① 이 보수를 뺀 대용이 실물에 얼마나 다가가는지 보임
    gld_proxy = deduct_annual_fee(gold.chain, GLD_EXPENSE_RATIO)
    gld_df = inputs.prices(GLD_ACTUAL_PATH)

    perth_name, fx_name = PERTH_MINT_GOLD_DATA_PATH.name, AUD_USD_DATA_PATH.name
    chain_label = f"{perth_name} · {fx_name} · {GOLD_FUTURES_PATH.name} (연 보수 {GLD_EXPENSE_RATIO:.1%} 뺌)"
    return [
        _ProxyPair("GLD", chain_label, GLD_ACTUAL_PATH.name, gld_proxy, gld_df),
        _ProxyPair("GC=F", f"{perth_name} (달러)", GOLD_FUTURES_PATH.name, gold.perth_usd, futures_df),
        _ProxyPair(
            "Perth 달러", f"{perth_name} (호주달러) × {fx_name}", f"{perth_name} (달러)", gold.aud_in_usd, gold.perth_usd
        ),
    ]


def _proxy_tables(pairs: list[_ProxyPair]) -> tuple[dict[str, PairSummary], pd.DataFrame, pd.DataFrame]:
    """검증 ① — 대상별 비교 요약, 요약 표, 연도별 표 (반올림을 마친 표)."""
    summaries: dict[str, PairSummary] = {}
    summary_rows: list[dict[str, object]] = []
    year_rows: list[dict[str, object]] = []
    for pair in pairs:
        aligned = align_closes(pair.proxy, pair.actual)
        summary = summarize_pair(aligned)
        identity = {DISPLAY_TARGET: pair.name}
        summaries[pair.name] = summary
        summary_rows.append(
            {
                **identity,
                DISPLAY_PROXY_FILE: pair.proxy_label,
                DISPLAY_ACTUAL_FILE: pair.actual_label,
                DISPLAY_PROXY_FIRST_DATE: pair.proxy[COL_DATE].iloc[0],
                **pair_summary_record(summary),
                **unmatched_days_record(count_unmatched_days(pair.proxy, pair.actual)),
            }
        )
        years = summarize_periods(aligned, calendar_year_periods(summary.start, summary.end))
        year_rows.extend({**identity, **record} for record in period_summary_records(years))
    return summaries, round_for_display(pd.DataFrame(summary_rows)), round_for_display(pd.DataFrame(year_rows))


def _assumptions_table(
    runs: list[LeveragedRun],
    ffr_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    proxy_summaries: dict[str, PairSummary],
    inputs: _Inputs,
) -> pd.DataFrame:
    """검증 ④ — 기초마다 대조할 실물이 없는 구간(1배 합성 첫날 ~ 첫 레버리지 상품 첫날 전날)에서 가정만 바꾼 시나리오.

    상품은 합성을 만든 기초로 묶는다. 배당 보정 폭은 ① 에서 지수의 연 수익을 실물 ETF 의 연 수익으로 맞추는 비율이다
    (배당 − ETF 보수).

    Raises:
        ValueError: 대상 표에 기초가 없는 상품이 있거나, 대상 표의 기초를 쓰는 상품이 없을 때 — 빠진 채 만들지 않는다
    """
    target_bases = [underlying_path for underlying_path, _, _ in ASSUMPTION_TARGETS]
    uncovered = [run.name for run in runs if run.underlying_path not in target_bases]
    if uncovered:
        raise ValueError(f"검증 ④ 대상 표(ASSUMPTION_TARGETS)에 기초가 없는 레버리지 상품: {uncovered} — 그 기초를 대상 표에 더하세요")

    results: list[AssumptionResult] = []
    for underlying_path, first_product_path, dividend_target in ASSUMPTION_TARGETS:
        group = [run for run in runs if run.underlying_path == underlying_path]
        if not group:
            raise ValueError(
                f"검증 ④ 대상 표의 기초 {underlying_path} 를 쓰는 레버리지 상품이 없습니다 — " "상품 표(LEVERAGED_SYNTHETIC_TARGETS)의 기초와 맞추세요"
            )
        end = inputs.prices(first_product_path)[COL_DATE].iloc[0] - timedelta(days=1)
        dividend_gap_rate: float | None = None
        if dividend_target is not None:
            summary = proxy_summaries[dividend_target]
            dividend_gap_rate = annual_gap_rate(summary.proxy_cagr, summary.actual_cagr)
            logger.debug(f"{dividend_target} 배당 보정 폭: 연 {dividend_gap_rate * 100:.4f}% (① 지수 연 수익을 실물로 맞추는 비율)")
        results.extend(
            assumption_scenarios(
                group[0].underlying,
                ffr_df,
                expense_df,
                [(run.name, run.leverage) for run in group],
                end=end,
                dividend_gap_rate=dividend_gap_rate,
            )
        )
    adopted = {r.product: r for r in results if r.scenario == SCENARIO_ADOPTED}
    rows = [
        {
            DISPLAY_SCENARIO: r.scenario,
            DISPLAY_PRODUCT: r.product,
            DISPLAY_LEVERAGE: r.leverage,
            DISPLAY_START: r.start,
            DISPLAY_END: r.end,
            DISPLAY_CAGR: r.cagr,
            DISPLAY_MDD: r.mdd,
            DISPLAY_SCENARIO_CAGR_DIFF: r.cagr - adopted[r.product].cagr,
            DISPLAY_SCENARIO_MDD_DIFF: r.mdd - adopted[r.product].mdd,
        }
        for r in results
    ]
    digits = {
        col: ROUND_PERCENT for col in (DISPLAY_CAGR, DISPLAY_MDD, DISPLAY_SCENARIO_CAGR_DIFF, DISPLAY_SCENARIO_MDD_DIFF)
    }
    return pd.DataFrame(rows).round(digits)
