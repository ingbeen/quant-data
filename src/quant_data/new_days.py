"""새로 붙는 날 검사 (판정 규칙 ②) 와 패스 목록

과거 행은 판정 규칙 ①(revision)의 상대 2e-5 가 지키고, 이 모듈은 기존 끝날 뒤에 새로 붙는 날만 본다(결정 Q29).
- 미국: 대상 하루 수익률 − 배율 × 짝 하루 수익률, 기준 배율 × 1%p (결정 Q30)
- 짝이 없는 금 · 장기채: 하루 변동 임시 한도 (결정 Q27)
- 국내: KRX 원본가 ↔ 야후 원본가 완전 일치, KRX 원본가 하루 변화 ↔ KRX 공식 등락률
기준을 넘은 날은 저장을 막지 않고 실패로 모은다 — 갱신이 멈추고, 실제 대폭락 · 대폭등이면 패스 목록에 근거와 함께
적은 뒤 다시 실행한다(결정 Q26). 패스 목록은 사람과 AI 가 적는다.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.constants import COL_CHANGE_RATE, COL_CLOSE, COL_DATE
from quant_data.record_files import parse_iso_date, read_record_rows

PAIR_TOLERANCE_PER_LEVERAGE: Final = 0.01  # 배율 1 당 짝 차이 기준 (0.01 = 1%p)
# 짝이 정해지기 전의 금 · 장기채만 — quant 의 저장 거부 기준을 옮긴 값이고 근거 기록은 없다(결정 Q27)
TEMP_DAILY_MOVE_LIMIT: Final = 0.5  # 비율 (0.5 = 50%)
# KRX 공식 등락률(%)의 표기 자릿수 — Phase 4 착수 전 측정에서 확인해 고친다
OFFICIAL_RATE_DECIMALS: Final = 2
_COMPARE_EPSILON: Final = 1e-9  # 반 단위 경계의 부동소수점 잡음

PASS_LIST_COLUMNS: Final = ("종목", "날짜", "검사", "사유", "근거")


class Check(Enum):
    """새로 붙는 날 검사 — 값은 패스 목록의 「검사」 칸에 적는 이름."""

    PAIR = "짝 차이"
    DAILY_MOVE = "하루 변동"
    KR_TWO_SOURCES = "두 출처 일치"
    KR_OFFICIAL_RATE = "공식 등락률"


@dataclass(frozen=True)
class NewDayFailure:
    ticker: str
    day: date
    check: Check
    detail: str


@dataclass(frozen=True)
class PassEntry:
    """패스 목록 한 줄 — 같은 종목 · 날짜 · 검사의 실패를 놓아준다."""

    ticker: str
    day: date
    check: Check
    reason: str
    evidence: str


def appended_days(existing: pd.DataFrame | None, updated: pd.DataFrame) -> list[date]:
    """기존 끝날 뒤에 새로 붙는 날. 기존 파일이 없으면 빈 목록 — 첫 판의 미국 짝 대조는 걸지 않는다(결정 Q34)."""
    if existing is None:
        return []
    end: date = existing[COL_DATE].iloc[-1]
    return [day for day in updated[COL_DATE] if day > end]


def _closes(prices: pd.DataFrame) -> dict[date, float]:
    return dict(zip(prices[COL_DATE], prices[COL_CLOSE].astype(float), strict=True))


def _previous_day(dates: list[date], day: date, ticker: str) -> date | None:
    """그날 앞 거래일 — 첫 행이면 None.

    Raises:
        ValueError: 그날이 시세에 없을 때 (부르는 쪽이 넘긴 날이 시세 밖)
    """
    if day not in dates:
        raise ValueError(f"{ticker} 시세에 검사할 날 {day} 가 없습니다")
    position = dates.index(day)
    return dates[position - 1] if position > 0 else None


def check_pair(
    target: pd.DataFrame,
    pair: pd.DataFrame,
    *,
    ticker: str,
    pair_name: str,
    leverage: float,
    days: Sequence[date],
) -> list[NewDayFailure]:
    """
    대상 하루 수익률 − 배율 × 짝 하루 수익률이 |배율| × 1%p 를 넘는 날. 짝에 그날 또는 전날이 없으면 견줄 수 없어 실패다.

    Raises:
        ValueError: days 에 대상 시세 밖의 날이 있을 때
    """
    target_closes = _closes(target)
    pair_closes = _closes(pair)
    dates = list(target_closes)
    limit = abs(leverage) * PAIR_TOLERANCE_PER_LEVERAGE
    failures: list[NewDayFailure] = []
    for day in days:
        previous = _previous_day(dates, day, ticker)
        if previous is None:
            continue
        if day not in pair_closes or previous not in pair_closes:
            detail = f"짝 {pair_name} 시세에 {previous} · {day} 중 없는 날이 있어 견줄 수 없음"
            failures.append(NewDayFailure(ticker, day, Check.PAIR, detail))
            continue
        target_return = target_closes[day] / target_closes[previous] - 1
        pair_return = pair_closes[day] / pair_closes[previous] - 1
        difference = target_return - leverage * pair_return
        if abs(difference) > limit:
            detail = (
                f"하루 수익률 {target_return:+.2%} − 배율 {leverage:g} × 짝 {pair_name} {pair_return:+.2%}"
                f" = {difference * 100:+.2f}%p (기준 {limit * 100:.0f}%p)"
            )
            failures.append(NewDayFailure(ticker, day, Check.PAIR, detail))
    return failures


def check_daily_move(target: pd.DataFrame, *, ticker: str, days: Sequence[date], limit: float) -> list[NewDayFailure]:
    """
    하루 변동의 절대값이 limit 이상인 날 (limit 은 비율, 0.5 = 50%).

    Raises:
        ValueError: days 에 시세 밖의 날이 있을 때
    """
    closes = _closes(target)
    dates = list(closes)
    failures: list[NewDayFailure] = []
    for day in days:
        previous = _previous_day(dates, day, ticker)
        if previous is None:
            continue
        move = closes[day] / closes[previous] - 1
        if abs(move) >= limit:
            detail = f"하루 변동 {move:+.2%} (임시 한도 {limit:.0%})"
            failures.append(NewDayFailure(ticker, day, Check.DAILY_MOVE, detail))
    return failures


def check_kr_two_sources(
    krx_raw: pd.DataFrame, yahoo_raw: pd.DataFrame, *, ticker: str, days: Sequence[date]
) -> list[NewDayFailure]:
    """
    KRX 원본가 종가 ↔ 야후 원본가 종가가 원 단위로 다른 날. 야후에 그날이 없거나 가격이 빈 행이면 건너뛴다 —
    그날은 공식 등락률 대조만 한다.

    Raises:
        ValueError: days 에 KRX 시세 밖의 날이 있을 때
    """
    krx_closes = _closes(krx_raw)
    yahoo_closes = _closes(yahoo_raw)
    failures: list[NewDayFailure] = []
    for day in days:
        if day not in krx_closes:
            raise ValueError(f"{ticker} KRX 시세에 검사할 날 {day} 가 없습니다")
        yahoo_close = yahoo_closes.get(day)
        if yahoo_close is None or math.isnan(yahoo_close):
            continue
        krx_won = round(krx_closes[day])
        yahoo_won = round(yahoo_close)
        if krx_won != yahoo_won:
            detail = f"KRX {krx_won:,}원 · 야후 {yahoo_won:,}원"
            failures.append(NewDayFailure(ticker, day, Check.KR_TWO_SOURCES, detail))
    return failures


def check_kr_official_rate(
    krx_raw: pd.DataFrame,
    *,
    ticker: str,
    days: Sequence[date],
    split_ratios: Mapping[date, float],
) -> list[NewDayFailure]:
    """
    KRX 원본가 하루 변화 ↔ KRX 공식 등락률이 표기 자릿수의 반 단위를 넘게 어긋난 날 — 기준가가 전날 종가가 아닌 날
    (분할 · 병합 등 액션)을 찾는다. 국내 분할 기록에 그날 비율(주식 수 배수)이 있으면 전날 종가 ÷ 비율을 기준으로 견준다.

    Raises:
        ValueError: days 에 시세 밖의 날이 있을 때
    """
    closes = _closes(krx_raw)
    rates = dict(zip(krx_raw[COL_DATE], krx_raw[COL_CHANGE_RATE].astype(float), strict=True))
    dates = list(closes)
    half_unit = 0.5 * 10.0**-OFFICIAL_RATE_DECIMALS
    failures: list[NewDayFailure] = []
    for day in days:
        previous = _previous_day(dates, day, ticker)
        if previous is None:
            continue
        ratio = split_ratios.get(day, 1.0)
        change = (closes[day] * ratio / closes[previous] - 1) * 100
        if abs(change - rates[day]) > half_unit + _COMPARE_EPSILON:
            detail = f"원본가 하루 변화 {change:+.4f}% · 공식 등락률 {rates[day]:+.2f}%"
            if ratio != 1.0:
                detail += f" (국내 분할 기록 비율 {ratio:g})"
            failures.append(NewDayFailure(ticker, day, Check.KR_OFFICIAL_RATE, detail))
    return failures


def load_pass_list(path: Path) -> list[PassEntry]:
    """
    패스 목록 파일(한글 머리 · BOM 붙은 CSV)을 읽는다 — 모든 칸이 차 있어야 한다.

    Raises:
        FileNotFoundError: 파일이 없을 때 — 빈 목록으로 넘기면 지워진 파일을 알아채지 못한다
        ValueError: 머리가 다를 때, 날짜가 YYYY-MM-DD 가 아닐 때, 검사 이름이 Check 에 없을 때, 사유 · 근거가 빌 때,
            같은 종목 · 날짜 · 검사가 두 줄일 때
    """
    rows = read_record_rows(path, PASS_LIST_COLUMNS, "패스 목록")
    checks = {check.value: check for check in Check}
    entries: list[PassEntry] = []
    seen: set[tuple[str, date, Check]] = set()
    for line, (ticker, day_text, check_text, reason, evidence) in rows:
        where = f"패스 목록 {path} {line}행"
        day = parse_iso_date(day_text, where)
        check = checks.get(check_text)
        if check is None:
            raise ValueError(f"{where}: 검사 '{check_text}' 는 {list(checks)} 중 하나여야 합니다")
        if not reason:
            raise ValueError(f"{where}: 사유가 비었습니다")
        if not evidence:
            raise ValueError(f"{where}: 근거가 비었습니다 — 그날 짝 지수의 변동 · 함께 넘은 종목처럼 확인한 근거를 적으세요")
        key = (ticker, day, check)
        if key in seen:
            raise ValueError(f"{where}: 같은 종목 · 날짜 · 검사가 두 줄입니다(중복) — {ticker} {day} {check.value}")
        seen.add(key)
        entries.append(PassEntry(ticker, day, check, reason, evidence))
    return entries


def remaining_failures(failures: Sequence[NewDayFailure], entries: Sequence[PassEntry]) -> list[NewDayFailure]:
    """패스 목록이 놓아주지 않은 실패 — 종목 · 날짜 · 검사가 모두 같은 줄만 놓아준다."""
    passed = {(entry.ticker, entry.day, entry.check) for entry in entries}
    return [failure for failure in failures if (failure.ticker, failure.day, failure.check) not in passed]
