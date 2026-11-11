"""국내 수정주가(C-2) — KRX 기준가 사슬과 야후 분배 대조

KRX 는 분배락 · 분할 · 병합이 있는 날 기준가를 전날 종가가 아닌 값으로 두고 공식 등락률을 그 기준가로 낸다(분배금은
ETF 호가 단위 5원으로 맞춘다 — 착수 전 측정 ①). 그래서 하루 수익률 = 종가 ÷ 기준가 − 1 을 이으면 수정주가가 된다(결정 Q14).
기준가가 바뀐 날은 공식 등락률이 원본가 하루 변화와 표기 자릿수의 반 단위 밖인 날이다 — 대비만 어긋난 날(2005년
069500 4일)은 기준가 칸이 틀린 것이라 바뀐 날로 보지 않는다.
기준가가 내려간 날은 같은 날 야후 분배금이 KRX 차이보다 0 ~ 4원 크면 그 금액(정확한 값)을, 아니면 KRX 차이를 쓴다.
야후 기록과 어긋난 날은 값을 바꾸지 않고 판 요약에 적는다(결정 Q28).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

import numpy as np
import pandas as pd

from quant_data.constants import (
    COL_BASE_PRICE,
    COL_CHANGE_RATE,
    COL_CLOSE,
    COL_DATE,
    COL_VALUE,
    PRICE_COLUMNS,
    REQUIRED_COLUMNS,
)

# KRX 공식 등락률(%)의 표기 자릿수 — 착수 전 측정 ① 9종 29,495일 모두 2자리
OFFICIAL_RATE_DECIMALS: Final = 2
_OFFICIAL_RATE_HALF_UNIT: Final = 0.5 * 10.0**-OFFICIAL_RATE_DECIMALS
_COMPARE_EPSILON: Final = 1e-9  # 반 단위 경계의 부동소수점 잡음
# KRX 기준가는 분배금을 ETF 호가 단위로 맞춘다 → 같은 분배면 0 ≤ 야후 금액 − KRX 기준가 차이 < 5원 (측정 ① 69일 중 68일)
YAHOO_AMOUNT_WINDOW_WON: Final = 5


def is_base_changed(previous_close: float, close: float, official_rate: float) -> bool:
    """공식 등락률(%)이 원본가 하루 변화와 표기 자릿수의 반 단위 밖이면 기준가가 전날 종가가 아닌 날이다."""
    change = (close / previous_close - 1) * 100
    return abs(change - official_rate) > _OFFICIAL_RATE_HALF_UNIT + _COMPARE_EPSILON


def official_rate_matches_base(close: float, base: float, official_rate: float) -> bool:
    """기준가로 낸 등락률이 공식 등락률과 표기 자릿수의 반 단위 안인가 — 기준가가 0 이하면 아니다."""
    if not base > 0:
        return False
    return abs((close / base - 1) * 100 - official_rate) <= _OFFICIAL_RATE_HALF_UNIT + _COMPARE_EPSILON


@dataclass(frozen=True)
class KrAdjusted:
    """국내 수정주가 — prices 는 REQUIRED_COLUMNS 표, notes 는 야후 분배 대조의 어긋남(날짜순, 판 요약에 적는다)."""

    prices: pd.DataFrame
    notes: tuple[str, ...]


def build_kr_adjusted(raw: pd.DataFrame, yahoo_dividends: pd.DataFrame) -> KrAdjusted:
    """
    C-2 국내 수정주가 — 기준가가 바뀐 날 그 앞 행 전체에 「기준가 ÷ 전날 종가」를 곱한다. 마지막 날 값은 원본가와 같다.

    Args:
        raw: KRX 원본가 (날짜 오름차순, REQUIRED_COLUMNS + 기준가 · 공식 등락률 — 다른 열은 결과에 남기지 않는다)
        yahoo_dividends: 야후 분배 기록 (Date · Value 원)

    Returns:
        KrAdjusted (원본가 표는 바꾸지 않는다)

    Raises:
        ValueError: 기준가가 바뀐 날의 기준가가 0 이하일 때 (KRX 자료가 깨짐)
    """
    dates: list[date] = list(raw[COL_DATE])
    closes = raw[COL_CLOSE].to_numpy(dtype=float)
    bases = raw[COL_BASE_PRICE].to_numpy(dtype=float)
    rates = raw[COL_CHANGE_RATE].to_numpy(dtype=float)
    dividends: Mapping[date, float] = dict(
        zip(yahoo_dividends[COL_DATE], yahoo_dividends[COL_VALUE].astype(float), strict=True)
    )

    factors = np.ones(len(dates))
    notes: list[tuple[date, str]] = []
    seen_yahoo: set[date] = set()
    for i in range(1, len(dates)):
        day, previous = dates[i], closes[i - 1]
        if not is_base_changed(previous, closes[i], rates[i]):
            continue
        base = bases[i]
        if not base > 0:
            raise ValueError(f"{day} 기준가 {base:,.0f}원이 0 이하입니다 — KRX 원본가의 대비 · 등락률을 확인하세요")
        gap = previous - base
        if gap > 0:
            amount = dividends.get(day)
            if amount is None:
                notes.append((day, f"{day} 기준가 −{gap:,.0f}원 (전날 종가의 {gap / previous:.2%}) — 야후 기록 없음, KRX 를 씀"))
            else:
                seen_yahoo.add(day)
                if 0 <= amount - gap < YAHOO_AMOUNT_WINDOW_WON:
                    base = previous - amount
                else:
                    notes.append((day, f"{day} 금액 다름 — KRX 기준가 차이 {gap:,.0f}원 · 야후 {amount:g}원, KRX 를 씀"))
        else:
            notes.append((day, f"{day} 기준가 상승 +{-gap:,.0f}원 (전날 종가의 {-gap / previous:.2%} — 병합 등)"))
        factors[:i] *= base / previous

    for day, amount in dividends.items():
        if day not in seen_yahoo and dates and dates[0] < day <= dates[-1] and not math.isnan(amount):
            notes.append((day, f"{day} 야후에만 — 분배금 {amount:g}원, KRX 기준가는 바뀌지 않음"))

    adjusted = raw[REQUIRED_COLUMNS].copy()
    adjusted[PRICE_COLUMNS] = raw[PRICE_COLUMNS].astype(float).mul(factors, axis=0)
    return KrAdjusted(adjusted.reset_index(drop=True), tuple(text for _, text in sorted(notes, key=lambda note: note[0])))
