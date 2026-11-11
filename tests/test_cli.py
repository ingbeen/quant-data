"""cli_helpers.py 모듈 테스트

CLI 예외 처리 데코레이터의 계약을 검증한다.

테스트 대상:
- cli_exception_handler: CLI main() 함수의 예외 처리 데코레이터
"""

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from quant_data.cli import cli_exception_handler
from quant_data.constants import STORAGE_DIR

# 데코레이터는 함수가 정의된 모듈의 `logger` 를 쓴다 — 이 테스트 모듈이 CLI 스크립트 자리다
logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def storage_dir_in_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """실행 위치를 `STORAGE_DIR` 폴더가 있는 임시 폴더로 옮긴다 (데코레이터의 실행 위치 확인을 통과시킨다)."""
    (tmp_path / STORAGE_DIR).mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestCliExceptionHandler:
    """cli_exception_handler 데코레이터 테스트

    목적: 예외 처리, 모듈 로거 사용, 실행 위치 확인, 종료 코드 반환 계약 검증
    """

    def test_normal_execution_returns_zero(self):
        """
        정상 실행 시 함수의 반환값(0)을 그대로 반환한다.

        Given: 정상 실행되는 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 함수의 반환값 0을 반환
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            return 0

        # When
        result = main()

        # Then
        assert result == 0

    def test_file_not_found_error_returns_one(self, caplog):
        """
        FileNotFoundError 발생 시 종료 코드 1을 반환한다.

        Given: FileNotFoundError를 발생시키는 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 종료 코드 1 반환, 에러 로그 출력
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            raise FileNotFoundError("파일을 찾을 수 없습니다")

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        # 에러 로그 확인
        assert any("예외 발생" in record.message for record in caplog.records)

    def test_value_error_returns_one(self, caplog):
        """
        ValueError 발생 시 종료 코드 1을 반환한다.

        Given: ValueError를 발생시키는 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 종료 코드 1 반환, 에러 로그 출력
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            raise ValueError("잘못된 값입니다")

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        assert any("예외 발생" in record.message for record in caplog.records)

    def test_generic_exception_returns_one(self, caplog):
        """
        일반 Exception 발생 시 종료 코드 1을 반환한다.

        Given: Exception을 발생시키는 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 종료 코드 1 반환, 에러 로그 출력
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            raise Exception("일반 예외")

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        assert any("예외 발생" in record.message for record in caplog.records)

    def test_error_is_logged_with_module_logger(self, caplog: pytest.LogCaptureFixture):
        """
        목적: 예외를 함수가 정의된 모듈의 `logger` 로 기록하는지 검증

        Given: 모듈 레벨 `logger` 가 있는 모듈의 함수가 예외를 낸다
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 에러 로그의 로거 이름이 그 모듈 `logger` 의 이름이다
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            raise ValueError("테스트 예외")

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        assert [record.name for record in caplog.records] == [logger.name]

    def test_logger_is_read_from_function_globals(self, caplog: pytest.LogCaptureFixture):
        """
        목적: 스크립트를 다른 이름공간으로 실행하는 실행기(python -m cProfile 등)에서도 그 스크립트의 `logger` 를 쓰는지 검증
              — 그런 실행기에서 `sys.modules[func.__module__]` 은 스크립트가 아니라 실행기 모듈이다

        Given: 함수의 전역 이름공간에는 `logger` 가 있고, 그 함수의 `__module__` 이름은 sys.modules 에 없다
        When: @cli_exception_handler 데코레이터를 적용한 함수가 예외를 낸다
        Then: 종료 코드 1, 에러 로그의 로거 이름이 그 이름공간의 `logger` 이름이다
        """
        # Given
        namespace: dict[str, Any] = {
            "__name__": "_script_run_by_profiler",
            "cli_exception_handler": cli_exception_handler,
            "logger": logging.getLogger("script_run_by_profiler"),
        }
        exec("@cli_exception_handler\ndef main() -> int:\n    raise ValueError('테스트 예외')\n", namespace)
        assert namespace["__name__"] not in sys.modules

        # When
        with caplog.at_level(logging.ERROR):
            result = namespace["main"]()

        # Then
        assert result == 1
        assert [record.name for record in caplog.records] == ["script_run_by_profiler"]

    def test_module_without_logger_raises_key_error(self, monkeypatch: pytest.MonkeyPatch):
        """
        목적: 모듈에 `logger` 가 없으면 다른 로거로 바꾸지 않고 멈추는지 검증

        Given: `logger` 변수가 없는 모듈의 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: KeyError 발생
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            return 0

        monkeypatch.delattr(sys.modules[__name__], "logger")

        # When & Then
        with pytest.raises(KeyError, match="logger"):
            main()

    def test_outside_repo_root_returns_one_without_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """
        목적: 실행 위치에 `STORAGE_DIR` 폴더가 없으면 함수를 실행하지 않고 안내와 함께 실패하는지 검증
              — 경로가 실행 위치 기준이라 저장소 루트 밖에서는 입력을 못 찾거나 결과가 엉뚱한 폴더에 생긴다

        Given: `STORAGE_DIR` 폴더가 없는 실행 위치
        When: @cli_exception_handler 데코레이터를 적용한 함수 실행
        Then: 종료 코드 1, 함수 본문은 실행되지 않음, 예외 문구가 저장소 루트에서 실행하라고 안내
        """
        # Given
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        calls: list[str] = []

        @cli_exception_handler
        def main() -> int:
            calls.append("ran")
            return 0

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        assert calls == []
        logged_errors = [record.exc_info[1] for record in caplog.records if record.exc_info]
        assert len(logged_errors) == 1
        assert isinstance(logged_errors[0], FileNotFoundError)
        assert "저장소 루트에서 실행하세요" in str(logged_errors[0])

    def test_exception_info_logged(self, caplog):
        """
        예외 발생 시 스택 트레이스가 로그에 포함된다.

        Given: 예외를 발생시키는 함수
        When: @cli_exception_handler 데코레이터 적용 후 실행
        Then: 로그에 스택 트레이스 포함 (exc_info=True)
        """

        # Given
        @cli_exception_handler
        def main() -> int:
            raise RuntimeError("런타임 에러 테스트")

        # When
        with caplog.at_level(logging.ERROR):
            result = main()

        # Then
        assert result == 1
        # exc_info=True로 인해 exc_info가 로그 레코드에 포함됨
        assert any(record.exc_info is not None for record in caplog.records)

    def test_decorator_preserves_function_metadata(self):
        """
        데코레이터가 원본 함수의 메타데이터를 보존한다.

        Given: 독스트링과 이름이 있는 함수
        When: @cli_exception_handler 데코레이터 적용
        Then: 함수명과 독스트링 보존 (@wraps 동작 확인)
        """

        # Given
        @cli_exception_handler
        def test_function() -> int:
            """테스트 함수 독스트링"""
            return 0

        # When & Then
        # @wraps(func)가 동작하면 함수명과 독스트링이 보존됨
        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "테스트 함수 독스트링"
