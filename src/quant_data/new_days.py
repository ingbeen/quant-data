"""신규 일자 검사 (판정 규칙 ②) 와 허용 목록

과거 행은 판정 규칙 ①(revision)의 상대 2e-5 가 지키고, 이 모듈은 기존 끝날 뒤에 신규 일자만 본다(결정 Q29).
- 미국: 대상 하루 수익률 − 배율 × 벤치마크 하루 수익률, 기준 배율 × 1%p (결정 Q30 · Q31 — 금 · 장기채는 같은 자산의 다른 ETF)
- 국내: KRX 원본가 ↔ 야후 원본가 완전 일치, 기준가가 바뀐 날의 「종가 ÷ 기준가 − 1」 ↔ KRX 공식 등락률 (결정 Q14)
- 비트코인: Bitstamp 종가 ↔ Coin Metrics 기준가 차이 5%
기준을 넘은 날은 저장을 막지 않고 실패로 모은다 — 갱신이 멈추고, 실제 대폭락 · 대폭등이면 허용 목록에 근거와 함께
적은 뒤 다시 실행한다(결정 Q26). 허용 목록은 사람과 AI 가 적는다.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.constants import COL_BASE_PRICE, COL_CHANGE_RATE, COL_CLOSE, COL_DATE, COL_VALUE
from quant_data.domestic import is_base_changed, official_rate_matches_base
from quant_data.record_files import parse_iso_date, read_record_rows

TRACKING_TOLERANCE_PER_LEVERAGE: Final = 0.01  # 배율 1 당 추적 차이 기준 (0.01 = 1%p)
# verify-lab 이 교차 확인에 쓰던 목록 경계 그대로 — 새로 고른 숫자가 아니다(사용자 결정 2026-11-11)
COIN_CROSS_CHECK_TOLERANCE: Final = 0.05  # 비율 (0.05 = 5%)

ALLOWLIST_COLUMNS: Final = ("종목", "날짜", "검사", "사유", "근거")


class Check(Enum):
    """신규 일자 검사 — 값은 허용 목록의 「검사」 칸에 적는 이름."""

    TRACKING = "추적 차이"
    KR_CROSS_CHECK = "교차 확인 일치"
    KR_BASE_RATE = "기준가 등락률"
    COIN_CROSS_CHECK = "교차 확인 차이"


@dataclass(frozen=True)
class NewDayFailure:
    ticker: str
    day: date
    check: Check
    detail: str


@dataclass(frozen=True)
class AllowlistEntry:
    """허용 목록 한 줄 — 같은 종목 · 날짜 · 검사의 실패를 놓아준다."""

    ticker: str
    day: date
    check: Check
    reason: str
    evidence: str


def appended_days(existing: pd.DataFrame | None, updated: pd.DataFrame) -> list[date]:
    """기존 끝날 뒤의 신규 일자. 기존 파일이 없으면 빈 목록 — 최초 수집에는 미국 벤치마크 대조를 걸지 않는다(결정 Q34)."""
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


def check_tracking_difference(
    target: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    ticker: str,
    benchmark_name: str,
    leverage: float,
    days: Sequence[date],
) -> list[NewDayFailure]:
    """
    대상 하루 수익률 − 배율 × 벤치마크 하루 수익률이 |배율| × 1%p 를 넘는 날. 벤치마크에 그날 또는 전날이 없으면 견줄 수 없어 실패다.

    Raises:
        ValueError: days 에 대상 시세 밖의 날이 있을 때
    """
    target_closes = _closes(target)
    benchmark_closes = _closes(benchmark)
    dates = list(target_closes)
    limit = abs(leverage) * TRACKING_TOLERANCE_PER_LEVERAGE
    failures: list[NewDayFailure] = []
    for day in days:
        previous = _previous_day(dates, day, ticker)
        if previous is None:
            continue
        if day not in benchmark_closes or previous not in benchmark_closes:
            detail = f"벤치마크 {benchmark_name} 시세에 {previous} · {day} 중 없는 날이 있어 견줄 수 없음"
            failures.append(NewDayFailure(ticker, day, Check.TRACKING, detail))
            continue
        target_return = target_closes[day] / target_closes[previous] - 1
        benchmark_return = benchmark_closes[day] / benchmark_closes[previous] - 1
        difference = target_return - leverage * benchmark_return
        if abs(difference) > limit:
            detail = (
                f"하루 수익률 {target_return:+.2%} − 배율 {leverage:g} × 벤치마크 {benchmark_name} {benchmark_return:+.2%}"
                f" = {difference * 100:+.2f}%p (기준 {limit * 100:.0f}%p)"
            )
            failures.append(NewDayFailure(ticker, day, Check.TRACKING, detail))
    return failures


def check_kr_cross(
    krx_raw: pd.DataFrame, yahoo_raw: pd.DataFrame, *, ticker: str, days: Sequence[date]
) -> list[NewDayFailure]:
    """
    KRX 원본가 종가 ↔ 야후 원본가 종가가 원 단위로 다른 날. 야후에 그날이 없거나 가격이 빈 행이면 건너뛴다 —
    그날은 KRX 자료끼리의 대조(check_kr_base_rate)만 한다.

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
            failures.append(NewDayFailure(ticker, day, Check.KR_CROSS_CHECK, detail))
    return failures


def check_kr_base_rate(krx_raw: pd.DataFrame, *, ticker: str, days: Sequence[date]) -> list[NewDayFailure]:
    """
    기준가가 바뀐 날(공식 등락률이 원본가 하루 변화와 반 단위 밖)에 「종가 ÷ 기준가 − 1」이 공식 등락률과 반 단위 밖이면
    걸린다 — KRX 의 대비 · 등락률이 서로 맞지 않으면 국내 수정주가를 만들 기준가를 믿을 수 없다. 바뀌지 않은 날은 기준가
    칸을 보지 않는다(대비만 어긋난 날).

    Raises:
        ValueError: days 에 시세 밖의 날이 있을 때
    """
    closes = _closes(krx_raw)
    bases = dict(zip(krx_raw[COL_DATE], krx_raw[COL_BASE_PRICE].astype(float), strict=True))
    rates = dict(zip(krx_raw[COL_DATE], krx_raw[COL_CHANGE_RATE].astype(float), strict=True))
    dates = list(closes)
    failures: list[NewDayFailure] = []
    for day in days:
        previous = _previous_day(dates, day, ticker)
        if previous is None or not is_base_changed(closes[previous], closes[day], rates[day]):
            continue
        if not official_rate_matches_base(closes[day], bases[day], rates[day]):
            implied = (closes[day] / bases[day] - 1) * 100 if bases[day] > 0 else math.nan
            detail = (
                f"기준가 {bases[day]:,.0f}원으로 낸 등락률 {implied:+.4f}% · 공식 등락률 {rates[day]:+.2f}% "
                f"(전날 종가 {closes[previous]:,.0f}원 · 종가 {closes[day]:,.0f}원)"
            )
            failures.append(NewDayFailure(ticker, day, Check.KR_BASE_RATE, detail))
    return failures


def check_coin_cross(
    target: pd.DataFrame,
    reference: pd.DataFrame,
    *,
    ticker: str,
    reference_name: str,
    days: Sequence[date],
    tolerance: float = COIN_CROSS_CHECK_TOLERANCE,
) -> list[NewDayFailure]:
    """
    Bitstamp 종가 ÷ Coin Metrics 기준가 − 1 의 절대값이 tolerance(비율)를 넘거나 그날 기준가가 없는 날.

    Raises:
        ValueError: days 에 대상 시세 밖의 날이 있을 때
    """
    closes = _closes(target)
    values = dict(zip(reference[COL_DATE], reference[COL_VALUE].astype(float), strict=True))
    failures: list[NewDayFailure] = []
    for day in days:
        if day not in closes:
            raise ValueError(f"{ticker} 시세에 검사할 날 {day} 가 없습니다")
        value = values.get(day)
        if value is None:
            failures.append(
                NewDayFailure(ticker, day, Check.COIN_CROSS_CHECK, f"{reference_name} 에 {day} 값이 없어 견줄 수 없음")
            )
            continue
        difference = closes[day] / value - 1
        if abs(difference) > tolerance:
            detail = (
                f"종가 {closes[day]:,.2f} · {reference_name} {value:,.2f} — 차이 {difference:+.2%} (기준 {tolerance:.0%})"
            )
            failures.append(NewDayFailure(ticker, day, Check.COIN_CROSS_CHECK, detail))
    return failures


def load_allowlist(path: Path) -> list[AllowlistEntry]:
    """
    허용 목록 파일(한글 헤더 · BOM 붙은 CSV)을 읽는다 — 모든 칸이 차 있어야 한다.

    Raises:
        FileNotFoundError: 파일이 없을 때 — 빈 목록으로 넘기면 지워진 파일을 알아채지 못한다
        ValueError: 헤더가 다를 때, 날짜가 YYYY-MM-DD 가 아닐 때, 검사 이름이 Check 에 없을 때, 사유 · 근거가 빌 때,
            같은 종목 · 날짜 · 검사가 두 줄일 때
    """
    rows = read_record_rows(path, ALLOWLIST_COLUMNS, "허용 목록")
    checks = {check.value: check for check in Check}
    entries: list[AllowlistEntry] = []
    seen: set[tuple[str, date, Check]] = set()
    for line, (ticker, day_text, check_text, reason, evidence) in rows:
        where = f"허용 목록 {path} {line}행"
        day = parse_iso_date(day_text, where)
        check = checks.get(check_text)
        if check is None:
            raise ValueError(f"{where}: 검사 '{check_text}' 는 {list(checks)} 중 하나여야 합니다")
        if not reason:
            raise ValueError(f"{where}: 사유가 비었습니다")
        if not evidence:
            raise ValueError(f"{where}: 근거가 비었습니다 — 그날 벤치마크 지수의 변동 · 함께 넘은 종목처럼 확인한 근거를 적으세요")
        key = (ticker, day, check)
        if key in seen:
            raise ValueError(f"{where}: 같은 종목 · 날짜 · 검사가 두 줄입니다(중복) — {ticker} {day} {check.value}")
        seen.add(key)
        entries.append(AllowlistEntry(ticker, day, check, reason, evidence))
    return entries


def remaining_failures(failures: Sequence[NewDayFailure], entries: Sequence[AllowlistEntry]) -> list[NewDayFailure]:
    """허용 목록이 놓아주지 않은 실패 — 종목 · 날짜 · 검사가 모두 같은 줄만 놓아준다."""
    passed = {(entry.ticker, entry.day, entry.check) for entry in entries}
    return [failure for failure in failures if (failure.ticker, failure.day, failure.check) not in passed]
