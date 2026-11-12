"""내보내기 — 데이터 저장소의 파일을 사용처 저장소의 받는 폴더로 복사한다 (표준 라이브러리만)

받는 폴더의 목록 파일(LIST_FILE_NAME — 한 줄에 storage 기준 경로 하나)에 적힌 파일만 복사하고, 같은 폴더에 매니페스트
(MANIFEST_FILE_NAME — 데이터 저장소의 커밋 번호 · 내보낸 파일 중 커밋 안 된 것 · 기준일 · 파일마다의 매니페스트 항목)을
쓴다(결정 Q2 · Q19). 사용처는 이 사본을 결과와 함께 커밋한다.

표준 라이브러리만 쓰고 quant_data 의 다른 모듈도 import 하지 않는다 — 사용처 저장소의 세션이 그 저장소의 파이썬으로
`python3 <데이터 저장소>/scripts/export.py` 를 돌려도 된다(다른 저장소의 `poetry run` 은 엉뚱한 가상환경을 잡는다).
그래서 매니페스트 키 · 경로를 여기 따로 두고, 갱신 쪽(manifest · constants)과 같은지는 테스트가 지킨다.
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

STORAGE_DIR: Final = Path("storage")
MANIFEST_PATH: Final = STORAGE_DIR / "manifest.json"
LIST_FILE_NAME: Final = "quant_data_files.txt"
MANIFEST_FILE_NAME: Final = "quant_data_manifest.json"

KEY_CUTOFF: Final = "기준일"
KEY_FILES: Final = "파일"
KEY_COMMIT: Final = "커밋"
KEY_UNCOMMITTED: Final = "커밋 안 된 변경"

# 이 파일 위치 기준 — 실행 위치가 사용처 저장소여도 데이터 저장소 루트를 가리킨다
_REPO_ROOT: Final = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RepoState:
    """데이터 저장소의 git 상태 — commit 은 HEAD(커밋이 없으면 None), uncommitted 는 물은 경로 중 커밋 안 된 것."""

    commit: str | None
    uncommitted: tuple[str, ...]


@dataclass(frozen=True)
class ExportResult:
    copied: tuple[str, ...]  # 받는 폴더의 파일 이름
    state: RepoState


def read_list_file(path: Path) -> list[str]:
    """
    목록 파일 — 빈 줄과 # 로 시작하는 줄을 빼고 적힌 순서대로. 한 줄은 storage 기준 경로(예: prices/QQQ_synthetic.csv).

    Raises:
        FileNotFoundError: 목록 파일이 없을 때
        ValueError: storage 밖을 가리키는 줄, 같은 줄 두 번(중복), 받는 폴더에서 같은 이름이 되는 두 줄
    """
    if not path.exists():
        raise FileNotFoundError(f"목록 파일 {LIST_FILE_NAME} 이 없습니다: {path} — 받는 폴더에 받을 파일 목록을 두세요")
    entries: list[str] = []
    names: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        pure = PurePosixPath(entry)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"{path} {line_number}행: {entry} 는 storage 밖을 가리킵니다 — storage 기준 경로를 적으세요")
        if entry in entries:
            raise ValueError(f"{path} {line_number}행: {entry} 가 두 번 적혔습니다(중복)")
        if pure.name in names:
            raise ValueError(f"{path} {line_number}행: {entry} 와 {names[pure.name]} 가 받는 폴더에서 같은 이름 {pure.name} 이 됩니다")
        names[pure.name] = entry
        entries.append(entry)
    return entries


def read_repo_state(
    root: Path,
    paths: Sequence[Path],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> RepoState:
    """
    git 으로 HEAD 커밋 번호와, paths 중 커밋 안 된 변경(새 파일 · 바뀐 파일)이 있는 경로를 읽는다.

    Raises:
        RuntimeError: git 상태를 읽지 못할 때 (git 저장소가 아님 등) — 「변경 없음」으로 적으면 매니페스트가 거짓이 된다
    """
    head = run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    commit = head.stdout.strip() if head.returncode == 0 else None
    status = run(
        ["git", "status", "--porcelain", "-z", "--", *(path.as_posix() for path in paths)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        raise RuntimeError(f"git 상태를 읽지 못했습니다(종료 코드 {status.returncode}): {status.stderr.strip()} — {root}")
    tokens = [token for token in status.stdout.split("\0") if token]
    uncommitted: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        code, file = token[:2], token[3:]
        uncommitted.append(file)
        # 이름 바꿈 · 복사는 다음 토큰이 옛 경로 (-z 형식)
        skip_next = "R" in code or "C" in code
    return RepoState(commit=commit, uncommitted=tuple(uncommitted))


def export_files(
    root: Path,
    destination: Path,
    *,
    read_state: Callable[[Path, Sequence[Path]], RepoState] = read_repo_state,
) -> ExportResult:
    """
    목록대로 복사하고 받는 폴더에 매니페스트를 쓴다. 받는 폴더의 다른 파일은 건드리지 않는다.

    Raises:
        FileNotFoundError: 목록 파일 · 데이터 저장소 매니페스트가 없을 때
        ValueError: 목록이 잘못됐을 때(read_list_file), 목록의 파일이 데이터 저장소에 없거나 매니페스트에 없을 때 —
            모두 복사하기 전에
    """
    entries = read_list_file(destination / LIST_FILE_NAME)
    sources = [STORAGE_DIR / entry for entry in entries]
    missing = [entry for entry, source in zip(entries, sources, strict=True) if not (root / source).is_file()]
    if missing:
        raise ValueError(f"목록에 있는데 데이터 저장소에 없는 파일: {missing} — 갱신을 먼저 돌렸는지, 이름이 맞는지 확인하세요")

    manifest = _read_manifest(root / MANIFEST_PATH)
    files: dict[str, Any] = manifest[KEY_FILES]
    not_in_manifest = [source.as_posix() for source in sources if source.as_posix() not in files]
    if not_in_manifest:
        raise ValueError(f"데이터 저장소 매니페스트에 없는 파일: {not_in_manifest} — 매니페스트가 낡았거나 갱신 밖에서 만든 파일입니다")

    state = read_state(root, [*sources, MANIFEST_PATH])
    copied: list[str] = []
    for source in sources:
        shutil.copyfile(root / source, destination / source.name)
        copied.append(source.name)
    summary = {
        KEY_COMMIT: state.commit,
        KEY_UNCOMMITTED: list(state.uncommitted),
        KEY_CUTOFF: manifest[KEY_CUTOFF],
        KEY_FILES: {source.name: files[source.as_posix()] for source in sources},
    }
    (destination / MANIFEST_FILE_NAME).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ExportResult(copied=tuple(copied), state=state)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"데이터 저장소 매니페스트가 없습니다: {path} — 갱신을 먼저 돌리세요")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or KEY_CUTOFF not in data or not isinstance(data.get(KEY_FILES), dict):
        raise ValueError(f"매니페스트 {path} 에 「{KEY_CUTOFF}」 · 「{KEY_FILES}」 키가 없습니다")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    """내보내기 CLI — 받는 폴더(--to)의 목록대로 복사한다. 종료 코드 0 = 성공 (실패는 예외로 끝난다)."""
    parser = argparse.ArgumentParser(description="quant-data 의 파일을 사용처 저장소의 받는 폴더로 복사한다")
    parser.add_argument("--to", required=True, type=Path, help=f"받는 폴더 (그 안에 {LIST_FILE_NAME} 이 있어야 한다)")
    args = parser.parse_args(argv)
    destination: Path = args.to.resolve()

    result = export_files(_REPO_ROOT, destination)
    print(f"{destination} 에 {len(result.copied)}개 복사 · 매니페스트 {MANIFEST_FILE_NAME}")
    print(f"데이터 저장소 커밋: {result.state.commit or '없음(커밋 전)'}")
    if result.state.uncommitted:
        print(f"[주의] 커밋 안 된 변경이 있는 파일 {len(result.state.uncommitted)}개 — 매니페스트에 적었습니다:")
        for file in result.state.uncommitted:
            print(f"  - {file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
