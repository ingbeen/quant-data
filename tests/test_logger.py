"""logger.py 모듈 테스트

로거 설정 및 포맷팅 기능의 계약을 검증한다.

테스트 대상:
- setup_logger(): 로거 생성 및 설정
- get_logger(): 로거 조회 및 지연 초기화
- ClickableFormatter: VSCode 클릭 가능한 경로 포맷팅
"""

import logging
from io import StringIO
from pathlib import Path

import pytest

from quant_data.logger import ClickableFormatter, get_logger, setup_logger


class TestSetupLogger:
    """setup_logger() 함수 테스트

    목적: 로거 생성, 핸들러 설정 계약 검증
    """

    def test_creates_logger_with_default_level(self):
        """
        로거 생성 시 DEBUG 레벨로 설정된다.

        Given: 새 로거 이름
        When: setup_logger() 호출
        Then: DEBUG 레벨 로거 반환
        """
        # Given & When
        logger = setup_logger(name="test_default_level")

        # Then
        assert logger.level == logging.DEBUG

    def test_prevents_duplicate_handlers(self):
        """
        동일 이름으로 재호출 시 핸들러가 중복 추가되지 않는다.

        Given: 이미 생성된 로거
        When: 동일 이름으로 setup_logger() 재호출
        Then: 핸들러 수 변경 없음
        """
        # Given
        logger1 = setup_logger(name="test_duplicate_handlers")
        initial_handler_count = len(logger1.handlers)

        # When
        logger2 = setup_logger(name="test_duplicate_handlers")

        # Then
        assert logger1 is logger2  # 동일 로거 인스턴스
        assert len(logger2.handlers) == initial_handler_count

    def test_logger_has_console_handler(self):
        """
        생성된 로거는 콘솔 핸들러를 가진다.

        Given: 로거 생성
        When: setup_logger() 호출
        Then: StreamHandler 포함
        """
        # Given & When
        logger = setup_logger(name="test_console_handler")

        # Then
        assert len(logger.handlers) > 0
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_logger_propagate_is_false(self):
        """
        생성된 로거는 상위 로거로 전파하지 않는다.

        Given: 로거 생성
        When: setup_logger() 호출
        Then: propagate=False
        """
        # Given & When
        logger = setup_logger(name="test_propagate")

        # Then
        assert logger.propagate is False


class TestGetLogger:
    """get_logger() 함수 테스트

    목적: 로거 조회 및 지연 초기화 계약 검증
    """

    def test_returns_existing_logger(self):
        """
        이미 존재하는 로거를 반환한다.

        Given: 기존 로거 존재
        When: get_logger() 호출
        Then: 기존 로거 반환
        """
        # Given
        existing_logger = setup_logger(name="test_existing_logger")

        # When
        logger = get_logger(name="test_existing_logger")

        # Then
        assert logger is existing_logger

    def test_creates_logger_if_not_exists(self):
        """
        로거가 없으면 새로 생성한다.

        Given: 로거 미존재
        When: get_logger() 호출
        Then: 새 로거 생성 및 반환
        """
        # Given
        logger_name = "test_new_logger_from_get"

        # When
        logger = get_logger(name=logger_name)

        # Then
        assert logger.name == logger_name
        assert len(logger.handlers) > 0


class TestClickableFormatter:
    """ClickableFormatter 클래스 테스트

    목적: VSCode 클릭 가능한 경로 포맷팅 계약 검증
    """

    def test_finds_project_root(self):
        """
        프로젝트 루트를 찾는다 (pyproject.toml 또는 .git 기준).

        Given: 프로젝트 루트 존재
        When: ClickableFormatter 인스턴스 생성
        Then: project_root가 Path 객체로 설정됨
        """
        # Given & When
        formatter = ClickableFormatter()

        # Then
        assert isinstance(formatter.project_root, Path)
        # 프로젝트 루트는 pyproject.toml 또는 .git을 포함해야 함
        assert (formatter.project_root / "pyproject.toml").exists() or (formatter.project_root / ".git").exists()

    def test_formats_record_with_location(self):
        """
        로그 레코드에 상대 경로 location 필드를 추가한다.

        Given: 로그 레코드
        When: format() 호출
        Then: record.location 필드 추가됨 (파일경로:줄번호)
        """
        # Given
        formatter = ClickableFormatter(fmt="%(location)s - %(message)s")
        logger = logging.getLogger("test_formatter")
        logger.setLevel(logging.DEBUG)
        logger.handlers = []

        # StringIO 핸들러 추가
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # When
        logger.debug("테스트 메시지")

        # Then
        output = stream.getvalue()
        # location 필드가 포함되어야 함 (파일경로:줄번호 형식)
        assert ":" in output  # 파일경로:줄번호
        assert "테스트 메시지" in output

    def test_handles_external_library_paths(self):
        """
        외부 라이브러리 경로는 상대 경로로 변환할 수 없어도 정상 동작한다.

        Given: 외부 경로의 로그 레코드
        When: format() 호출
        Then: ValueError 없이 정상 포맷팅
        """
        # Given
        formatter = ClickableFormatter(fmt="%(location)s - %(message)s")

        # 가짜 로그 레코드 생성 (외부 경로)
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="/외부/라이브러리/경로/file.py",
            lineno=42,
            msg="테스트",
            args=(),
            exc_info=None,
        )

        # When
        try:
            result = formatter.format(record)
            # Then
            # ValueError 없이 정상 포맷팅되어야 함
            assert "42" in result  # 줄번호는 포함되어야 함
        except ValueError:
            pytest.fail("외부 경로 처리 시 ValueError 발생")


class TestLoggerIntegration:
    """로거 통합 테스트

    목적: 전체 로거 워크플로우 검증
    """

    def test_logger_workflow(self):
        """
        로거 생성 → 사용 전체 워크플로우가 정상 동작한다.

        Given: 새 로거 생성
        When: DEBUG/WARNING 로그 출력
        Then: 레벨에 따라 모두 출력됨
        """
        # Given
        logger = setup_logger(name="test_workflow_integration")

        # 로그 캡처를 위한 StringIO 핸들러 추가
        stream = StringIO()
        test_handler = logging.StreamHandler(stream)
        test_handler.setLevel(logging.DEBUG)
        logger.addHandler(test_handler)

        # When - DEBUG 레벨에서 로그
        logger.debug("DEBUG 메시지")
        logger.warning("WARNING 메시지")

        # Then - 둘 다 출력됨
        output1 = stream.getvalue()
        assert "DEBUG 메시지" in output1
        assert "WARNING 메시지" in output1
