"""
내보내기 — 데이터 저장소의 파일을 사용처 저장소의 받는 폴더로 복사한다 (표준 라이브러리만)

본문은 src/quant_data/export.py 다. 이 진입점은 그 파일을 경로로 실행해 quant_data 패키지 설치 없이 파이썬 3.10 이상의
python3 로 돈다 — 사용처 저장소의 세션에서 돌려도 된다. 실행 명령은 docs/COMMANDS.md 가 정본이다.
"""

import runpy
import sys
from pathlib import Path

# 본문이 3.10 문법(X | None)을 씀 → macOS 기본 /usr/bin/python3(3.9)에서는 TypeError 대신 이 안내로 멈춤
_MINIMUM_VERSION = (3, 10)

if __name__ == "__main__":
    if sys.version_info < _MINIMUM_VERSION:
        sys.exit(
            f"내보내기는 파이썬 3.10 이상이 필요합니다 — 지금 {sys.version.split()[0]} ({sys.executable}). "
            "brew · pyenv 의 python3 로 다시 실행하세요"
        )
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src" / "quant_data" / "export.py"), run_name="__main__")
