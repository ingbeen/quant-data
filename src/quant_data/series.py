"""하루 한 값인 계열 — 읽기 · 검사 · 저장 · 덧붙이기 판정

국내 지수 종가 · NAV · Coin Metrics 지표 · 국내 ETF 의 야후 분배 기록이 이 모양(Date · Value)이다. 단위는 계열마다 달라
(원 · 달러 · 배) 저장 자릿수는 갱신 방식 표가 계열마다 정한다. 검사는 중복 날짜 · 결측뿐이다 — 부호 · 변동폭은 보지 않고,
값의 범위는 받는 함수가 계열에 맞게 본다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.logger import get_logger
from quant_data.revision import REVISION_NOISE_TOLERANCE, RevisionKind

logger = get_logger(__name__)

SERIES_COLUMNS: Final = [COL_DATE, COL_VALUE]


def load_series(path: Path) -> pd.DataFrame:
    """
    계열 CSV 를 읽는다 — 날짜를 date 로 파싱해 오름차순으로 두고, 검사(validate_series)에 걸리면 멈춘다. 행이 없어도 된다.

    Raises:
        FileNotFoundError: 파일이 없을 때 — 빈 계열로 넘기면 지워진 파일을 알아채지 못한다
        ValueError: 열이 Date · Value 가 아닐 때, validate_series 와 같은 경우
    """
    if not path.exists():
        raise FileNotFoundError(f"계열 파일을 찾을 수 없습니다: {path}")
    df = pd.read_csv(path)
    if list(df.columns) != SERIES_COLUMNS:
        raise ValueError(f"계열 파일의 열이 {SERIES_COLUMNS} 가 아닙니다: {list(df.columns)} ({path})")
    df[COL_DATE] = pd.to_datetime(df[COL_DATE]).dt.date
    df[COL_VALUE] = df[COL_VALUE].astype(float)
    df = df.sort_values(COL_DATE).reset_index(drop=True)
    validate_series(df)
    return df


def validate_series(df: pd.DataFrame) -> None:
    """
    계열에 중복 날짜나 결측 값이 있으면 ValueError — 지우거나 메우지 않는다.

    Raises:
        ValueError: 중복 날짜 · 결측 값 (날짜 포함)
    """
    duplicated = df.loc[df.duplicated(subset=[COL_DATE]), COL_DATE].unique().tolist()
    if duplicated:
        raise ValueError(f"중복 날짜 발견 - {len(duplicated)}개, 날짜: {duplicated[:5]}")
    missing = df.loc[df[COL_VALUE].isna(), COL_DATE].tolist()
    if missing:
        raise ValueError(f"결측치 발견 - {len(missing)}개, 날짜: {missing[:5]}")


def save_series(df: pd.DataFrame, path: Path, *, decimals: int) -> None:
    """
    계열을 자릿수 반올림 → 검사 → 저장 순서로 저장한다. 검사에 걸리면 파일을 쓰지 않는다.

    Raises:
        ValueError: validate_series 와 같은 경우
    """
    rounded = df[SERIES_COLUMNS].copy()
    rounded[COL_VALUE] = rounded[COL_VALUE].astype(float).round(decimals)
    validate_series(rounded)
    path.parent.mkdir(parents=True, exist_ok=True)
    rounded.to_csv(path, index=False)
    logger.debug(f"저장: {path} ({len(rounded):,}행)")


@dataclass(frozen=True)
class SeriesRevision:
    """덧붙이기 판정 — values 는 이 판정대로 저장할 표(비정상이면 사람이 --accept 했을 때 저장할 응답)."""

    kind: RevisionKind
    values: pd.DataFrame
    issues: tuple[str, ...]


def judge_series_append(existing: pd.DataFrame | None, response: pd.DataFrame, *, decimals: int) -> SeriesRevision:
    """
    다시 받은 계열을 기존 파일과 견준다 — 지난 날 값이 시세와 같은 흔들림(상대 2e-5 + 저장 자릿수의 반 단위) 안이고
    지난 날이 모두 있으면 기존 행 그대로에 기존 끝날 뒤의 새 날만 붙이고(NOISE), 아니면 비정상이다. 기존 파일이 없으면
    응답 그대로(NEW).

    Raises:
        ValueError: 응답에 중복 날짜 · 결측 값이 있을 때 (validate_series)
    """
    response = response[SERIES_COLUMNS].reset_index(drop=True)
    validate_series(response)
    if existing is None:
        return SeriesRevision(RevisionKind.NEW, response, ())

    stored = dict(zip(existing[COL_DATE], existing[COL_VALUE].astype(float), strict=True))
    received = dict(zip(response[COL_DATE], response[COL_VALUE].astype(float), strict=True))
    last_day = max(stored) if stored else None
    half_unit = 0.5 * 10.0**-decimals

    issues: list[str] = []
    missing = sorted(set(stored) - set(received))
    if missing:
        issues.append(f"기존 날 {len(missing)}개가 응답에 없음 — {_span(missing)}")
    changed = sorted(
        day
        for day in set(stored) & set(received)
        if abs(received[day] - stored[day]) > REVISION_NOISE_TOLERANCE * abs(stored[day]) + half_unit
    )
    if changed:
        shown = " · ".join(f"{day} {stored[day]:g} → {received[day]:g}" for day in changed[:5])
        issues.append(f"기존 날 {len(changed)}개의 값이 바뀜 — {shown}")
    inside = sorted(day for day in set(received) - set(stored) if last_day is not None and day < last_day)
    if inside:
        issues.append(f"기존 끝날({last_day}) 앞에 새 날 {len(inside)}개가 생김 — {_span(inside)}")
    if issues:
        return SeriesRevision(RevisionKind.ABNORMAL, response, tuple(issues))

    new_rows = response if last_day is None else response[response[COL_DATE] > last_day]
    kept = pd.concat([existing[SERIES_COLUMNS], new_rows], ignore_index=True)
    return SeriesRevision(RevisionKind.NOISE, kept, ())


def _span(days: Sequence[date]) -> str:
    return str(days[0]) if len(days) == 1 else f"{days[0]} ~ {days[-1]}"
