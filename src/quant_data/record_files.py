"""사람 · AI 가 쓰는 기록 파일(허용 목록)의 공통 읽기 — 한글 헤더 · BOM 붙은 CSV."""

import csv
import re
from datetime import date
from pathlib import Path
from typing import Final

_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


def read_record_rows(path: Path, columns: tuple[str, ...], name: str) -> list[tuple[int, tuple[str, ...]]]:
    """
    기록 파일을 (줄 번호, 앞뒤 공백을 지운 칸) 으로 읽는다. 빈 줄은 건너뛴다.

    Raises:
        FileNotFoundError: 파일이 없을 때 — 빈 기록으로 넘기면 지워진 파일을 알아채지 못한다
        ValueError: 헤더가 columns 가 아닐 때, 칸 수가 다른 줄이 있을 때
    """
    if not path.exists():
        raise FileNotFoundError(f"{name} 파일이 없습니다: {path} — 헤더({','.join(columns)})만 있는 파일이라도 두어야 합니다")
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = list(csv.reader(file))
    if not reader or tuple(cell.strip() for cell in reader[0]) != columns:
        found = reader[0] if reader else []
        raise ValueError(f"{name} {path} 의 헤더가 {list(columns)} 가 아닙니다: {found}")
    rows: list[tuple[int, tuple[str, ...]]] = []
    for line, row in enumerate(reader[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(columns):
            raise ValueError(f"{name} {path} {line}행: 칸이 {len(columns)}개가 아닙니다 ({len(row)}개)")
        rows.append((line, tuple(cell.strip() for cell in row)))
    return rows


def parse_iso_date(text: str, where: str) -> date:
    """
    YYYY-MM-DD 날짜.

    Raises:
        ValueError: 모양이 다르거나 없는 날일 때 (where 와 「날짜」 포함)
    """
    if not _ISO_DATE.fullmatch(text):
        raise ValueError(f"{where}: 날짜 '{text}' 가 YYYY-MM-DD 가 아닙니다")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{where}: 날짜 '{text}' 가 없는 날입니다") from None
