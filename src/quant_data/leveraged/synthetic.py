"""레버리지 합성 시세

기초 시세를 배율만큼 굴리고 비용을 뺀 시뮬레이션으로 실물 레버리지 ETF 의 상장 전 구간을 채운다.
시뮬레이션은 상장일(이음매)까지만 돌린다 — 그 뒤는 실물 행이라 시뮬레이션이 합성 값에 들어가지 않고, 상장 뒤 금리 ·
운용비율이 없어도 만들어진다(결정 Q20). 그날까지의 기초만 보는 계산이라 전 기간을 굴린 합성과 값이 같다.
비용 입력(금리 · 운용비율 · 가산금리)은 이 모듈 한 곳에서 만든다 — 합성 파일과 검증 시나리오가 같은 입력을 써야
한쪽만 상한이 빠지는 일이 없다. 파일은 쓰지 않는다 — 쓰기는 update 가 한다(결정 Q17).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.constants import COL_DATE
from quant_data.leveraged.constants import (
    DEFAULT_SOFTPLUS_A,
    DEFAULT_SOFTPLUS_B,
    LEVERAGED_SYNTHETIC_TARGETS,
    SPREAD_CAP,
    SPREAD_CAP_LAST_MONTH,
)
from quant_data.leveraged.monthly_data import build_extended_expense_dict, create_ffr_dict
from quant_data.leveraged.simulation import build_monthly_spread_map, cap_spread_through, simulate
from quant_data.logger import get_logger
from quant_data.synthetic.proxy_series import require_rows_from_seam_equal_actual, splice_proxy

logger = get_logger(__name__)

# 이음매 종가 비율로 다시 맞추므로 결과에 남지 않음
_INITIAL_PRICE: Final = 1.0


@dataclass(frozen=True)
class CostInputs:
    """시뮬레이션 비용 입력 — 월별 {"YYYY-MM": 비율} (simulate 의 ffr_dict · expense_dict · funding_spread)."""

    ffr: dict[str, float]
    expense: dict[str, float]
    spread: dict[str, float]


@dataclass(frozen=True)
class LeveragedRun:
    """상품 하나의 합성 결과 — 그 상품의 기초(상품 표의 경로와 읽은 시세), 이어 붙이기 전 시뮬레이션(기초 첫날 ~ 이음매),
    그 상품의 실물, 저장할 합성 파일과 그 시세."""

    name: str
    leverage: float
    underlying_path: Path
    underlying: pd.DataFrame
    simulated: pd.DataFrame
    actual: pd.DataFrame
    output_path: Path
    synthetic: pd.DataFrame


def month_of(day: date) -> str:
    """날짜의 월 키 (yyyy-mm) — 월별 비용 입력의 키 모양."""
    return f"{day.year:04d}-{day.month:02d}"


def build_cost_inputs(
    ffr_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    first_month: str,
    *,
    spread_cap: float | None = SPREAD_CAP,
) -> CostInputs:
    """
    합성 비용 입력을 만든다.

    가산금리는 softplus 모형 값에 SPREAD_CAP_LAST_MONTH 까지의 달만 spread_cap 상한을 건다(None 이면 상한 없음).
    운용비율은 first_month 부터 파일 첫 달 전까지 상장 전 고정값이다.

    Args:
        ffr_df: 월별 금리 (DATE: str (yyyy-mm), VALUE: float (0~1 비율))
        expense_df: 월별 운용비율 (같은 형식)
        first_month: 시뮬레이션할 기초 시세의 첫 달 (yyyy-mm)
        spread_cap: 가산금리 상한 (비율, 0.016 = 1.6%). None 이면 모형 값 그대로

    Raises:
        ValueError: create_ffr_dict · build_extended_expense_dict · build_monthly_spread_map · cap_spread_through 와 같다
    """
    spread = build_monthly_spread_map(ffr_df, DEFAULT_SOFTPLUS_A, DEFAULT_SOFTPLUS_B)
    if spread_cap is not None:
        spread = cap_spread_through(spread, spread_cap, SPREAD_CAP_LAST_MONTH)
    return CostInputs(
        ffr=create_ffr_dict(ffr_df),
        expense=build_extended_expense_dict(expense_df, first_month),
        spread=spread,
    )


def simulate_leveraged(underlying_df: pd.DataFrame, leverage: float, costs: CostInputs) -> pd.DataFrame:
    """
    기초 시세 전 기간을 배율만큼 굴린 시뮬레이션 (시작 가격 1).

    Raises:
        ValueError: simulate 와 같다 (월별 비용 입력이 기초의 날짜를 덮지 못할 때 포함)
    """
    return simulate(
        underlying_df,
        leverage,
        _INITIAL_PRICE,
        ffr_dict=costs.ffr,
        expense_dict=costs.expense,
        funding_spread=costs.spread,
    )


def build_leveraged_synthetic(simulated_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """
    레버리지 합성 시세 — 이음매(실물 첫 거래일) 앞은 그날 종가 비율로 맞춘 시뮬레이션, 이음매부터는 실물 행 그대로.

    Raises:
        ValueError: splice_proxy 와 같다
        RuntimeError: 이어 붙인 결과의 이음매 뒤 행이 실물과 다를 때 (내부 불변조건 위반 — 저장 전에 멈춘다)
    """
    spliced = splice_proxy(simulated_df, actual_df)
    require_rows_from_seam_equal_actual(spliced, actual_df)
    return spliced


def build_leveraged_synthetics(
    ffr_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    read_prices: Callable[[Path], pd.DataFrame],
    targets: Sequence[tuple[str, Path, Path, float, Path]] = LEVERAGED_SYNTHETIC_TARGETS,
) -> list[LeveragedRun]:
    """
    상품 표의 상품마다 자기 기초 시세를 상장일까지 굴려 그 상품의 합성을 만든다.

    기초 · 실물은 read_prices 로 읽는다 — 저장된 값(가격 6자리)과 같은 표여야 파일만으로 다시 만든 결과와 마지막 자리가
    같다. 같은 기초는 한 번만 읽고, 비용 입력은 그 기초의 첫 달부터 덮는다.

    Args:
        ffr_df: 월별 금리 (build_cost_inputs)
        expense_df: 월별 운용비율 (build_cost_inputs)
        read_prices: 저장소 루트 기준 시세 경로 → 저장된 값과 같은 시세
        targets: (상품 이름, 기초 시세, 실물 시세, 배율, 합성 파일) 의 표

    Returns:
        상품마다 기초 · 시뮬레이션 · 실물 · 합성 (표 순서) — 저장할 합성과 검증 ④ 의 입력

    Raises:
        ValueError: build_cost_inputs · simulate · splice_proxy 와 같다
        RuntimeError: build_leveraged_synthetic 와 같다
    """
    bases: dict[Path, tuple[pd.DataFrame, CostInputs]] = {}
    runs: list[LeveragedRun] = []
    for name, underlying_path, actual_path, leverage, output_path in targets:
        if underlying_path not in bases:
            underlying_df = read_prices(underlying_path)
            costs = build_cost_inputs(ffr_df, expense_df, month_of(underlying_df[COL_DATE].iloc[0]))
            bases[underlying_path] = (underlying_df, costs)
        underlying_df, costs = bases[underlying_path]

        actual_df = read_prices(actual_path)
        listing_day = actual_df[COL_DATE].iloc[0]
        until_listing = underlying_df[underlying_df[COL_DATE] <= listing_day].reset_index(drop=True)
        simulated_df = simulate_leveraged(until_listing, leverage, costs)
        synthetic_df = build_leveraged_synthetic(simulated_df, actual_df)
        logger.debug(
            f"{name}({leverage}배, 기초 {underlying_path.name}): 이음매 {listing_day} 앞 "
            f"{len(synthetic_df) - len(actual_df):,}행을 시뮬레이션으로 채움 → {output_path}"
        )
        runs.append(
            LeveragedRun(
                name=name,
                leverage=leverage,
                underlying_path=underlying_path,
                underlying=underlying_df,
                simulated=simulated_df,
                actual=actual_df,
                output_path=output_path,
                synthetic=synthetic_df,
            )
        )
    return runs
