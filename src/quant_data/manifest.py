"""매니페스트 — 갱신이 남긴 버전의 파일마다 종목 · 기간 · 행 수 · 상태 · 분배 기록 첫날 · 분배 대조 어긋난 날 (결정 Q12)

갱신이 끝날 때마다 다시 쓴다. 실행 끝 경고(제외 · 받아들임)가 사라진 뒤에도 이 파일이 그 버전의 예외를 말하고,
내보내기가 사용처로 옮겨 사용처가 가져간 사본이 어느 버전인지 말한다. 실행 시각은 적지 않는다 — 데이터가 그대로인
재실행이 diff 를 내지 않게.
"""

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Final

KEY_CUTOFF: Final = "기준일"
KEY_FILES: Final = "파일"  # 저장소 루트 기준 posix 경로 → 항목
KEY_TICKER: Final = "종목"
KEY_FIRST_DAY: Final = "첫날"
KEY_LAST_DAY: Final = "끝날"
KEY_ROWS: Final = "행 수"
KEY_STATUS: Final = "상태"
KEY_FIRST_DIVIDEND: Final = "분배 기록 첫날"  # 야후 응답의 첫 배당 기록 — 그 앞 구간은 배당이 수정주가에 없다
KEY_DISTRIBUTION_CHECK: Final = "분배 대조 어긋난 날"  # 국내 수정주가 — KRX 기준가 ↔ 야후 분배 기록 (결정 Q28)

STATUS_NEW: Final = "신규"
STATUS_NOISE: Final = "노이즈뿐"
STATUS_DIVIDEND_ADJUSTED: Final = "배당 반영"
STATUS_ACCEPTED: Final = "받아들임"
STATUS_EXCLUDED: Final = "제외"
STATUS_FIXED: Final = "고정"
STATUS_NOT_FETCHED: Final = "미수집"  # --no-fetch 로 지금 파일만 가공한 버전
STATUS_PRODUCT: Final = "가공"


def read_manifest(path: Path) -> dict[str, Any] | None:
    """
    매니페스트를 읽는다. 파일이 없으면 None.

    Raises:
        ValueError: JSON 이 아니거나 기준일 · 파일 키가 없을 때
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"매니페스트 {path} 가 JSON 이 아닙니다: {error}") from None
    if not isinstance(data, dict) or KEY_CUTOFF not in data or not isinstance(data.get(KEY_FILES), dict):
        raise ValueError(f"매니페스트 {path} 에 「{KEY_CUTOFF}」 · 「{KEY_FILES}」 키가 없습니다")
    return data


def write_manifest(path: Path, cutoff_date: date, files: Mapping[Path, Mapping[str, object]]) -> None:
    """매니페스트를 쓴다 — 파일 순서는 받은 순서, 한글은 그대로(ensure_ascii=False)."""
    data = {
        KEY_CUTOFF: cutoff_date.isoformat(),
        KEY_FILES: {file.as_posix(): dict(entry) for file, entry in files.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
