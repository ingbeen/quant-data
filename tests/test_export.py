"""
export 모듈 테스트 — 사용처 저장소로 내보내기 (표준 라이브러리만)

이 파일은 무엇을 검증하나요?
1. 받는 폴더의 목록 파일(`quant_data_files.txt`)에 적힌 파일만 복사하는가? (결정 Q19)
2. 목록에 있는데 데이터 저장소에 없는 파일이면 아무것도 복사하지 않고 멈추는가?
3. 받는 폴더의 판 요약에 데이터 저장소의 커밋 번호와 내보낸 파일 중 커밋 안 된 것이 적히는가? (결정 Q2)
4. 내보내기 모듈이 표준 라이브러리만 import 하는가? — 다른 저장소의 `poetry run` 이 엉뚱한 가상환경을 잡아도 돈다
5. 판 요약 열쇠 · 경로가 갱신 쪽과 같은가? — 내보내기는 갱신 모듈을 import 하지 않고 같은 값을 따로 둔다

왜 중요한가요?
사용처는 내보낸 사본을 결과와 함께 커밋한다. 목록 밖 파일이 섞이거나 판 요약이 틀리면 옛 결과를 재현할 때
어느 판의 데이터로 돌았는지 알 수 없다.
"""

import ast
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from quant_data import constants, edition, export
from quant_data.export import (
    EDITION_FILE_NAME,
    KEY_COMMIT,
    KEY_UNCOMMITTED,
    LIST_FILE_NAME,
    RepoState,
    export_files,
    read_list_file,
    read_repo_state,
)

SYNTHETIC = "prices/QQQ_synthetic.csv"
ADJUSTED = "prices/QQQ_adjusted.csv"
FFR = "series/federal_funds_rate_monthly.csv"
QQQ_SYNTHETIC_ENTRY = {
    edition.KEY_TICKER: "QQQ",
    edition.KEY_FIRST_DAY: "1985-10-01",
    edition.KEY_LAST_DAY: "2026-11-06",
    edition.KEY_ROWS: 10360,
    edition.KEY_STATUS: edition.STATUS_PRODUCT,
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """데이터 저장소 대역 — 시세 둘 · 금리 하나와 그 판 요약."""
    repo = tmp_path / "quant-data"
    for relative, body in ((SYNTHETIC, "synthetic"), (ADJUSTED, "adjusted"), (FFR, "ffr")):
        path = repo / "storage" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{body}\n", encoding="utf-8")
    files = {
        f"storage/{SYNTHETIC}": QQQ_SYNTHETIC_ENTRY,
        f"storage/{ADJUSTED}": {**QQQ_SYNTHETIC_ENTRY, edition.KEY_STATUS: edition.STATUS_NOISE},
        f"storage/{FFR}": {edition.KEY_TICKER: "FFR", edition.KEY_STATUS: edition.STATUS_NOISE},
    }
    (repo / constants.EDITION_PATH).write_text(
        json.dumps({edition.KEY_CUTOFF: "2026-11-06", edition.KEY_FILES: files}, ensure_ascii=False),
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    """사용처의 받는 폴더 대역 — 목록 파일과, 목록과 상관없는 기존 파일 하나."""
    folder = tmp_path / "quant" / "storage" / "stock"
    folder.mkdir(parents=True)
    (folder / LIST_FILE_NAME).write_text(f"# quant 백테스트가 읽는 시세\n{SYNTHETIC}\n\n", encoding="utf-8")
    (folder / "untouched.csv").write_text("keep\n", encoding="utf-8")
    return folder


class StateRecorder:
    """저장소 상태 대역 — 받은 경로를 남기고 정해진 상태를 돌려준다."""

    def __init__(self, state: RepoState) -> None:
        self.state = state
        self.paths: list[Path] = []

    def __call__(self, _root: Path, paths: Sequence[Path]) -> RepoState:
        self.paths = list(paths)
        return self.state


CLEAN = RepoState(commit="0123abcd", uncommitted=())


class TestReadListFile:
    """목록 파일 — 한 줄에 storage 기준 경로 하나, 빈 줄 · # 주석 무시"""

    def test_reads_entries_skipping_comments_and_blanks(self, tmp_path: Path) -> None:
        """
        목적: 빈 줄과 # 로 시작하는 줄을 빼고 적힌 순서대로 읽는다

        Given: 주석 · 빈 줄 · 경로 둘
        When: read_list_file
        Then: 두 경로
        """
        # Given
        path = tmp_path / LIST_FILE_NAME
        path.write_text(f"# 주석\n{SYNTHETIC}\n\n  {FFR}  \n", encoding="utf-8")

        # When & Then
        assert read_list_file(path) == [SYNTHETIC, FFR]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """
        목적: 목록 파일이 없으면 멈춘다 — 받는 폴더를 잘못 준 경우다

        Given: 목록 파일이 없는 폴더
        When: read_list_file
        Then: FileNotFoundError (파일 이름)
        """
        # When & Then
        with pytest.raises(FileNotFoundError, match=LIST_FILE_NAME):
            read_list_file(tmp_path / LIST_FILE_NAME)

    @pytest.mark.parametrize(
        ("lines", "pattern"),
        [
            ([SYNTHETIC, SYNTHETIC], "중복"),
            ([SYNTHETIC, "other/QQQ_synthetic.csv"], "이름"),
            (["../secret.csv"], "storage"),
            (["/etc/passwd"], "storage"),
        ],
        ids=["duplicate", "same_name", "parent_escape", "absolute"],
    )
    def test_bad_entries_raise(self, tmp_path: Path, lines: list[str], pattern: str) -> None:
        """
        목적: 같은 줄 두 번 · 받는 폴더에서 같은 이름이 되는 두 줄 · storage 밖을 가리키는 줄은 받지 않는다 —
              받는 폴더는 한 층이라 같은 이름이면 나중 파일이 앞 파일을 덮는다

        Given: 잘못된 목록
        When: read_list_file
        Then: ValueError
        """
        # Given
        path = tmp_path / LIST_FILE_NAME
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            read_list_file(path)


class TestExportFiles:
    """내보내기 — 목록대로만 복사하고 판 요약을 쓴다"""

    def test_copies_only_listed_files(self, root: Path, destination: Path) -> None:
        """
        목적: 목록에 적힌 파일만 같은 바이트로 복사하고, 받는 폴더의 다른 파일은 건드리지 않는다

        Given: 데이터 저장소에 시세 둘 · 금리 하나, 목록에는 QQQ 합성 하나
        When: export_files
        Then: 받는 폴더에 QQQ_synthetic.csv(같은 바이트) · 판 요약 · 목록 · 원래 파일만 있다
        """
        # When
        result = export_files(root, destination, read_state=StateRecorder(CLEAN))

        # Then
        assert result.copied == ("QQQ_synthetic.csv",)
        assert (destination / "QQQ_synthetic.csv").read_bytes() == (root / "storage" / SYNTHETIC).read_bytes()
        assert sorted(p.name for p in destination.iterdir()) == sorted(
            [LIST_FILE_NAME, EDITION_FILE_NAME, "QQQ_synthetic.csv", "untouched.csv"]
        )
        assert (destination / "untouched.csv").read_text(encoding="utf-8") == "keep\n"

    def test_missing_source_stops_before_copying(self, root: Path, destination: Path) -> None:
        """
        목적: 목록에 있는데 데이터 저장소에 없는 파일이면 아무것도 복사하지 않고 멈춘다 — 일부만 바뀐 사본이 남지 않는다

        Given: 목록 = QQQ 합성 · 없는 파일
        When: export_files
        Then: ValueError (없는 경로), 받는 폴더는 목록 · 원래 파일뿐
        """
        # Given
        (destination / LIST_FILE_NAME).write_text(f"{SYNTHETIC}\nprices/NOPE_synthetic.csv\n", encoding="utf-8")

        # When & Then
        with pytest.raises(ValueError, match="NOPE_synthetic.csv"):
            export_files(root, destination, read_state=StateRecorder(CLEAN))
        assert sorted(p.name for p in destination.iterdir()) == sorted([LIST_FILE_NAME, "untouched.csv"])

    def test_edition_has_commit_uncommitted_and_entries(self, root: Path, destination: Path) -> None:
        """
        목적: 받는 폴더의 판 요약에 커밋 번호 · 내보낸 파일 중 커밋 안 된 것 · 기준일 · 파일마다 데이터 저장소 판 요약의
              항목을 적는다 — 로컬 작업 트리에서 가져오므로 커밋 번호만으로는 그 판을 말하지 못한다(Q2)

        Given: 커밋 0123abcd, QQQ 합성이 커밋 안 됨
        When: export_files
        Then: 판 요약 = {커밋: 0123abcd, 커밋 안 된 변경: [storage/prices/QQQ_synthetic.csv], 기준일, 파일: {QQQ_synthetic.csv: 항목}}
        """
        # Given
        state = RepoState(commit="0123abcd", uncommitted=(f"storage/{SYNTHETIC}",))

        # When
        export_files(root, destination, read_state=StateRecorder(state))

        # Then
        written = json.loads((destination / EDITION_FILE_NAME).read_text(encoding="utf-8"))
        assert written == {
            KEY_COMMIT: "0123abcd",
            KEY_UNCOMMITTED: [f"storage/{SYNTHETIC}"],
            edition.KEY_CUTOFF: "2026-11-06",
            edition.KEY_FILES: {"QQQ_synthetic.csv": QQQ_SYNTHETIC_ENTRY},
        }

    def test_repo_state_is_asked_for_exported_files_and_edition(self, root: Path, destination: Path) -> None:
        """
        목적: 커밋 안 된 변경은 저장소 전체가 아니라 내보낸 파일과 판 요약으로 잰다 — 계획서만 고쳐도 「변경 있음」이 되면
              그 표시를 무시하게 된다

        Given: 목록 = QQQ 합성
        When: export_files
        Then: 저장소 상태를 물은 경로 = [storage/prices/QQQ_synthetic.csv, storage/edition.json]
        """
        # Given
        recorder = StateRecorder(CLEAN)

        # When
        export_files(root, destination, read_state=recorder)

        # Then
        assert recorder.paths == [Path("storage") / SYNTHETIC, constants.EDITION_PATH]

    def test_listed_file_missing_in_edition_raises(self, root: Path, destination: Path) -> None:
        """
        목적: 데이터 저장소 판 요약에 없는 파일은 내보내지 않는다 — 판 요약이 낡았거나 갱신 밖에서 만든 파일이다

        Given: 판 요약에서 QQQ 합성 항목을 뺌
        When: export_files
        Then: ValueError (「판 요약」)
        """
        # Given
        path = root / constants.EDITION_PATH
        data = json.loads(path.read_text(encoding="utf-8"))
        del data[edition.KEY_FILES][f"storage/{SYNTHETIC}"]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        # When & Then
        with pytest.raises(ValueError, match="판 요약"):
            export_files(root, destination, read_state=StateRecorder(CLEAN))


class FakeRun:
    """subprocess.run 대역 — 명령 앞 두 낱말로 응답을 고른다."""

    def __init__(self, responses: dict[tuple[str, str], tuple[int, str]]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        code, stdout = self.responses[(command[1], command[2])]
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")


class TestReadRepoState:
    """git 으로 커밋 번호와 커밋 안 된 경로를 읽는다"""

    def test_reads_commit_and_uncommitted_paths(self, tmp_path: Path) -> None:
        """
        목적: 커밋 번호는 HEAD, 커밋 안 된 경로는 porcelain -z 의 경로 — 경로에 ^ · = 같은 글자가 있어도 그대로 읽는다

        Given: HEAD = 0123abcd, 상태 = 새 파일 하나 · 바뀐 파일 하나
        When: read_repo_state
        Then: RepoState(0123abcd, 두 경로)
        """
        # Given
        run = FakeRun(
            {
                ("rev-parse", "HEAD"): (0, "0123abcd\n"),
                ("status", "--porcelain"): (0, "?? storage/prices/^NDX_raw.csv\0 M storage/edition.json\0"),
            }
        )

        # When
        state = read_repo_state(tmp_path, [Path("storage/prices/^NDX_raw.csv"), Path("storage/edition.json")], run=run)

        # Then
        assert state == RepoState(
            commit="0123abcd", uncommitted=("storage/prices/^NDX_raw.csv", "storage/edition.json")
        )

    def test_no_commit_yet(self, tmp_path: Path) -> None:
        """
        목적: 커밋이 하나도 없는 저장소는 커밋 번호 없음으로 적는다 (경계) — 멈추지 않고 「모두 커밋 안 됨」으로 보인다

        Given: rev-parse 실패, 상태 = 새 파일 하나
        When: read_repo_state
        Then: commit None
        """
        # Given
        run = FakeRun({("rev-parse", "HEAD"): (128, ""), ("status", "--porcelain"): (0, "?? storage/edition.json\0")})

        # When
        state = read_repo_state(tmp_path, [Path("storage/edition.json")], run=run)

        # Then
        assert state.commit is None
        assert state.uncommitted == ("storage/edition.json",)

    def test_status_failure_raises(self, tmp_path: Path) -> None:
        """
        목적: git 상태를 읽지 못하면 멈춘다 — 「커밋 안 된 변경 없음」으로 적으면 판 요약이 거짓이 된다

        Given: status 실패 (git 저장소가 아님)
        When: read_repo_state
        Then: RuntimeError (「git」)
        """
        # Given
        run = FakeRun({("rev-parse", "HEAD"): (128, ""), ("status", "--porcelain"): (128, "")})

        # When & Then
        with pytest.raises(RuntimeError, match="git"):
            read_repo_state(tmp_path, [Path("storage/edition.json")], run=run)


class TestStandardLibraryOnly:
    """내보내기는 표준 라이브러리만 쓴다 (Q19)"""

    def test_imports_are_standard_library(self) -> None:
        """
        목적: 내보내기 모듈의 import 가 모두 표준 라이브러리다 — 판다스 · quant_data 다른 모듈을 import 하면
              사용처 저장소의 파이썬으로 돌릴 수 없다

        Given: export 모듈 소스
        When: import 문의 최상위 모듈 이름을 모은다
        Then: 모두 sys.stdlib_module_names 안 (__future__ 포함)
        """
        # Given
        tree = ast.parse(Path(export.__file__).read_text(encoding="utf-8"))

        # When
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])

        # Then
        assert modules - set(sys.stdlib_module_names) == set()


class TestSharedValues:
    """내보내기가 따로 둔 값이 갱신 쪽과 같다"""

    def test_keys_and_paths_match_update_side(self) -> None:
        """
        목적: 판 요약 열쇠(기준일 · 파일)와 저장 경로(storage · 판 요약 파일)가 갱신 쪽 상수와 같다 — 한쪽만 바꾸면
              내보내기가 판 요약을 읽지 못하거나 엉뚱한 폴더를 본다

        Given: export · edition · constants 의 값
        When: 비교
        Then: 같다
        """
        # Then
        assert export.KEY_CUTOFF == edition.KEY_CUTOFF
        assert export.KEY_FILES == edition.KEY_FILES
        assert export.STORAGE_DIR == constants.STORAGE_DIR
        assert export.EDITION_PATH == constants.EDITION_PATH
