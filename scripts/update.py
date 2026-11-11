"""
갱신 — 받기 → 판정 → 가공(합성 · 검증 표) → (전부 성공했을 때만) 쓰기 → 판 요약

자료별 갱신 방식 표(src/quant_data/catalog.py)대로 다시 받음 · 덧붙이기 자료를 받고, 고정 자료는 받지 않는다.
비정상이나 새로 붙는 날 실패가 하나라도 있으면 원인을 한 번에 내고 아무 파일도 쓰지 않은 채 종료 코드 1 로 끝난다 —
사람이 확인한 뒤 --exclude · --accept 를 정하거나 패스 목록에 적고 다시 실행한다.

실행 명령은 docs/COMMANDS.md 가 정본이다.
"""

import argparse
import sys
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path

from quant_data.catalog import CATALOG
from quant_data.cli import cli_exception_handler
from quant_data.constants import EDITION_PATH
from quant_data.edition import KEY_CUTOFF, read_edition
from quant_data.leveraged.monthly_data import fetch_ffr_monthly
from quant_data.logger import get_logger
from quant_data.products import build_products
from quant_data.sources.bitstamp import fetch_bitstamp_history
from quant_data.sources.coinmetrics import fetch_coinmetrics_series
from quant_data.sources.krx import fetch_krx_etf, fetch_krx_index, fetch_krx_nav
from quant_data.sources.yahoo import YFINANCE_VERSION, fetch_yahoo, resolve_cutoff_date
from quant_data.update import Fetchers, format_stop_report, run_update

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="자료별 갱신 방식 표대로 받고 판정해, 모두 정상일 때만 쓴다")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="이름",
        help="받지 않고 옛 값 · 옛 끝날 그대로 둘 자료 (여러 번 줄 수 있다 — 사람이 정한다)",
    )
    parser.add_argument(
        "--accept",
        action="append",
        default=[],
        metavar="이름",
        help="비정상이어도 이번 응답으로 덮어쓸 자료 (여러 번 줄 수 있다 — 사람이 정한다)",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=None,
        help="받을 마지막 날 YYYY-MM-DD (그날 포함, 오늘까지). 뉴욕에서 그날 봉이 끝나기 전인 날은 빠진다. 미지정 시 그저께",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="받지 않고 지금 파일로 가공 · 판 요약만 한다 (기준일은 판 요약의 것, 판 요약이 없으면 --end)",
    )
    return parser.parse_args()


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"날짜는 YYYY-MM-DD 로 주세요: {text!r}") from None


def _cutoff_without_fetch(root: Path, end: date | None) -> date:
    """받지 않는 갱신의 기준일 — 판 요약의 기준일을 그대로 쓴다. 판 요약이 없을 때(첫 판)만 --end 로 정한다."""
    previous = read_edition(root / EDITION_PATH)
    if previous is None:
        if end is None:
            raise ValueError("판 요약이 없는 첫 판은 --end 로 기준일(지금 파일의 끝날)을 주세요")
        return end
    if end is not None:
        raise ValueError("받지 않는 갱신은 기준일을 바꾸지 않습니다 — --end 를 빼고 실행하세요")
    return date.fromisoformat(previous[KEY_CUTOFF])


@cli_exception_handler
def main() -> int:
    """
    Returns:
        종료 코드 (0: 썼음, 1: 멈춤 · 실패 — 아무 파일도 쓰지 않음)
    """
    args = parse_args()
    root = Path.cwd()
    now = datetime.now().astimezone()
    fetch = not args.no_fetch
    cutoff_date = resolve_cutoff_date(args.end, now) if fetch else _cutoff_without_fetch(root, args.end)
    logger.debug(f"기준일 {cutoff_date} · 받기 {'함' if fetch else '안 함'}")

    # 비트코인 받기의 「지금」은 받기 직전에 잰다 — 받은 뒤에 재면 UTC 하루가 바뀌는 순간 진행 중이던 날이 끝난 날로 남는다
    fetchers = Fetchers(
        yahoo=fetch_yahoo,
        ffr_monthly=fetch_ffr_monthly,
        krx_etf=fetch_krx_etf,
        krx_index=fetch_krx_index,
        krx_nav=fetch_krx_nav,
        bitstamp=lambda: fetch_bitstamp_history(datetime.now(UTC)),
        coinmetrics=lambda metric: fetch_coinmetrics_series(metric, datetime.now(UTC)),
    )
    result = run_update(
        CATALOG,
        fetchers,
        root=root,
        cutoff_date=cutoff_date,
        exclude=frozenset(args.exclude),
        accept=frozenset(args.accept),
        build_products=partial(build_products, root),
        fetch=fetch,
    )
    if result.stopped:
        report = format_stop_report(result, run_at=now, cutoff_date=cutoff_date, yfinance_version=YFINANCE_VERSION)
        logger.warning(f"멈춤 — 원인:\n{report}")
        logger.error("아무 파일도 쓰지 않았습니다 — 위 원인을 확인하고 --exclude · --accept 를 정하거나 패스 목록에 적은 뒤 다시 실행하세요")
        return 1

    logger.debug(f"썼음: {len(result.written)}개 파일 (판 요약 {EDITION_PATH})")
    if result.excluded:
        logger.warning(f"제외한 자료(옛 값 · 옛 끝날 그대로): {list(result.excluded)} — 판 요약에 「제외」로 적었습니다")
    if result.accepted:
        logger.warning(f"받아들인 자료(이번 응답으로 덮어씀): {list(result.accepted)} — 판 요약에 「받아들임」으로 적었습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
