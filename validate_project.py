#!/usr/bin/env python3
"""
통합 품질 검증 스크립트 (Ruff + PyRight + Pytest)

프로젝트의 모든 품질 검증을 단일 진입점으로 실행합니다.
AI가 실행하고 로그를 읽어 문제를 수정할 수 있도록 명확한 출력을 제공합니다.

사용법:
    poetry run python validate_project.py                # 전체 실행 (Ruff + PyRight + Pytest)
    poetry run python validate_project.py --only-lint    # Ruff만 실행
    poetry run python validate_project.py --only-pyright # PyRight만 실행
    poetry run python validate_project.py --only-tests   # Pytest만 실행
    poetry run python validate_project.py --cov          # Pytest + 커버리지만 실행
"""

import argparse
import re
import subprocess
import sys


def print_section(title: str) -> None:
    """섹션 제목을 출력합니다."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def _run_tool(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """도구를 실행하고 그 출력을 그대로 보여 줍니다. 통과 여부는 종료 코드(0 = 통과)로 판정합니다."""
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return result


def run_ruff() -> bool:
    """
    Ruff 린트 체크를 실행합니다.

    Returns:
        bool: 성공 여부
    """
    success = _run_tool(["poetry", "run", "ruff", "check", "."]).returncode == 0
    print("[OK] Ruff 체크 통과" if success else "[FAIL] Ruff 체크 실패")
    return success


def run_pyright() -> bool:
    """
    PyRight 타입 체크를 실행합니다.

    Returns:
        bool: 성공 여부
    """
    success = _run_tool(["poetry", "run", "pyright"]).returncode == 0
    print("[OK] PyRight 체크 통과" if success else "[FAIL] PyRight 체크 실패")
    return success


def run_pytest(with_coverage: bool = False) -> tuple[bool, str]:
    """
    Pytest 테스트를 실행합니다.

    Args:
        with_coverage: True일 경우 커버리지 포함 실행

    Returns:
        tuple[bool, str]: (성공 여부, 통과했을 때의 개수 "passed=N, failed=0, skipped=M" — 실패하면 빈 문자열)
    """
    if with_coverage:
        cmd = [
            "poetry",
            "run",
            "pytest",
            "--cov=src/quant_data",
            "--cov-report=term-missing",
            "tests/",
            "-v",
        ]
    else:
        cmd = ["poetry", "run", "pytest", "tests/", "-v"]

    result = _run_tool(cmd)

    if result.returncode != 0:
        # 실패한 실행의 개수는 찍지 않는다 — 수집 단계에서 죽으면 요약 줄에 failed 가 없어 "failed=0" 으로 읽힌다
        print("[FAIL] Pytest 실패")
        return False, ""

    # 통과한 실행의 마지막 요약 줄("= 946 passed, 1 skipped in 17.02s =")에서 개수를 읽는다 (0 인 항목은 줄에 없다).
    # 종료 코드 0 은 실패 · 수집 오류가 없다는 뜻이라 failed 는 0 이다
    summary_line = next(line for line in reversed(result.stdout.splitlines()) if re.search(r" in [\d.]+s", line))
    counts = {name: int(number) for number, name in re.findall(r"(\d+) (\w+)", summary_line)}
    detail = f"passed={counts['passed']}, failed=0, skipped={counts.get('skipped', 0)}"

    print(f"[OK] Pytest 통과 ({detail})")
    return True, detail


def parse_args() -> argparse.Namespace:
    """명령행 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="통합 품질 검증 스크립트 (Ruff + PyRight + Pytest)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  poetry run python validate_project.py                # 전체 실행 (Ruff + PyRight + Pytest)
  poetry run python validate_project.py --only-lint    # Ruff만 실행
  poetry run python validate_project.py --only-pyright # PyRight만 실행
  poetry run python validate_project.py --only-tests   # Pytest만 실행
  poetry run python validate_project.py --cov          # Pytest + 커버리지만 실행

참고:
  --only-* 옵션들은 상호 배타적입니다. 하나만 선택할 수 있습니다.
  --cov 옵션은 단독으로 사용하거나 --only-tests와 함께 사용할 수 있습니다.
        """,
    )

    only_group = parser.add_mutually_exclusive_group()
    only_group.add_argument(
        "--only-lint",
        action="store_true",
        help="Ruff 린트 체크만 실행",
    )
    only_group.add_argument(
        "--only-pyright",
        action="store_true",
        help="PyRight 타입 체크만 실행",
    )
    only_group.add_argument(
        "--only-tests",
        action="store_true",
        help="Pytest 테스트만 실행",
    )

    parser.add_argument(
        "--cov",
        action="store_true",
        help="커버리지 포함 테스트만 실행 (단독 사용 시 Ruff, PyRight 제외)",
    )

    return parser.parse_args()


def main() -> int:
    """
    메인 함수: 옵션에 따라 Ruff, PyRight, Pytest를 실행하고 결과를 집계합니다.

    Returns:
        int: 종료 코드 (0=성공, 1=실패)
    """
    args = parse_args()

    # --cov 옵션 검증
    if args.cov and (args.only_lint or args.only_pyright):
        print("오류: --cov 옵션은 --only-lint, --only-pyright와 함께 사용할 수 없습니다.")
        return 1

    # 실행할 도구 결정
    if args.cov:
        # --cov 옵션: 테스트 + 커버리지만 실행
        should_run_lint = False
        should_run_pyright = False
        should_run_tests = True
    else:
        # 전체 실행인지 개별 도구 실행인지 판단
        is_only_mode = args.only_lint or args.only_pyright or args.only_tests

        should_run_lint = args.only_lint or not is_only_mode
        should_run_pyright = args.only_pyright or not is_only_mode
        should_run_tests = args.only_tests or not is_only_mode

    # 타이틀 생성
    tools = []
    if should_run_lint:
        tools.append("Ruff")
    if should_run_pyright:
        tools.append("PyRight")
    if should_run_tests:
        tools.append("Pytest")
    title = f"프로젝트 품질 검증 ({' + '.join(tools)})"

    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

    # 결과 수집: (도구 이름, 성공 여부, 덧붙일 설명)
    results: list[tuple[str, bool, str]] = []
    section_num = 1

    # 1. Ruff 실행
    if should_run_lint:
        print_section(f"{section_num}. Ruff 린트 체크")
        section_num += 1
        results.append(("Ruff", run_ruff(), ""))

    # 2. PyRight 실행
    if should_run_pyright:
        print_section(f"{section_num}. PyRight 타입 체크")
        section_num += 1
        results.append(("PyRight", run_pyright(), ""))

    # 3. Pytest 실행
    if should_run_tests:
        print_section(f"{section_num}. Pytest 테스트")
        section_num += 1
        pytest_success, pytest_detail = run_pytest(with_coverage=args.cov)
        results.append(("Pytest", pytest_success, pytest_detail))

    # 최종 결과 요약
    print_section("최종 결과")

    for name, success, detail in results:
        status = "[OK] 통과" if success else "[FAIL] 실패"
        print(f"{name + ':':8} {status}{f' ({detail})' if detail else ''}")

    if all(success for _, success, _ in results):
        print("\n[SUCCESS] 모든 품질 검증 통과!")
        return 0
    else:
        print("\n[FAILED] 품질 검증 실패. 위 오류를 수정해주세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
