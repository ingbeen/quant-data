"""CLI 스크립트 공통 헬퍼 함수

CLI 스크립트에서 공통으로 사용하는 예외 처리 데코레이터를 제공한다.
"""

import logging
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from quant_data.constants import STORAGE_DIR


def cli_exception_handler(func: Callable[[], int]) -> Callable[[], int]:
    """
    CLI main() 함수의 예외를 일관되게 처리하는 데코레이터.

    모든 예외를 캐치하여 스택 트레이스를 포함한 에러 로그를 남기고 실패 코드(1)를 반환한다.
    로거는 함수가 정의된 모듈의 최상위 'logger' 변수를 쓴다(없으면 KeyError).

    실행 위치에 `STORAGE_DIR` 폴더가 없으면 함수를 실행하지 않고 실패 코드를 반환한다 — 입력 · 결과 경로가
    실행 위치 기준이라, 저장소 루트 밖에서 돌리면 입력을 못 찾거나 결과가 엉뚱한 폴더에 생긴다.

    예외 메시지는 스택 트레이스에 포함되므로 별도로 출력하지 않아 중복을 방지한다.

    사용 예시:
        @cli_exception_handler
        def main() -> int:
            # 비즈니스 로직
            return 0

    Args:
        func: CLI의 main() 함수 (반환값: 0=성공, 1=실패)

    Returns:
        래핑된 함수 (원본 함수를 감싼 wrapper 함수)
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> int:
        # 모듈 객체(sys.modules[func.__module__])가 아니라 함수의 전역 이름공간에서 찾는다 — 스크립트를 다른 이름공간으로
        # 실행하는 실행기(python -m cProfile 등)에서는 그 모듈 객체가 실행기 자신이다
        logger: logging.Logger = func.__globals__["logger"]

        try:
            if not STORAGE_DIR.is_dir():
                raise FileNotFoundError(f"저장소 루트에서 실행하세요 — 현재 위치({Path.cwd()})에 '{STORAGE_DIR}' 폴더가 없습니다")
            return func(*args, **kwargs)

        except Exception:
            # 스택 트레이스에 예외 타입과 메시지가 포함된다
            logger.error("예외 발생", exc_info=True)

            # Unix 관례: 0=성공, 1=실패
            return 1

    return wrapper
