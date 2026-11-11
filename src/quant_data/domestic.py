"""국내 수정주가(C-2) · 국내 분할 기록 · KRX 수정주가 대조

KRX 는 수정주가를 최근 3,000거래일만 준다. 상장일부터의 수정주가는 KRX 원본가에 분배일마다 그 앞 값 전체 ×
(1 − 분배금 ÷ 전 거래일 원본 종가)를 곱해 만든다 — 분배금은 야후 기록이다(결정 Q14). 국내 분할 기록(사람이 운용사
공시를 확인해 적는 파일)의 비율도 같은 방식으로 입히고, 원본가 파일은 KRX 값 그대로 둔다. 야후 첫 분배 기록 앞 구간은
원본가 등락 그대로라 그만큼 덜 좋게 잡힌다.
KRX 수정주가와는 겹치는 날의 하루 수익률로 견주고, 원 단위 반올림만으로 설명되지 않는 날을 어긋난 날로 센다(결정 Q28).
값은 바꾸지 않고 판 요약에 적는다.
"""

import math
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from quant_data.constants import COL_CLOSE, COL_DATE, PRICE_COLUMNS, REQUIRED_COLUMNS
from quant_data.record_files import parse_iso_date, read_record_rows

KR_ACTIONS_COLUMNS: Final = ("종목", "날짜", "비율", "근거")
_WON_HALF_UNIT: Final = 0.5  # KRX 수정주가는 원 단위로 반올림돼 있다
_COMPARE_EPSILON: Final = 1e-12


@dataclass(frozen=True)
class KrAction:
    """국내 분할 기록 한 줄 — ratio 는 주식 수 배수 (액면분할 2:1 = 2, 병합 5:1 = 0.2)."""

    ticker: str
    day: date
    ratio: float
    evidence: str


def load_kr_actions(path: Path) -> list[KrAction]:
    """
    국내 분할 기록 파일(한글 머리 · BOM 붙은 CSV)을 읽는다.

    Raises:
        FileNotFoundError: 파일이 없을 때 — 빈 기록으로 넘기면 지워진 분할 기록이 조용히 빠져 C-2 가 틀린다
        ValueError: 머리가 다를 때, 날짜가 YYYY-MM-DD 가 아닐 때, 비율이 양의 유한한 숫자가 아닐 때, 근거가 빌 때,
            같은 종목 · 날짜가 두 줄일 때
    """
    actions: list[KrAction] = []
    seen: set[tuple[str, date]] = set()
    for line, (ticker, day_text, ratio_text, evidence) in read_record_rows(path, KR_ACTIONS_COLUMNS, "국내 분할 기록"):
        where = f"국내 분할 기록 {path} {line}행"
        day = parse_iso_date(day_text, where)
        try:
            ratio = float(ratio_text)
        except ValueError:
            raise ValueError(f"{where}: 비율 '{ratio_text}' 가 숫자가 아닙니다") from None
        if not (math.isfinite(ratio) and ratio > 0):
            raise ValueError(f"{where}: 비율 {ratio_text} 는 0 보다 큰 주식 수 배수여야 합니다 (액면분할 2:1 = 2, 병합 5:1 = 0.2)")
        if not evidence:
            raise ValueError(f"{where}: 근거가 비었습니다 — 확인한 운용사 공시를 적으세요")
        if (ticker, day) in seen:
            raise ValueError(f"{where}: 같은 종목 · 날짜가 두 줄입니다(중복) — {ticker} {day}")
        seen.add((ticker, day))
        actions.append(KrAction(ticker, day, ratio, evidence))
    return actions


def split_ratios_for(actions: Sequence[KrAction], ticker: str) -> dict[date, float]:
    """한 종목의 국내 분할 기록 — 날짜 → 비율."""
    return {action.day: action.ratio for action in actions if action.ticker == ticker}


def build_kr_adjusted(raw: pd.DataFrame, dividends: pd.Series, split_ratios: Mapping[date, float]) -> pd.DataFrame:
    """
    C-2 국내 수정주가 — 분배일 앞 행 전체에 (1 − 분배금 ÷ 전 거래일 원본 종가), 분할일 앞 행 전체에 1 ÷ 비율을 곱한다.

    거래일이 아닌 날의 기록은 다음 거래일에 건다. 첫 행 날짜 이전 · 마지막 행 뒤의 기록은 바꿀 앞 행이 없거나 구간
    전체의 수준만 바꿔 넣지 않는다 — 마지막 날 값은 원본가와 같다.

    Args:
        raw: KRX 원본가 (날짜 오름차순, REQUIRED_COLUMNS — 다른 열은 결과에 남기지 않는다)
        dividends: 야후 분배 기록 (날짜 → 분배금, 원)
        split_ratios: 국내 분할 기록 (날짜 → 주식 수 배수)

    Returns:
        REQUIRED_COLUMNS 표 (원본가 표는 바꾸지 않는다)

    Raises:
        ValueError: 분배금이 전 거래일 종가 이상일 때, 분할 비율이 0 이하일 때
    """
    dates: list[date] = list(raw[COL_DATE])
    closes = raw[COL_CLOSE].to_numpy(dtype=float)
    factors = np.ones(len(dates))
    for day, amount in zip(list(dividends.index), dividends.to_numpy(dtype=float), strict=True):
        position = bisect_left(dates, day)
        if position == 0 or position == len(dates):
            continue
        factor = 1 - float(amount) / closes[position - 1]
        if not factor > 0:
            raise ValueError(
                f"{day} 분배금 {float(amount):,.0f}원이 전 거래일({dates[position - 1]}) 원본 종가 "
                f"{closes[position - 1]:,.0f}원 이상입니다 — 분배 기록을 확인하세요"
            )
        factors[:position] *= factor
    for day, ratio in split_ratios.items():
        if not ratio > 0:
            raise ValueError(f"{day} 분할 비율 {ratio} 는 0 보다 커야 합니다")
        position = bisect_left(dates, day)
        if position == 0 or position == len(dates):
            continue
        factors[:position] /= ratio

    adjusted = raw[REQUIRED_COLUMNS].copy()
    adjusted[PRICE_COLUMNS] = raw[PRICE_COLUMNS].astype(float).mul(factors, axis=0)
    return adjusted.reset_index(drop=True)


def krx_mismatch_days(built: pd.DataFrame, krx_adjusted: pd.DataFrame) -> list[date]:
    """
    C-2 ↔ KRX 수정주가가 겹치는 날끼리의 하루 수익률이, KRX 값의 원 단위 반올림(±0.5원)만으로 설명되지 않는 날.

    수준이 아니라 하루 수익률로 견준다 — 분배 기록 한 건이 다르면 그날 하루만 어긋난 날이 된다. 퍼센트 기준을 고르지
    않아 가격 수준에 따라 오탐이 갈리지 않는다.
    """
    merged = (
        built[[COL_DATE, COL_CLOSE]]
        .merge(krx_adjusted[[COL_DATE, COL_CLOSE]], on=COL_DATE, suffixes=("_built", "_krx"))
        .sort_values(COL_DATE)
        .reset_index(drop=True)
    )
    built_closes = merged[f"{COL_CLOSE}_built"].to_numpy(dtype=float)
    krx_closes = merged[f"{COL_CLOSE}_krx"].to_numpy(dtype=float)
    mismatches: list[date] = []
    for i in range(1, len(merged)):
        built_return = built_closes[i] / built_closes[i - 1] - 1
        low = (krx_closes[i] - _WON_HALF_UNIT) / (krx_closes[i - 1] + _WON_HALF_UNIT) - 1
        high = (krx_closes[i] + _WON_HALF_UNIT) / (krx_closes[i - 1] - _WON_HALF_UNIT) - 1
        if not (low - _COMPARE_EPSILON <= built_return <= high + _COMPARE_EPSILON):
            mismatches.append(merged[COL_DATE].iloc[i])
    return mismatches
