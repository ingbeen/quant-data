"""레버리지 합성 검증 ④ — 대조할 실물이 없는 구간에서 가정만 바꾼 판

② 합성 ↔ 실물 추적과 ③ 상장 전 펀드 대조는 상장 뒤 시뮬레이션이 필요해 고정 시점 기록으로 굳혔다(결정 Q32).
정의와 근거는 docs/research/합성_시세_연장.md 5장.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from quant_data.constants import ANNUAL_DAYS, COL_CLOSE, COL_DATE, PRICE_COLUMNS
from quant_data.leveraged.synthetic import build_cost_inputs, month_of, simulate_leveraged

# simulate 가 가산금리 0 을 거부 → 사실상 0 으로 둠
_ZERO_SPREAD: Final = 1e-12

VARIANT_ADOPTED: Final = "채택"
VARIANT_UNCAPPED: Final = "상한 없음"
VARIANT_ZERO_SPREAD: Final = "가산금리 0"
VARIANT_DIVIDEND: Final = "배당 보정"


@dataclass(frozen=True)
class AssumptionResult:
    """가정 판 하나의 Buy & Hold — 구간 첫날 종가에 사서 끝날 종가까지. 연 수익(달력일 기준) · 최악 낙폭은 %."""

    variant: str
    product: str
    leverage: float
    start: date
    end: date
    cagr: float
    mdd: float


def annual_gap_rate(base_cagr: float, target_cagr: float) -> float:
    """
    연 수익 base_cagr 인 시세를 target_cagr 로 맞추려면 해마다 더 붙여야 하는 비율 (연 수익은 %, 반환은 0~1 비율).

    (1 + target) ÷ (1 + base) − 1 이다 — 두 연 수익의 단순 차를 복리로 붙이면 target 을 넘는다.
    """
    return (1.0 + target_cagr / 100.0) / (1.0 + base_cagr / 100.0) - 1.0


def _with_annual_drift(df: pd.DataFrame, annual_rate: float) -> pd.DataFrame:
    """가격 열에 연 annual_rate 를 달력일 비례로 붙인 시세 — 첫날에서 d 일 뒤는 (1 + annual_rate)^(d ÷ ANNUAL_DAYS) 배.

    연 수익을 달력일로 재므로(_cagr) 같은 기준으로 붙여야 연 수익이 정확히 annual_rate 만큼 오른다.
    """
    elapsed_days = np.array([(day - df[COL_DATE].iloc[0]).days for day in df[COL_DATE]], dtype=float)
    factors = (1.0 + annual_rate) ** (elapsed_days / ANNUAL_DAYS)
    result = df.copy()
    result[PRICE_COLUMNS] = result[PRICE_COLUMNS].mul(factors, axis=0)
    return result


def _cagr(closes: pd.Series, start: date, end: date) -> float:
    days = (end - start).days
    return float(((closes.iloc[-1] / closes.iloc[0]) ** (ANNUAL_DAYS / days) - 1.0) * 100.0)


def _mdd(closes: pd.Series) -> float:
    return float((closes / closes.cummax() - 1.0).min() * 100.0)


def assumption_variants(
    underlying_df: pd.DataFrame,
    ffr_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    products: Sequence[tuple[str, float]],
    *,
    end: date,
    dividend_gap_rate: float | None,
) -> list[AssumptionResult]:
    """
    기초 첫날 ~ end 에서 가정만 바꾼 판의 Buy & Hold 를 상품마다 잰다 (검증 ④). 행은 판 순서 · 상품 순서다.

    판: 채택(합성 파일과 같은 비용 입력), 상한 없음, 가산금리 0, 배당 보정(채택 비용에 연 수익을
    dividend_gap_rate 만큼 복리로 높인 기초 — dividend_gap_rate 가 None 이면 이 판은 없다).

    Args:
        underlying_df: 1배 기초 시세 (합성 파일의 기초)
        ffr_df: 월별 금리
        expense_df: 월별 운용비율
        products: (상품 이름, 배율)
        end: 구간 끝날 (그날 포함)
        dividend_gap_rate: 배당 보정 폭 (연 비율, annual_gap_rate — 0.0052 = 연 0.52%).
            None 은 기초가 배당을 담아 보정할 것이 없을 때다

    Raises:
        ValueError: 구간의 날이 2일 미만일 때, build_cost_inputs · simulate 와 같다
    """
    window = underlying_df[underlying_df[COL_DATE] <= end].reset_index(drop=True)
    if len(window) < 2:
        raise ValueError(f"가정 판의 구간에 날이 2일 이상 필요합니다: {len(window)}일 (끝날 {end})")
    start = window[COL_DATE].iloc[0]
    last = window[COL_DATE].iloc[-1]

    first_month = month_of(start)
    adopted = build_cost_inputs(ffr_df, expense_df, first_month)
    variants = [
        (VARIANT_ADOPTED, window, adopted),
        (VARIANT_UNCAPPED, window, build_cost_inputs(ffr_df, expense_df, first_month, spread_cap=None)),
        (VARIANT_ZERO_SPREAD, window, replace(adopted, spread={month: _ZERO_SPREAD for month in adopted.spread})),
    ]
    if dividend_gap_rate is not None:
        variants.append((VARIANT_DIVIDEND, _with_annual_drift(window, dividend_gap_rate), adopted))

    results: list[AssumptionResult] = []
    for variant, underlying, costs in variants:
        for product, leverage in products:
            closes = simulate_leveraged(underlying, leverage, costs)[COL_CLOSE]
            results.append(
                AssumptionResult(
                    variant=variant,
                    product=product,
                    leverage=leverage,
                    start=start,
                    end=last,
                    cagr=_cagr(closes, start, last),
                    mdd=_mdd(closes),
                )
            )
    return results
