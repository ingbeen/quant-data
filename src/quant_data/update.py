"""갱신 — 받기 → 판정 → 가공 → (전부 성공했을 때만) 쓰기 → 판 요약

판정 원칙: 「수정주가가 배당으로 바뀌는 것 말고는 데이터가 바뀌면 오류다. 정상이면 최신 데이터만 추가된다」.
받을 자료를 끝까지 받아 판정하고, 비정상(판정 규칙 ①)이나 새로 붙는 날 실패(판정 규칙 ②)가 하나라도 있으면 한 번에
보이고 아무 파일도 쓰지 않는다. 받기 · 가공의 예외는 그 자리에서 올라가고 역시 쓰지 않는다(결정 Q17).
비정상은 사람이 --exclude(옛 값 · 옛 끝날 그대로) 또는 --accept(이번 응답으로 덮어씀)로 정하고(결정 Q16),
새로 붙는 날 실패는 패스 목록(국내 공식 등락률은 국내 분할 기록도)으로만 넘긴다. 고정 자료는 받지 않는다(결정 Q20).
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quant_data.catalog import Dataset, Kind, Method
from quant_data.constants import COL_DATE, EDITION_PATH, PASS_LIST_PATH, REQUIRED_COLUMNS, ROUND_INPUT_PRICE
from quant_data.edition import (
    KEY_FILES,
    KEY_FIRST_DAY,
    KEY_FIRST_DIVIDEND,
    KEY_LAST_DAY,
    KEY_ROWS,
    KEY_STATUS,
    KEY_TICKER,
    STATUS_ACCEPTED,
    STATUS_EXCLUDED,
    STATUS_EXPLAINED,
    STATUS_FIXED,
    STATUS_NEW,
    STATUS_NOISE,
    STATUS_NOT_FETCHED,
    STATUS_PRODUCT,
    read_edition,
    write_edition,
)
from quant_data.leveraged.monthly_data import judge_monthly_append, load_monthly_data, save_monthly_data
from quant_data.logger import get_logger
from quant_data.new_days import (
    NewDayFailure,
    appended_days,
    check_daily_move,
    check_pair,
    load_pass_list,
    remaining_failures,
)
from quant_data.prices import (
    PriceBasis,
    load_prices,
    parse_price_file_name,
    round_prices,
    save_prices,
    validate_price_series,
)
from quant_data.revision import PriceRevision, RevisionKind, format_abnormal_block, judge_revision
from quant_data.sources.yahoo import YahooResponse

logger = get_logger(__name__)

_YAHOO_KINDS = (Kind.YAHOO_FUND, Kind.YAHOO_INDEX)
_FETCHABLE_KINDS = (*_YAHOO_KINDS, Kind.FRED_MONTHLY)
_STATUS_BY_KIND = {
    RevisionKind.NEW: STATUS_NEW,
    RevisionKind.NOISE: STATUS_NOISE,
    RevisionKind.EXPLAINED: STATUS_EXPLAINED,
}
_TABLE_ENCODING = "utf-8-sig"  # 검증 표는 한글 머리 — Excel 이 BOM 없는 UTF-8 을 깨뜨려 읽는다


@dataclass(frozen=True)
class Fetchers:
    """받기 함수 — 받는 방식(Kind)마다 하나. 파일은 쓰지 않는다."""

    yahoo: Callable[[str], YahooResponse]
    ffr_monthly: Callable[[], pd.DataFrame]


@dataclass(frozen=True)
class Products:
    """가공 결과 — 저장소 루트 기준 경로 → 표. prices 는 시세(6자리 반올림 · 검사 뒤 저장), tables 는 반올림을 마친 검증 표."""

    prices: Mapping[Path, pd.DataFrame]
    tables: Mapping[Path, pd.DataFrame]


@dataclass(frozen=True)
class Abnormal:
    """판정 규칙 ① 의 비정상 파일 하나 — revision 은 시세 판정이면 원인 블록에 쓰는 판정, 월별 판정이면 None."""

    name: str
    path: Path
    issues: tuple[str, ...]
    revision: PriceRevision | None


@dataclass(frozen=True)
class UpdateResult:
    """갱신 결과 — stopped 면 written 이 비어 있다(아무 파일도 쓰지 않음)."""

    stopped: bool
    abnormal: tuple[Abnormal, ...]
    new_day_failures: tuple[NewDayFailure, ...]
    excluded: tuple[str, ...]
    accepted: tuple[str, ...]
    written: tuple[Path, ...]


@dataclass(frozen=True)
class _FileOutcome:
    """받은 파일 하나의 판정 — table 은 이 판정대로 쓸 표(비정상이면 --accept 했을 때 쓸 응답)."""

    path: Path
    existing: pd.DataFrame | None
    table: pd.DataFrame
    status: str
    abnormal: Abnormal | None
    first_dividend: date | None


@dataclass(frozen=True)
class _DatasetOutcome:
    dataset: Dataset
    files: tuple[_FileOutcome, ...]

    @property
    def abnormal(self) -> bool:
        return any(file.abnormal is not None for file in self.files)


def run_update(
    catalog: Sequence[Dataset],
    fetchers: Fetchers,
    *,
    root: Path,
    cutoff_date: date,
    exclude: Collection[str],
    accept: Collection[str],
    build_products: Callable[[Mapping[Path, pd.DataFrame]], Products],
    fetch: bool = True,
) -> UpdateResult:
    """
    갱신 한 번.

    Args:
        catalog: 자료별 갱신 방식 표
        fetchers: 받기 함수
        root: 저장소 루트 — 표의 상대 경로를 이 아래에서 읽고 쓴다
        cutoff_date: 받을 마지막 날 (기존 끝날이 더 뒤면 기존 끝날까지 견준다 — 기존 행은 판정 없이 지우지 않는다)
        exclude: 받지 않고 옛 값 · 옛 끝날 그대로 둘 자료 이름 (사람이 정한다)
        accept: 비정상이어도 이번 응답으로 덮어쓸 자료 이름 (사람이 정한다)
        build_products: 이번에 쓸 표(경로 → 표)를 받아 가공 결과를 돌려준다 — 쓰지 않은 파일은 스스로 읽는다
        fetch: False 면 아무것도 받지 않고 지금 파일로 가공 · 판 요약만 한다 (첫 판 · 가공 코드를 고친 뒤)

    Returns:
        UpdateResult

    Raises:
        ValueError: 표 밖 · 고정 자료 이름, 두 옵션에 같은 이름, fetch=False 에 옵션, 받는 함수가 없는 종류가 고정이 아님,
            짝이 표에 없음, 고정 자료 파일이 없음 — 모두 받기 전에
        FileNotFoundError: 패스 목록이 없을 때
    """
    by_name = {dataset.name: dataset for dataset in catalog}
    _check_catalog(catalog, by_name)
    _check_options(by_name, exclude, accept, fetch)
    _require_fixed_files(root, catalog)
    pass_list = load_pass_list(root / PASS_LIST_PATH)
    previous = read_edition(root / EDITION_PATH)

    outcomes: dict[str, _DatasetOutcome] = {}
    if fetch:
        for dataset in catalog:
            if dataset.method is Method.FIXED or dataset.name in exclude:
                continue
            outcomes[dataset.name] = _fetch_and_judge(dataset, fetchers, root, cutoff_date, dataset.name in accept)

    excluded = tuple(name for name in by_name if name in exclude)
    accepted = tuple(name for name in by_name if name in accept)
    abnormal = tuple(file.abnormal for o in outcomes.values() for file in o.files if file.abnormal is not None)
    failures = tuple(remaining_failures(_new_day_failures(by_name, outcomes, root), pass_list))
    if abnormal or failures:
        logger.warning(f"멈춤 — 비정상 {len(abnormal)}건 · 새로 붙는 날 실패 {len(failures)}건, 아무 파일도 쓰지 않았습니다")
        return UpdateResult(True, abnormal, failures, excluded, accepted, ())

    updated = {file.path: file.table for outcome in outcomes.values() for file in outcome.files}
    products = build_products(updated)
    _validate_before_write(outcomes, products)
    entries = _edition_entries(root, catalog, outcomes, products, previous, exclude)
    written = _write(root, outcomes, products)
    write_edition(root / EDITION_PATH, cutoff_date, entries)
    return UpdateResult(False, (), (), excluded, accepted, (*written, EDITION_PATH))


def _check_catalog(catalog: Sequence[Dataset], by_name: Mapping[str, Dataset]) -> None:
    if len(by_name) != len(catalog):
        raise ValueError("자료별 갱신 방식 표에 같은 이름이 두 번 있습니다")
    for dataset in catalog:
        if dataset.method is not Method.FIXED and dataset.kind not in _FETCHABLE_KINDS:
            raise ValueError(f"{dataset.name}: 「{dataset.kind.value}」 는 받는 함수가 없어 고정으로만 둘 수 있습니다")
        if dataset.pair is not None and dataset.pair not in by_name:
            raise ValueError(f"{dataset.name} 의 짝 {dataset.pair} 가 자료별 갱신 방식 표에 없습니다")


def _check_options(by_name: Mapping[str, Dataset], exclude: Collection[str], accept: Collection[str], fetch: bool) -> None:
    if not fetch and (exclude or accept):
        raise ValueError("받지 않는 갱신(--no-fetch)에는 --exclude · --accept 를 쓸 수 없습니다 — 판정할 응답이 없습니다")
    both = sorted(set(exclude) & set(accept))
    if both:
        raise ValueError(f"--exclude 와 --accept 에 같은 이름이 있습니다: {both} — 하나만 정하세요")
    for option, names in (("--exclude", exclude), ("--accept", accept)):
        unknown = sorted(name for name in names if name not in by_name)
        if unknown:
            raise ValueError(f"{option} 의 {unknown} 가 자료별 갱신 방식 표에 없습니다 — 이름을 확인하세요")
        fixed = sorted(name for name in names if by_name[name].method is Method.FIXED)
        if fixed:
            raise ValueError(f"{option} 의 {fixed} 는 고정 자료라 받지 않습니다 — 고정 자료에는 쓸 수 없습니다")


def _require_fixed_files(root: Path, catalog: Sequence[Dataset]) -> None:
    missing = [
        path.as_posix()
        for dataset in catalog
        if dataset.method is Method.FIXED
        for path in dataset.files
        if not (root / path).exists()
    ]
    if missing:
        raise ValueError(f"고정 자료 파일이 없습니다: {missing} — 다시 받지 않는 자료라 git 이력에서 되살리세요")


def _fetch_and_judge(
    dataset: Dataset, fetchers: Fetchers, root: Path, cutoff_date: date, accepted: bool
) -> _DatasetOutcome:
    if dataset.kind in _YAHOO_KINDS:
        response = fetchers.yahoo(dataset.name)
        files = tuple(_judge_price_file(dataset, path, response, root, cutoff_date, accepted) for path in dataset.files)
    elif dataset.kind is Kind.FRED_MONTHLY:
        monthly = fetchers.ffr_monthly()
        files = tuple(_judge_monthly_file(dataset, path, monthly, root, accepted) for path in dataset.files)
    else:
        raise RuntimeError(f"내부 불변조건 위반: 받는 함수가 없는 종류 {dataset.kind} 가 받기까지 왔습니다 ({dataset.name})")
    return _DatasetOutcome(dataset, files)


def _judge_price_file(
    dataset: Dataset, path: Path, response: YahooResponse, root: Path, cutoff_date: date, accepted: bool
) -> _FileOutcome:
    _, basis = parse_price_file_name(path.name)
    if basis is PriceBasis.SYNTHETIC:
        raise RuntimeError(f"내부 불변조건 위반: 받는 자료 {dataset.name} 의 파일에 합성 파일 {path} 가 있습니다")
    source = response.raw if basis is PriceBasis.RAW else response.adjusted
    existing = load_prices(root / path) if (root / path).exists() else None
    last_day = cutoff_date if existing is None else max(cutoff_date, existing[COL_DATE].iloc[-1])
    cut = source[source[COL_DATE] <= last_day].reset_index(drop=True)
    revision = judge_revision(
        existing,
        cut,
        response.events,
        price_decimals=ROUND_INPUT_PRICE,
        explain_dividends=basis is PriceBasis.ADJUSTED,
    )
    dividends = response.events.dividends
    first_dividend: date | None = min(dividends.index) if len(dividends) else None
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, revision, accepted)
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.prices):,}행)")
    return _FileOutcome(path, existing, round_prices(revision.prices), status, abnormal, first_dividend)


def _judge_monthly_file(
    dataset: Dataset, path: Path, response: pd.DataFrame, root: Path, accepted: bool
) -> _FileOutcome:
    existing = load_monthly_data(root / path) if (root / path).exists() else None
    revision = judge_monthly_append(existing, response)
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, None, accepted)
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.values):,}개월)")
    return _FileOutcome(path, existing, revision.values, status, abnormal, None)


def _status(
    name: str,
    path: Path,
    kind: RevisionKind,
    issues: tuple[str, ...],
    revision: PriceRevision | None,
    accepted: bool,
) -> tuple[str, Abnormal | None]:
    if kind is not RevisionKind.ABNORMAL:
        return _STATUS_BY_KIND[kind], None
    if accepted:
        logger.warning(f"{name} {path.name}: 비정상이지만 --accept 로 이번 응답을 씁니다")
        return STATUS_ACCEPTED, None
    return "", Abnormal(name, path, issues, revision)


def _new_day_failures(
    by_name: Mapping[str, Dataset], outcomes: Mapping[str, _DatasetOutcome], root: Path
) -> list[NewDayFailure]:
    """판정 규칙 ② — 비정상(받아들이지 않음)인 자료는 판정 규칙 ① 만 보인다."""
    failures: list[NewDayFailure] = []
    for name, outcome in outcomes.items():
        dataset = outcome.dataset
        if outcome.abnormal or dataset.kind not in _YAHOO_KINDS:
            continue
        target = _check_target(outcome)
        days = appended_days(target.existing, target.table)
        if not days:
            continue
        if dataset.pair is not None:
            pair = _pair_table(by_name[dataset.pair], outcomes, root)
            failures += check_pair(
                target.table, pair, ticker=name, pair_name=dataset.pair, leverage=dataset.leverage, days=days
            )
        if dataset.daily_move_limit is not None:
            failures += check_daily_move(target.table, ticker=name, days=days, limit=dataset.daily_move_limit)
    return failures


def _check_target(outcome: _DatasetOutcome) -> _FileOutcome:
    """새로 붙는 날 검사의 대상 — 수정주가 파일이 있으면 그것(배당이 든 수익률), 없으면 원본가(지수)."""
    by_basis = {parse_price_file_name(file.path.name)[1]: file for file in outcome.files}
    return by_basis.get(PriceBasis.ADJUSTED) or by_basis[PriceBasis.RAW]


def _pair_table(pair: Dataset, outcomes: Mapping[str, _DatasetOutcome], root: Path) -> pd.DataFrame:
    """짝의 이번 표 — 받아 판정이 정상이면 그 표, 아니면 지금 파일, 파일도 없으면 빈 표(모든 날이 「짝 없음」)."""
    outcome = outcomes.get(pair.name)
    if outcome is not None and not outcome.abnormal:
        return _check_target(outcome).table
    path = root / pair.files[0]
    return load_prices(path) if path.exists() else pd.DataFrame(columns=REQUIRED_COLUMNS)


def _validate_before_write(outcomes: Mapping[str, _DatasetOutcome], products: Products) -> None:
    """쓸 시세를 모두 먼저 검사한다 — 쓰는 도중에 걸려 일부 파일만 바뀐 판이 남지 않게."""
    for outcome in outcomes.values():
        if outcome.dataset.kind in _YAHOO_KINDS:
            for file in outcome.files:
                validate_price_series(file.table)
    for table in products.prices.values():
        validate_price_series(round_prices(table))


def _write(root: Path, outcomes: Mapping[str, _DatasetOutcome], products: Products) -> list[Path]:
    written: list[Path] = []
    for outcome in outcomes.values():
        for file in outcome.files:
            if outcome.dataset.kind in _YAHOO_KINDS:
                save_prices(file.table, root / file.path)
            else:
                save_monthly_data(file.table, root / file.path)
            written.append(file.path)
    for path, table in products.prices.items():
        save_prices(table, root / path)
        written.append(path)
    for path, table in products.tables.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(root / path, index=False, encoding=_TABLE_ENCODING)
        written.append(path)
    return written


def _edition_entries(
    root: Path,
    catalog: Sequence[Dataset],
    outcomes: Mapping[str, _DatasetOutcome],
    products: Products,
    previous: Mapping[str, object] | None,
    exclude: Collection[str],
) -> dict[Path, dict[str, object]]:
    """판 요약의 파일 항목 — 표 순서, 그다음 가공 시세. 받지 않은 파일은 지금 파일로 기간을 잰다."""
    previous_files = previous.get(KEY_FILES, {}) if previous is not None else {}
    entries: dict[Path, dict[str, object]] = {}
    for dataset in catalog:
        outcome = outcomes.get(dataset.name)
        fetched = {file.path: file for file in outcome.files} if outcome is not None else {}
        for path in dataset.files:
            file = fetched.get(path)
            if file is not None:
                entry = _period_entry(dataset.name, file.table, file.status)
                first_dividend = file.first_dividend.isoformat() if file.first_dividend is not None else None
            else:
                if not (root / path).exists():
                    continue
                entry = _period_entry(dataset.name, _read_for_period(dataset, root / path), _idle_status(dataset, exclude))
                carried = previous_files.get(path.as_posix(), {}) if isinstance(previous_files, dict) else {}
                first_dividend = carried.get(KEY_FIRST_DIVIDEND) if isinstance(carried, dict) else None
            if dataset.kind in _YAHOO_KINDS:
                entry[KEY_FIRST_DIVIDEND] = first_dividend
            entries[path] = entry
    for path, table in products.prices.items():
        ticker, _ = parse_price_file_name(path.name)
        entries[path] = _period_entry(ticker, table, STATUS_PRODUCT)
    return entries


def _idle_status(dataset: Dataset, exclude: Collection[str]) -> str:
    if dataset.method is Method.FIXED:
        return STATUS_FIXED
    return STATUS_EXCLUDED if dataset.name in exclude else STATUS_NOT_FETCHED


def _read_for_period(dataset: Dataset, path: Path) -> pd.DataFrame:
    if dataset.kind in _YAHOO_KINDS:
        return load_prices(path)
    return pd.read_csv(path, dtype=str)


def _period_entry(ticker: str, table: pd.DataFrame, status: str) -> dict[str, object]:
    """종목 · 첫날 · 끝날 · 행 수 · 상태 — 날짜는 첫 열(시세의 Date · 계열의 DATE)."""
    first_column = table.columns[0]
    return {
        KEY_TICKER: ticker,
        KEY_FIRST_DAY: _day_text(table[first_column].iloc[0]),
        KEY_LAST_DAY: _day_text(table[first_column].iloc[-1]),
        KEY_ROWS: len(table),
        KEY_STATUS: status,
    }


def _day_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise RuntimeError(f"내부 불변조건 위반: 날짜 열 값이 date · 문자열이 아닙니다: {value!r}")


def format_stop_report(result: UpdateResult, *, run_at: datetime, cutoff_date: date, yfinance_version: str) -> str:
    """
    멈춘 갱신의 원인 — 사용자가 그대로 AI 에 붙여 판단을 받는다. 시세 비정상은 원인 블록(--accept · --exclude 안내),
    월별 비정상은 원인 줄, 새로 붙는 날 실패는 패스 목록에 적을 줄의 앞 세 칸과 함께 낸다.
    """
    sections: list[str] = []
    price_entries = [(a.name, a.path, a.revision) for a in result.abnormal if a.revision is not None]
    if price_entries:
        sections.append(
            format_abnormal_block(
                price_entries, run_at=run_at, cutoff_date=cutoff_date, yfinance_version=yfinance_version
            )
        )
    others = [a for a in result.abnormal if a.revision is None]
    if others:
        lines = ["[갱신 비정상 판정 — 시세가 아닌 자료]"]
        for item in others:
            lines.append(f"{item.name} — {item.path}")
            lines += [f"  - {issue}" for issue in item.issues]
            lines.append(f"  --accept {item.name} = 응답으로 덮어씀 · --exclude {item.name} = 기존 파일 그대로")
        sections.append("\n".join(lines))
    if result.new_day_failures:
        lines = [
            "[새로 붙는 날 검사 실패 — 실제 대폭락 · 대폭등이면 패스 목록에 근거와 함께 적고 다시 실행하세요]",
            f"패스 목록: {PASS_LIST_PATH} — 한 줄에 종목,날짜,검사,사유,근거 (근거 없이 적지 않습니다)",
        ]
        lines += [
            f"  - {failure.ticker},{failure.day},{failure.check.value} — {failure.detail}"
            for failure in result.new_day_failures
        ]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
