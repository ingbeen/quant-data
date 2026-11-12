"""다시 받은 시세 ↔ 기존 시세 파일 판정 (판정 규칙 ①)

야후는 수정 종가를 요청마다 미세하게 다르게 주고, 배당 기록을 늦게 넣거나 넣었다가 빼기도 한다.
다시 받은 응답을 기존 파일과 견줘 셋으로 가른다 — 노이즈뿐(기존 행 그대로 + 새 날짜 행), 배당 반영(응답의
배당 기록과 맞는 변화 — 응답으로 덮어씀), 그 밖(비정상 — --exclude · --accept 는 사람이 정한다). 분할은 기록과 맞아도
비정상이다 — 사람이 운용사 공시와 날짜 · 비율을 맞춰 본 뒤 받아들인다(결정 Q23). 기준값의 근거는
docs/research/시세_받기_판정.md 결정 14.
"""

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from quant_data.constants import COL_CLOSE, COL_DATE, PRICE_COLUMNS, REQUIRED_COLUMNS

# 허용 오차(상대) — 관측 노이즈 최대 4.9e-6 의 4배, 가장 작은 배당(배당 ÷ 전날 종가) 5.9e-5 의 1/3 (2026-11-07)
# 기록과 맞출 때도 같은 상한으로 비율을 견줌 — 야후 배당 1,438건의 (1 + 계단) ÷ 기록 비율이 최대 2.1e-6 안
REVISION_NOISE_TOLERANCE: Final = 2e-5
MAX_ISSUE_LINES: Final = 5
RECENT_DIVIDEND_COUNT: Final = 3
_DATE_ISSUE_WEIGHT: Final = float("inf")  # 날짜 변화는 가격 변화보다 앞에 낸다


class RevisionKind(Enum):
    NEW = "새 파일"
    NOISE = "노이즈뿐"
    DIVIDEND_ADJUSTED = "배당 반영"
    ABNORMAL = "비정상"


@dataclass(frozen=True)
class PriceEvents:
    """응답의 배당 · 분할 기록과 원본 종가 — 기준일로 잘라내기 전 전체 응답(수정 비율이 잘라낸 날의 배당까지 반영한다).

    dividends · splits 는 날짜(date) → 금액 · 배수(값이 있는 날만), raw_close 는 날짜 오름차순의 원본 종가다.
    """

    dividends: pd.Series
    splits: pd.Series
    raw_close: pd.Series


@dataclass(frozen=True)
class PriceRevision:
    """판정 결과. prices 는 이 판정대로 저장할 표 — 비정상이면 사람이 --accept 했을 때 저장할 응답이다."""

    kind: RevisionKind
    prices: pd.DataFrame
    issues: tuple[str, ...]  # 비정상 진단 줄 — 큰 것부터
    applied: tuple[str, ...]  # 기록과 맞은 배당
    split_changes: tuple[tuple[date, float], ...]  # 기록과 맞은 분할 (날짜, 배수) — 진단 출력의 공시 대조 안내
    existing_end: date | None
    existing_rows: int
    response_end: date
    response_rows: int
    recent_dividends: tuple[tuple[date, float], ...]


@dataclass(frozen=True)
class _Issue:
    weight: float  # 줄 순서 — 변화의 크기
    text: str


@dataclass(frozen=True)
class _Event:
    day: date
    factor: float  # 그날 앞 가격에 곱해지는 조정 비율
    description: str
    split_ratio: float | None  # 분할 기록이면 배수


@dataclass(frozen=True)
class _RowRecords:
    """겹친 날짜 한 행에 걸리는 기록들 — 그 행과 앞 행 사이."""

    factor: float
    description: str
    splits: tuple[tuple[date, float], ...]


def judge_revision(
    existing: pd.DataFrame | None,
    response: pd.DataFrame,
    events: PriceEvents,
    *,
    price_decimals: int,
    explain_dividends: bool,
) -> PriceRevision:
    """
    다시 받은 응답을 기존 시세와 견줘 가른다.

    Args:
        existing: 기존 파일 (load_prices 모양 — 날짜 오름차순, 가격은 price_decimals 자리). 없으면 None
        response: 받은 시세 (REQUIRED_COLUMNS, 날짜 오름차순, 기준일까지)
        events: 같은 응답의 배당 · 분할 기록과 원본 종가
        price_decimals: 기존 파일 가격의 자릿수 — 반올림 오차는 변화로 보지 않는다
        explain_dividends: 배당 기록으로 변화를 설명하는가 — 수정주가는 True, 원본가는 False(야후 원본가는 분할만
            과거에 반영된다)

    Returns:
        PriceRevision

    Raises:
        ValueError: 응답이나 기존 파일이 비었을 때
    """
    if response.empty:
        raise ValueError("받은 시세가 비어 있습니다 — 판정할 수 없습니다")
    if existing is not None and existing.empty:
        raise ValueError("기존 시세 파일에 행이 없습니다 — git 이력에서 그 파일을 되살리세요")
    response = response.reset_index(drop=True)
    recent = _recent_dividends(events.dividends)
    response_end: date = response[COL_DATE].iloc[-1]

    if existing is None:
        return PriceRevision(
            kind=RevisionKind.NEW,
            prices=response,
            issues=(),
            applied=(),
            split_changes=(),
            existing_end=None,
            existing_rows=0,
            response_end=response_end,
            response_rows=len(response),
            recent_dividends=recent,
        )

    existing = existing.reset_index(drop=True)
    existing_end: date = existing[COL_DATE].iloc[-1]
    known = response[response[COL_DATE] <= existing_end]
    new_rows = response[response[COL_DATE] > existing_end]

    issues = _date_issues(existing[COL_DATE], known[COL_DATE])
    pair = existing[[COL_DATE, *PRICE_COLUMNS]].merge(
        known[[COL_DATE, *PRICE_COLUMNS]], on=COL_DATE, suffixes=("_e", "_r")
    )
    stored = pair[[f"{col}_e" for col in PRICE_COLUMNS]].to_numpy(dtype=float)
    received = pair[[f"{col}_r" for col in PRICE_COLUMNS]].to_numpy(dtype=float)
    half_unit = 0.5 * 10.0**-price_decimals

    def revision(
        kind: RevisionKind,
        prices: pd.DataFrame,
        found: list[_Issue],
        applied: list[str],
        split_changes: list[tuple[date, float]],
    ) -> PriceRevision:
        ordered = sorted(found, key=lambda issue: -issue.weight)
        return PriceRevision(
            kind=kind,
            prices=prices,
            issues=tuple(issue.text for issue in ordered),
            applied=tuple(applied),
            split_changes=tuple(split_changes),
            existing_end=existing_end,
            existing_rows=len(existing),
            response_end=response_end,
            response_rows=len(response),
            recent_dividends=recent,
        )

    if not issues and _within_noise(stored, received, half_unit):
        kept = pd.concat([existing[REQUIRED_COLUMNS], new_rows[REQUIRED_COLUMNS]], ignore_index=True)
        return revision(RevisionKind.NOISE, kept, [], [], [])

    dates = list(pair[COL_DATE])
    found = _price_findings(dates, stored, received, events, half_unit, explain_dividends)
    issues += found.issues
    # 허용 오차는 넘었는데 맞춘 기록도 잡힌 원인도 없음 → 설명되지 않은 변화라 덮어쓰지 않음
    if not issues and not found.applied:
        issues.append(_unrecorded_small_change(dates, stored, received, half_unit))
    kind = RevisionKind.ABNORMAL if issues else RevisionKind.DIVIDEND_ADJUSTED
    return revision(kind, response, issues, list(found.applied), list(found.split_changes))


@dataclass(frozen=True)
class _Findings:
    """기록과 맞춘 결과 — 비정상 원인, 기록과 맞은 배당, 기록과 맞은 분할."""

    issues: tuple[_Issue, ...]
    applied: tuple[str, ...]
    split_changes: tuple[tuple[date, float], ...]


class _Records:
    """응답의 배당 · 분할 기록을 조정 비율로 — 원본가 판정이면 배당은 넣지 않는다."""

    def __init__(self, events: PriceEvents, explain_dividends: bool) -> None:
        self._events = events
        self._raw_dates: list[date] = list(events.raw_close.index)
        self._raw_values = events.raw_close.to_numpy(dtype=float)
        self._explain_dividends = explain_dividends

    def between(self, *, after: date, until: date | None = None) -> list[_Event]:
        """after < 날짜 ≤ until 인 기록 (날짜순). 배당의 조정 비율은 1 − 배당 ÷ 전날 원본 종가, 분할은 1 ÷ 배수."""

        def in_range(day: date) -> bool:
            return day > after and (until is None or day <= until)

        found: list[_Event] = []
        if self._explain_dividends:
            dividend_days: list[date] = list(self._events.dividends.index)
            for day, amount in zip(dividend_days, self._events.dividends.to_numpy(dtype=float), strict=True):
                if not in_range(day):
                    continue
                previous = self.previous_close(day)
                # 응답 첫날의 배당은 앞 행이 없어 어느 가격도 바꾸지 않음
                if previous is not None:
                    factor = 1 - float(amount) / previous if previous > 0 else math.nan
                    found.append(_Event(day, factor, f"{day} 배당 ${float(amount):.3f}", None))
        split_days: list[date] = list(self._events.splits.index)
        for day, ratio in zip(split_days, self._events.splits.to_numpy(dtype=float), strict=True):
            if in_range(day):
                factor = 1 / float(ratio) if ratio > 0 else math.nan
                found.append(_Event(day, factor, f"{day} 분할 {float(ratio):g}배", float(ratio)))
        return sorted(found, key=lambda event: event.day)

    def previous_close(self, day: date) -> float | None:
        position = bisect_left(self._raw_dates, day)
        return float(self._raw_values[position - 1]) if position > 0 else None

    def unrecorded_cause(self, step: float, day: date) -> str:
        # 관측은 두 파일의 상대 크기뿐 — 어느 쪽에 조정이 있는지 · 원인이 배당인지는 모름 → 추정으로만 적음
        if step <= 0:
            return "그날 앞에서 응답 가격이 기존보다 낮음 · 응답에 그날 배당 · 분할 기록 없음"
        # 기록이 빠진 배당은 그날 앞 가격을 1 ÷ (1 − 배당 ÷ 전날 종가) 배로 올림 → 배당 = 전날 종가 × s ÷ (1 + s)
        previous = self.previous_close(day)
        amount = f"약 ${previous * step / (1 + step):.3f}" if previous is not None else "(전날 종가 없음)"
        return f"그날 앞에서 기존 가격이 응답보다 낮음(빠진 배당이라면 {amount}) · 응답에 그날 배당 · 분할 기록 없음"


def _within_noise(stored: np.ndarray, received: np.ndarray, half_unit: float) -> bool:
    # 기존 값은 반올림돼 저장돼 참값과 반 단위까지 다름 → 상한에 반 단위를 더함
    return bool(np.all(np.abs(received - stored) <= REVISION_NOISE_TOLERANCE * np.abs(stored) + half_unit))


def _date_issues(existing_dates: pd.Series, known_dates: pd.Series) -> list[_Issue]:
    stored = set(existing_dates)
    received = set(known_dates)
    first: date = existing_dates.iloc[0]
    missing = sorted(stored - received)
    added = sorted(received - stored)
    before = [day for day in added if day < first]
    inside = [day for day in added if day > first]
    issues: list[_Issue] = []
    if missing:
        issues.append(_Issue(_DATE_ISSUE_WEIGHT, f"기존 날짜 {len(missing):,}개가 응답에 없음 — {_span(missing)}"))
    if inside:
        issues.append(_Issue(_DATE_ISSUE_WEIGHT, f"기존 기간 안에 새 날짜 {len(inside):,}개 — {_span(inside)}"))
    if before:
        issues.append(_Issue(_DATE_ISSUE_WEIGHT, f"기존 첫날({first}) 앞에 날짜 {len(before):,}개가 생김 — {_span(before)}"))
    return issues


def _span(days: Sequence[date]) -> str:
    return str(days[0]) if len(days) == 1 else f"{days[0]} ~ {days[-1]}"


def _row_span(dates: list[date], rows: np.ndarray) -> str:
    return _span([dates[rows[0]], dates[rows[-1]]]) if rows.size > 1 else str(dates[rows[0]])


def _split_text(splits: Sequence[tuple[date, float]]) -> str:
    """진단 줄의 분할 문구 — 사람이 운용사 공시와 맞춰 볼 날짜 · 배수."""
    return " · ".join(f"분할로 보이는 변화: {day} · {ratio:g}배 (야후 기록)" for day, ratio in splits)


def _unrecorded_small_change(dates: list[date], stored: np.ndarray, received: np.ndarray, half_unit: float) -> _Issue:
    beyond = np.abs(received - stored) > REVISION_NOISE_TOLERANCE * np.abs(stored) + half_unit
    rows = np.flatnonzero(beyond.any(axis=1))
    if rows.size == 0:
        raise RuntimeError("내부 불변조건 위반: 허용 오차를 넘은 값이 없는데 노이즈 판정을 지나왔습니다")
    deviation = received / stored - 1
    worst = float(deviation.flat[np.argmax(np.where(beyond, np.abs(deviation), 0.0))])
    return _Issue(
        abs(worst),
        f"기록 없는 작은 변화 — {rows.size:,}행이 허용 오차를 넘음, 가장 큰 차 {worst:+.4%} ({_row_span(dates, rows)})",
    )


def _price_findings(
    dates: list[date],
    stored: np.ndarray,
    received: np.ndarray,
    events: PriceEvents,
    half_unit: float,
    explain_dividends: bool,
) -> _Findings:
    """겹친 날짜의 가격 변화를 기록과 맞춘다."""
    if not dates:
        return _Findings((), (), ())
    ratio = received / stored
    floor = half_unit / stored  # 기존 값 반올림 오차의 상대 크기
    close = PRICE_COLUMNS.index(COL_CLOSE)
    records = _Records(events, explain_dividends)

    issues: list[_Issue] = []
    column_issue = _column_mismatch_issue(dates, ratio, floor, close)
    if column_issue is not None:
        issues.append(column_issue)

    close_ratio = ratio[:, close]
    close_floor = floor[:, close]
    steps, matched_rows = _step_findings(dates, close_ratio, close_floor, records)
    tail = _tail_findings(dates, close_ratio[-1], close_floor[-1], records)
    issues += [*steps.issues, *tail.issues]

    if not issues:
        drift_issue = _drift_issue(dates, close_ratio, close_floor, matched_rows)
        if drift_issue is not None:
            issues.append(drift_issue)
    return _Findings(tuple(issues), steps.applied + tail.applied, steps.split_changes + tail.split_changes)


def _column_mismatch_issue(dates: list[date], ratio: np.ndarray, floor: np.ndarray, close: int) -> _Issue | None:
    # 조정은 한 행의 네 가격에 같은 비율로 걸림 → 비율이 열마다 다르면 봉 자체가 바뀐 것
    others = [i for i in range(len(PRICE_COLUMNS)) if i != close]
    deviation = ratio[:, others] / ratio[:, [close]] - 1
    allowed = REVISION_NOISE_TOLERANCE + floor[:, others] + floor[:, [close]]
    bad = np.abs(deviation) > allowed
    rows = np.flatnonzero(bad.any(axis=1))
    if rows.size == 0:
        return None
    worst = float(deviation.flat[np.argmax(np.abs(np.where(bad, deviation, 0.0)))])
    return _Issue(
        abs(worst),
        f"{rows.size:,}행에서 시가 · 고가 · 저가가 종가와 다르게 바뀜 — 가장 큰 차 {worst:+.3%} ({_row_span(dates, rows)})",
    )


def _step_findings(
    dates: list[date], close_ratio: np.ndarray, close_floor: np.ndarray, records: _Records
) -> tuple[_Findings, set[int]]:
    """이웃한 두 날 사이 종가 비율의 계단을 그 사이 기록과 맞춘다 — (결과, 기록과 맞은 행)."""
    steps = close_ratio[:-1] / close_ratio[1:] - 1  # steps[k]: dates[k] 와 dates[k + 1] 사이
    allowed = REVISION_NOISE_TOLERANCE + close_floor[:-1] + close_floor[1:]
    by_row = _records_by_row(dates, records.between(after=dates[0], until=dates[-1]))

    issues: list[_Issue] = []
    applied: list[str] = []
    split_changes: list[tuple[date, float]] = []
    matched_rows: set[int] = set()
    for k in np.flatnonzero(np.abs(steps) > allowed):
        row = int(k) + 1
        step = float(steps[k])
        day = dates[row]
        prefix = f"{day} 이전 {row:,}행 {step:+.3%}"
        record = by_row.get(row)
        if record is None:
            issues.append(_Issue(abs(step), f"{prefix} — {records.unrecorded_cause(step, day)}"))
        elif not _usable(record.factor):
            issues.append(_Issue(abs(step), f"{prefix} — 조정 비율을 셀 수 없는 기록 (응답 기록: {record.description})"))
        # 크기에 비례한 허용은 분할(1 ÷ 배수) 같은 큰 기록에 다른 변화를 함께 묻힘 → 비율로 견줌
        elif abs((1 + step) / record.factor - 1) > float(allowed[k]):
            issues.append(_Issue(abs(step), f"{prefix} — 기록대로면 {record.factor - 1:+.3%} (응답 기록: {record.description})"))
        elif record.splits:
            # 분할은 기록과 맞아도 사람이 공시와 맞춰 본 뒤 받아들임 (결정 Q23)
            matched_rows.add(row)
            issues.append(_Issue(abs(step), f"{prefix} — {_split_text(record.splits)}"))
            split_changes.extend(record.splits)
        else:
            matched_rows.add(row)
            applied.append(f"{record.description} — {day} 이전 {row:,}행 {step:+.3%}")
    return _Findings(tuple(issues), tuple(applied), tuple(split_changes)), matched_rows


def _tail_findings(dates: list[date], tail_ratio: float, tail_floor: float, records: _Records) -> _Findings:
    """기존 끝날의 종가 비율을 그 뒤 기록과 맞춘다."""
    last = dates[-1]
    later = records.between(after=last)
    allowed = REVISION_NOISE_TOLERANCE + float(tail_floor)
    change = float(tail_ratio) - 1
    # 앞쪽 몇 건은 기존 파일이 잘라낸 날의 배당으로 이미 반영했을 수 있음 → 앞에서부터 빼 보며 맞춤
    for skipped in range(len(later) + 1):
        rest = later[skipped:]
        expected = float(np.prod([event.factor for event in rest])) if rest else 1.0
        if not (_usable(expected) and abs(tail_ratio / expected - 1) <= allowed):
            continue
        applied = tuple(f"{event.description} — 기존 끝날 {last} 뒤" for event in rest if event.split_ratio is None)
        splits = tuple((event.day, event.split_ratio) for event in rest if event.split_ratio is not None)
        if not splits:
            return _Findings((), applied, ())
        # 분할은 기록과 맞아도 사람이 공시와 맞춰 본 뒤 받아들임 (결정 Q23)
        text = f"기존 끝날 {last} 까지 {len(dates):,}행 {change:+.3%} — {_split_text(splits)}"
        return _Findings((_Issue(abs(change), text),), applied, splits)
    later_text = " · ".join(event.description for event in later) if later else "없음"
    text = f"기존 끝날 {last} 까지 {len(dates):,}행 {change:+.3%} — 기존 끝날 뒤 응답 기록 {later_text}"
    return _Findings((_Issue(abs(change), text),), (), ())


def _drift_issue(
    dates: list[date], close_ratio: np.ndarray, close_floor: np.ndarray, matched_rows: set[int]
) -> _Issue | None:
    # 기록과 맞은 계단만으로 끝날부터 비율을 다시 쌓음 → 실제 비율과 다르면 상한 아래 계단이 쌓인 것
    rebuilt = np.empty_like(close_ratio)
    rebuilt[-1] = close_ratio[-1]
    for row in range(len(close_ratio) - 1, 0, -1):
        step = close_ratio[row - 1] / close_ratio[row] if row in matched_rows else 1.0
        rebuilt[row - 1] = rebuilt[row] * step
    deviation = close_ratio / rebuilt - 1
    allowed = REVISION_NOISE_TOLERANCE + close_floor + close_floor[-1]
    bad = np.flatnonzero(np.abs(deviation) > allowed)
    if bad.size == 0:
        return None
    worst = int(bad[np.argmax(np.abs(deviation[bad]))])
    return _Issue(
        abs(float(deviation[worst])),
        f"작은 변화가 쌓임 — {_row_span(dates, bad)} 에서 최대 {float(deviation[worst]):+.3%}",
    )


def _usable(factor: float) -> bool:
    # 배당 ≥ 전날 종가 · 분할 배수 0 또는 무한(야후 분모 0)이면 0 · 무한 · nan → 어떤 계단도 설명하지 못함
    return math.isfinite(factor) and factor > 0


def _records_by_row(dates: list[date], events: list[_Event]) -> dict[int, _RowRecords]:
    """겹친 날짜의 행마다 그 행과 앞 행 사이 기록들의 조정 비율 곱 · 설명 · 분할."""
    by_row: dict[int, tuple[float, list[str], list[tuple[date, float]]]] = {}
    for event in events:
        row = bisect_left(dates, event.day)  # 기록 날짜 이후의 첫 행 — 휴장일 기록도 다음 거래일에 걸린다
        factor, descriptions, splits = by_row.get(row, (1.0, [], []))
        if event.split_ratio is not None:
            splits = [*splits, (event.day, event.split_ratio)]
        by_row[row] = (factor * event.factor, [*descriptions, event.description], splits)
    return {
        row: _RowRecords(factor, " · ".join(descriptions), tuple(splits))
        for row, (factor, descriptions, splits) in by_row.items()
    }


def _recent_dividends(dividends: pd.Series) -> tuple[tuple[date, float], ...]:
    latest = dividends.sort_index().iloc[-RECENT_DIVIDEND_COUNT:]
    days: list[date] = list(latest.index)
    return tuple((day, float(amount)) for day, amount in zip(days, latest.to_numpy(dtype=float), strict=True))


def format_abnormal_block(
    entries: Sequence[tuple[str, Path, PriceRevision]],
    *,
    run_at: datetime,
    cutoff_date: date,
    yfinance_version: str,
) -> str:
    """
    비정상 종목의 진단 출력 — 사용자가 그대로 AI 에 붙여 판단을 받는다. --exclude · --accept 는 사람이 정한다.

    Args:
        entries: (자료 이름, 파일 경로, 비정상 판정)
        run_at: 실행 시각 (시간대 포함)
        cutoff_date: 받을 마지막 날
        yfinance_version: 받은 yfinance 버전
    """
    lines = [
        "[갱신 비정상 판정 — 이 블록을 그대로 AI 에 붙여 판단을 받으세요]",
        f"실행 {run_at:%Y-%m-%d %H:%M} {run_at.tzname()} · 기준일 {cutoff_date} · yfinance {yfinance_version}",
        "판단 요청: 아래 변화가 야후 쪽 오류인지 실제 정정인지, 이번 응답으로 덮어써도 되는지",
    ]
    for name, path, revision in entries:
        lines.append("")
        lines.append(
            f"{name} — {path} (기존 ~ {revision.existing_end} {revision.existing_rows:,}행 · "
            f"응답 ~ {revision.response_end} {revision.response_rows:,}행)"
        )
        lines += [f"  - {issue}" for issue in revision.issues[:MAX_ISSUE_LINES]]
        if len(revision.issues) > MAX_ISSUE_LINES:
            lines.append(f"  - 외 {len(revision.issues) - MAX_ISSUE_LINES:,}건")
        if revision.recent_dividends:
            recent = " · ".join(f"{day} ${amount:.3f}" for day, amount in revision.recent_dividends)
            lines.append(f"  - 응답의 최근 배당: {recent}")
        else:
            lines.append("  - 응답에 배당 기록 없음")
        lines.append(f"  --accept {name} = 응답으로 덮어씀(위 변화가 저장됨) · --exclude {name} = 기존 파일 그대로(새 날짜도 붙지 않음)")
        if revision.split_changes:
            splits = ", ".join(f"{day} · {ratio:g}배" for day, ratio in revision.split_changes)
            lines.append(
                f"  분할로 보이는 변화({splits})는 운용사 공시와 날짜 · 비율을 맞춰 본 뒤 --accept 하세요" " — --exclude 하면 다음 갱신에서도 다시 멈춥니다"
            )
    return "\n".join(lines)
