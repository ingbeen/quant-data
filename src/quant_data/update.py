"""갱신 — 받기 → 판정 → 가공 → (전부 성공했을 때만) 쓰기 → 매니페스트

판정 원칙: 「수정주가가 배당으로 바뀌는 것 말고는 데이터가 바뀌면 오류다. 정상이면 최신 데이터만 추가된다」.
받을 자료를 끝까지 받아 판정하고, 비정상(판정 규칙 ①)이나 신규 일자 실패(판정 규칙 ②)가 하나라도 있으면 한 번에
보이고 아무 파일도 쓰지 않는다. 받기 · 가공의 예외는 그 자리에서 올라가고 역시 쓰지 않는다(결정 Q17).
비정상은 사람이 --exclude(옛 값 · 옛 끝날 그대로) 또는 --accept(이번 응답으로 덮어씀)로 정하고(결정 Q16),
신규 일자 실패는 허용 목록으로만 넘긴다. 고정 자료는 받지 않는다(결정 Q20) — 매니페스트에 오른 적 없는 고정 자료만
파일이 없을 때 한 번 받는다(최초 수집, 사용자 결정 2026-11-11).
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.catalog import Dataset, Kind, Method
from quant_data.constants import ALLOWLIST_PATH, COL_CLOSE, COL_DATE, MANIFEST_PATH, REQUIRED_COLUMNS, ROUND_INPUT_PRICE
from quant_data.leveraged.monthly_data import judge_monthly_append, load_monthly_data, save_monthly_data
from quant_data.logger import get_logger
from quant_data.manifest import (
    KEY_DISTRIBUTION_CHECK,
    KEY_FILES,
    KEY_FIRST_DAY,
    KEY_FIRST_DIVIDEND,
    KEY_LAST_DAY,
    KEY_ROWS,
    KEY_STATUS,
    KEY_TICKER,
    STATUS_ACCEPTED,
    STATUS_DIVIDEND_ADJUSTED,
    STATUS_EXCLUDED,
    STATUS_FIXED,
    STATUS_NEW,
    STATUS_NOISE,
    STATUS_NOT_FETCHED,
    STATUS_PRODUCT,
    read_manifest,
    write_manifest,
)
from quant_data.new_days import (
    NewDayFailure,
    appended_days,
    check_coin_cross,
    check_kr_base_rate,
    check_kr_cross,
    check_tracking_difference,
    load_allowlist,
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
from quant_data.revision import PriceEvents, PriceRevision, RevisionKind, format_abnormal_block, judge_revision
from quant_data.series import SERIES_COLUMNS, judge_series_append, load_series, save_series, validate_series
from quant_data.sources.yahoo import YahooResponse

logger = get_logger(__name__)

_YAHOO_KINDS: Final = (Kind.YAHOO_FUND, Kind.YAHOO_INDEX)
_FETCHABLE_KINDS: Final = (
    *_YAHOO_KINDS,
    Kind.FRED_MONTHLY,
    Kind.KRX_ETF,
    Kind.KRX_INDEX,
    Kind.KRX_NAV,
    Kind.BITSTAMP,
    Kind.COINMETRICS,
)
# KRX 자료는 다시 받을 때의 판정이 없다 — 최초 수집만 하는 고정이어야 한다(국내 합성 2단계에서 판정과 함께 바꾼다)
_FIXED_ONLY_KINDS: Final = (Kind.KRX_ETF, Kind.KRX_INDEX, Kind.KRX_NAV)
_YAHOO_KR_SUFFIX: Final = ".KS"  # 국내 ETF 의 야후 티커 — 9종 모두 유가증권시장 상장
_STATUS_BY_KIND = {
    RevisionKind.NEW: STATUS_NEW,
    RevisionKind.NOISE: STATUS_NOISE,
    RevisionKind.DIVIDEND_ADJUSTED: STATUS_DIVIDEND_ADJUSTED,
}
_TABLE_ENCODING = "utf-8-sig"  # 검증 표는 한글 헤더 — Excel 이 BOM 없는 UTF-8 을 깨뜨려 읽는다


class _Form(Enum):
    """파일 모양 — 읽기 · 검사 · 쓰기 함수를 고른다."""

    PRICES = "시세"
    SERIES = "일별 시계열"
    MONTHLY = "월별"
    OTHER = "그 밖(읽기만)"


@dataclass(frozen=True)
class Fetchers:
    """받기 함수 — 받는 방식(Kind)마다 하나. 파일은 쓰지 않는다."""

    yahoo: Callable[[str], YahooResponse]
    ffr_monthly: Callable[[], pd.DataFrame]
    krx_etf: Callable[[str], pd.DataFrame]
    krx_index: Callable[[str], pd.DataFrame]
    krx_nav: Callable[[str], pd.DataFrame]
    bitstamp: Callable[[], pd.DataFrame]
    coinmetrics: Callable[[str], pd.DataFrame]


@dataclass(frozen=True)
class Products:
    """가공 결과 — 저장소 루트 기준 경로 → 표. prices 는 시세(6자리 반올림 · 검사 뒤 저장), tables 는 반올림을 마친 검증 표,
    notes 는 가공 시세에 붙는 대조 어긋남(국내 수정주가의 야후 분배 대조 — 매니페스트에 적는다)."""

    prices: Mapping[Path, pd.DataFrame]
    tables: Mapping[Path, pd.DataFrame]
    notes: Mapping[Path, tuple[str, ...]] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class Abnormal:
    """판정 규칙 ① 의 비정상 파일 하나 — revision 은 시세 판정이면 진단 출력에 쓰는 판정, 계열 · 월별 판정이면 None."""

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
    form: _Form
    existing: pd.DataFrame | None
    table: pd.DataFrame
    status: str
    abnormal: Abnormal | None
    first_dividend: date | None


@dataclass(frozen=True)
class _DatasetOutcome:
    """자료 하나의 판정 — companion 은 판정 규칙 ② 에만 쓰는 받은 표(국내 ETF 의 야후 .KS 원본가)."""

    dataset: Dataset
    files: tuple[_FileOutcome, ...]
    companion: pd.DataFrame | None = None

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
        fetch: False 면 아무것도 받지 않고 지금 파일로 가공 · 매니페스트만 한다 (가공 코드를 고친 뒤)

    Returns:
        UpdateResult

    Raises:
        ValueError: 표 밖 · 고정 자료 이름, 두 옵션에 같은 이름, fetch=False 에 옵션, 받는 함수가 없는 종류 · KRX 종류가
            고정이 아님, 벤치마크가 표에 없음, 매니페스트와 표의 데이터 파일이 어긋남(매니페스트 없음 · 빠진 파일 · 목록 밖 파일 ·
            첫날 · 끝날 · 행 수), fetch=False 인데 처음 받을 고정 자료가 있음 — 모두 받기 전에
        FileNotFoundError: 허용 목록이 없을 때
    """
    by_name = {dataset.name: dataset for dataset in catalog}
    _check_catalog(catalog, by_name)
    _check_options(by_name, exclude, accept, fetch)
    previous = read_manifest(root / MANIFEST_PATH)
    _check_manifest_matches_files(root, catalog, previous)
    first_fetch = _first_fetch_names(root, catalog)
    if not fetch and first_fetch:
        raise ValueError(f"처음 받을 고정 자료가 있어 받지 않는 갱신(--no-fetch)을 할 수 없습니다: {sorted(first_fetch)}")
    allowlist = load_allowlist(root / ALLOWLIST_PATH)

    outcomes: dict[str, _DatasetOutcome] = {}
    if fetch:
        for dataset in catalog:
            if dataset.name in exclude or (dataset.method is Method.FIXED and dataset.name not in first_fetch):
                continue
            outcomes[dataset.name] = _fetch_and_judge(dataset, fetchers, root, cutoff_date, dataset.name in accept)

    excluded = tuple(name for name in by_name if name in exclude)
    # --accept 를 줬어도 비정상이 아니었으면 덮어쓰지 않았으므로 받아들인 자료가 아님
    accepted = tuple(
        name for name, outcome in outcomes.items() if any(file.status == STATUS_ACCEPTED for file in outcome.files)
    )
    abnormal = tuple(file.abnormal for o in outcomes.values() for file in o.files if file.abnormal is not None)
    failures = tuple(remaining_failures(_new_day_failures(by_name, outcomes, root), allowlist))
    if abnormal or failures:
        logger.warning(f"멈춤 — 비정상 {len(abnormal)}건 · 신규 일자 실패 {len(failures)}건, 아무 파일도 쓰지 않았습니다")
        return UpdateResult(True, abnormal, failures, excluded, accepted, ())

    updated = {file.path: file.table for outcome in outcomes.values() for file in outcome.files}
    products = build_products(updated)
    _validate_before_write(outcomes, products)
    entries = _manifest_entries(root, catalog, outcomes, products, previous, exclude)
    written = _write(root, outcomes, products)
    write_manifest(root / MANIFEST_PATH, cutoff_date, entries)
    return UpdateResult(False, (), (), excluded, accepted, (*written, MANIFEST_PATH))


def _check_catalog(catalog: Sequence[Dataset], by_name: Mapping[str, Dataset]) -> None:
    if len(by_name) != len(catalog):
        raise ValueError("자료별 갱신 방식 표에 같은 이름이 두 번 있습니다")
    for dataset in catalog:
        if dataset.method is not Method.FIXED and dataset.kind not in _FETCHABLE_KINDS:
            raise ValueError(f"{dataset.name}: 「{dataset.kind.value}」 는 받는 함수가 없어 고정으로만 둘 수 있습니다")
        if dataset.method is not Method.FIXED and dataset.kind in _FIXED_ONLY_KINDS:
            raise ValueError(f"{dataset.name}: 「{dataset.kind.value}」 는 다시 받을 때의 판정이 없어 고정(최초 수집만 함)으로만 둘 수 있습니다")
        if dataset.reference is not None and dataset.reference not in by_name:
            raise ValueError(f"{dataset.name} 의 비교 대상 {dataset.reference} 가 자료별 갱신 방식 표에 없습니다")


def _check_options(
    by_name: Mapping[str, Dataset], exclude: Collection[str], accept: Collection[str], fetch: bool
) -> None:
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


def _check_manifest_matches_files(
    root: Path, catalog: Sequence[Dataset], previous: Mapping[str, object] | None
) -> None:
    """
    매니페스트와 표의 데이터 파일이 정확히 맞는지 받기 전에 본다 — 받든 안 받든.

    갱신이 성공하면 매니페스트는 그때 쓴 파일로 만들어지므로 정상이면 늘 맞는다. 어긋남(매니페스트 없음 · 매니페스트에 있는데
    파일 없음 · 매니페스트에 없는데 파일 있음 · 첫날 · 끝날 · 행 수가 다름)은 파일이나 매니페스트만 지웠거나 이전 버전으로
    되살린 것이고, 그대로 두면 빠지거나 짧아진 파일이 판정 규칙 ① · ② 없이 「신규」 · 「최초 수집」으로 채워진다.
    표에 새로 더해 파일도 매니페스트 항목도 없는 자료는 맞는 것으로 본다(최초 수집한다).

    Raises:
        ValueError: 어긋난 파일이 있을 때
    """
    files = previous.get(KEY_FILES, {}) if previous is not None else {}
    listed = files if isinstance(files, dict) else {}
    period_keys = (KEY_FIRST_DAY, KEY_LAST_DAY, KEY_ROWS)
    problems: list[str] = []
    for dataset in catalog:
        for path in dataset.files:
            key = path.as_posix()
            exists = (root / path).exists()
            entry = listed.get(key)
            if entry is None:
                if exists:
                    problems.append(f"{key}: 매니페스트에 없는데 파일이 있음")
                continue
            if not exists:
                problems.append(f"{key}: 매니페스트에 있는데 파일이 없음")
                continue
            now = _period_entry(dataset.name, _read_for_period(dataset, root, path), "")
            recorded = tuple(entry.get(k) for k in period_keys) if isinstance(entry, dict) else None
            current = tuple(now[k] for k in period_keys)
            if recorded != current:
                problems.append(f"{key}: 매니페스트 (첫날 · 끝날 · 행 수) {recorded}, 파일 {current}")
    if problems:
        missing_manifest = f" — 매니페스트({MANIFEST_PATH})가 없습니다" if previous is None else ""
        shown = "\n".join(f"  {problem}" for problem in problems[:10])
        more = f"\n  … 그 밖 {len(problems) - 10}개" if len(problems) > 10 else ""
        raise ValueError(
            f"매니페스트와 데이터 파일이 어긋납니다{missing_manifest} — 빠지거나 짧아진 파일이 판정 없이 채워지지 않게 받기 전에 "
            f"멈춥니다. 매니페스트와 데이터 파일을 같은 커밋에서 함께 git 이력에서 되살리세요:\n{shown}{more}"
        )


def _first_fetch_names(root: Path, catalog: Sequence[Dataset]) -> set[str]:
    """
    이번에 최초 수집할 고정 자료 — 파일이 모두 없는 것. 매니페스트에 있던 파일이 없으면 _check_manifest_matches_files 가
    먼저 멈추므로, 여기 오는 것은 매니페스트에 오른 적 없는 자료다.

    Raises:
        ValueError: 일부 파일만 있을 때, 파일이 없는데 받는 함수가 없을 때
    """
    first: set[str] = set()
    partial: list[str] = []
    for dataset in catalog:
        if dataset.method is not Method.FIXED:
            continue
        missing = [path for path in dataset.files if not (root / path).exists()]
        if not missing:
            continue
        if len(missing) != len(dataset.files):
            partial.append(dataset.name)
        else:
            first.add(dataset.name)
    if partial:
        raise ValueError(f"고정 자료의 파일이 일부만 있습니다: {partial} — 매니페스트와 데이터 파일을 같은 커밋에서 함께 git 이력에서 되살리세요")
    unfetchable = sorted(name for name in first if _kind_of(catalog, name) not in _FETCHABLE_KINDS)
    if unfetchable:
        raise ValueError(f"고정 자료 파일이 없는데 받는 함수가 없습니다: {unfetchable} — git 이력에서 되살리세요")
    return first


def _kind_of(catalog: Sequence[Dataset], name: str) -> Kind:
    return next(dataset.kind for dataset in catalog if dataset.name == name)


def _fetch_and_judge(
    dataset: Dataset, fetchers: Fetchers, root: Path, cutoff_date: date, accepted: bool
) -> _DatasetOutcome:
    if dataset.kind in _YAHOO_KINDS:
        response = fetchers.yahoo(dataset.source_id)
        files = tuple(_judge_yahoo_file(dataset, path, response, root, cutoff_date, accepted) for path in dataset.files)
        return _DatasetOutcome(dataset, files)
    if dataset.kind is Kind.FRED_MONTHLY:
        monthly = fetchers.ffr_monthly()
        return _DatasetOutcome(
            dataset, tuple(_judge_monthly_file(dataset, path, monthly, root, accepted) for path in dataset.files)
        )
    if dataset.kind is Kind.KRX_ETF:
        return _fetch_kr_etf(dataset, fetchers, root, cutoff_date, accepted)
    if dataset.kind is Kind.BITSTAMP:
        table = fetchers.bitstamp()
        (path,) = dataset.files
        return _DatasetOutcome(dataset, (_judge_plain_prices(dataset, path, table, root, cutoff_date, accepted),))
    if dataset.kind in (Kind.KRX_INDEX, Kind.KRX_NAV, Kind.COINMETRICS):
        fetch_series = {
            Kind.KRX_INDEX: fetchers.krx_index,
            Kind.KRX_NAV: fetchers.krx_nav,
            Kind.COINMETRICS: fetchers.coinmetrics,
        }[dataset.kind]
        series = fetch_series(dataset.source_id)
        (path,) = dataset.files
        return _DatasetOutcome(dataset, (_judge_series_file(dataset, path, series, root, cutoff_date, accepted),))
    raise RuntimeError(f"내부 불변조건 위반: 받는 함수가 없는 종류 {dataset.kind} 가 받기까지 왔습니다 ({dataset.name})")


def _cut(table: pd.DataFrame, existing: pd.DataFrame | None, cutoff_date: date) -> pd.DataFrame:
    """받을 마지막 날까지 — 기존 끝날이 더 뒤면 기존 끝날까지(기존 행을 판정 없이 지우지 않는다)."""
    last_day = cutoff_date if existing is None or existing.empty else max(cutoff_date, existing[COL_DATE].iloc[-1])
    return table[table[COL_DATE] <= last_day].reset_index(drop=True)


def _judge_yahoo_file(
    dataset: Dataset, path: Path, response: YahooResponse, root: Path, cutoff_date: date, accepted: bool
) -> _FileOutcome:
    _, basis = parse_price_file_name(path.name)
    if basis is PriceBasis.SYNTHETIC:
        raise RuntimeError(f"내부 불변조건 위반: 받는 자료 {dataset.name} 의 파일에 합성 파일 {path} 가 있습니다")
    source = response.raw if basis is PriceBasis.RAW else response.adjusted
    existing = load_prices(root / path) if (root / path).exists() else None
    revision = judge_revision(
        existing,
        _cut(source, existing, cutoff_date),
        response.events,
        price_decimals=ROUND_INPUT_PRICE,
        explain_dividends=basis is PriceBasis.ADJUSTED,
    )
    dividends = response.events.dividends
    first_dividend: date | None = min(dividends.index) if len(dividends) else None
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, revision, accepted)
    # 야후가 틀린 배당을 넣어도 대조할 외부 출처가 없음 → 덮어쓴 까닭을 사람이 볼 곳은 이 줄뿐.
    # 덮어쓰는 판정(배당 반영 · --accept 로 받아들인 비정상)에만 붙임 — 멈춘 비정상은 아무것도 덮어쓰지 않음
    overwrites = revision.kind is RevisionKind.DIVIDEND_ADJUSTED or status == STATUS_ACCEPTED
    matched = revision.applied if overwrites else ()
    records = f" — 맞춘 기록: {' / '.join(matched)}" if matched else ""
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.prices):,}행){records}")
    return _FileOutcome(path, _Form.PRICES, existing, round_prices(revision.prices), status, abnormal, first_dividend)


def _judge_plain_prices(
    dataset: Dataset, path: Path, table: pd.DataFrame, root: Path, cutoff_date: date, accepted: bool
) -> _FileOutcome:
    """배당 · 분할 기록이 없는 시세(KRX 원본가 · Bitstamp) — 과거가 노이즈 밖으로 바뀌면 모두 비정상이다."""
    existing = load_prices(root / path) if (root / path).exists() else None
    cut = _cut(table, existing, cutoff_date)
    no_events = PriceEvents(
        dividends=pd.Series(dtype=float),
        splits=pd.Series(dtype=float),
        raw_close=pd.Series(cut[COL_CLOSE].to_numpy(dtype=float), index=list(cut[COL_DATE])),
    )
    revision = judge_revision(existing, cut, no_events, price_decimals=ROUND_INPUT_PRICE, explain_dividends=False)
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, revision, accepted)
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.prices):,}행)")
    return _FileOutcome(path, _Form.PRICES, existing, round_prices(revision.prices), status, abnormal, None)


def _judge_series_file(
    dataset: Dataset, path: Path, series: pd.DataFrame, root: Path, cutoff_date: date, accepted: bool
) -> _FileOutcome:
    existing = load_series(root / path) if (root / path).exists() else None
    revision = judge_series_append(existing, _cut(series, existing, cutoff_date), decimals=dataset.decimals)
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, None, accepted)
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.values):,}행)")
    return _FileOutcome(path, _Form.SERIES, existing, revision.values, status, abnormal, None)


def _judge_monthly_file(
    dataset: Dataset, path: Path, response: pd.DataFrame, root: Path, accepted: bool
) -> _FileOutcome:
    existing = load_monthly_data(root / path) if (root / path).exists() else None
    revision = judge_monthly_append(existing, response)
    status, abnormal = _status(dataset.name, path, revision.kind, revision.issues, None, accepted)
    logger.debug(f"{dataset.name} {path.name}: {revision.kind.value} ({len(revision.values):,}개월)")
    return _FileOutcome(path, _Form.MONTHLY, existing, revision.values, status, abnormal, None)


def _fetch_kr_etf(
    dataset: Dataset, fetchers: Fetchers, root: Path, cutoff_date: date, accepted: bool
) -> _DatasetOutcome:
    """KRX 원본가와 야후 .KS(원본가 — 교차 확인, 분배 기록 — C-2 금액 · 대조)를 받는다. 고정이라 최초 수집에서만 온다."""
    raw_path, dividends_path = dataset.files
    krx = fetchers.krx_etf(dataset.source_id)
    yahoo = fetchers.yahoo(f"{dataset.source_id}{_YAHOO_KR_SUFFIX}")
    if (root / raw_path).exists():
        raise RuntimeError(f"내부 불변조건 위반: 최초 수집만 하는 국내 ETF {dataset.name} 의 원본가 파일이 이미 있습니다")
    raw_file = _judge_plain_prices(dataset, raw_path, krx, root, cutoff_date, accepted)
    dividends = yahoo.events.dividends
    dividend_series = pd.DataFrame(
        {COL_DATE: list(dividends.index), SERIES_COLUMNS[1]: dividends.to_numpy(dtype=float)}, columns=SERIES_COLUMNS
    )
    dividend_file = _judge_series_file(dataset, dividends_path, dividend_series, root, cutoff_date, accepted)
    return _DatasetOutcome(dataset, (raw_file, dividend_file), companion=yahoo.raw)


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
        if outcome.abnormal:
            continue
        if dataset.kind in _YAHOO_KINDS and dataset.reference is not None:
            target = _check_target(outcome)
            days = appended_days(target.existing, target.table)
            if days:
                benchmark = _benchmark_prices(by_name[dataset.reference], outcomes, root)
                failures += check_tracking_difference(
                    target.table,
                    benchmark,
                    ticker=name,
                    benchmark_name=dataset.reference,
                    leverage=dataset.leverage,
                    days=days,
                )
        elif dataset.kind is Kind.KRX_ETF:
            raw = outcome.files[0]
            # 새 파일은 전 기간에 건다 — 국내는 분배 · 액션을 찾아야 C-2 가 맞다(결정 Q34)
            days = list(raw.table[COL_DATE]) if raw.existing is None else appended_days(raw.existing, raw.table)
            if outcome.companion is None:
                raise RuntimeError(f"내부 불변조건 위반: 국내 ETF {name} 의 야후 원본가가 없습니다")
            failures += check_kr_cross(raw.table, outcome.companion, ticker=name, days=days)
            failures += check_kr_base_rate(raw.table, ticker=name, days=days)
        elif dataset.kind is Kind.BITSTAMP and dataset.reference is not None:
            target = outcome.files[0]
            days = appended_days(target.existing, target.table)
            if days:
                reference = _reference_series(by_name[dataset.reference], outcomes, root)
                failures += check_coin_cross(
                    target.table, reference, ticker=name, reference_name=dataset.reference, days=days
                )
    return failures


def _check_target(outcome: _DatasetOutcome) -> _FileOutcome:
    """신규 일자 검사의 대상 — 수정주가 파일이 있으면 그것(배당이 든 수익률), 없으면 원본가(지수)."""
    by_basis = {parse_price_file_name(file.path.name)[1]: file for file in outcome.files}
    return by_basis.get(PriceBasis.ADJUSTED) or by_basis[PriceBasis.RAW]


def _benchmark_prices(benchmark: Dataset, outcomes: Mapping[str, _DatasetOutcome], root: Path) -> pd.DataFrame:
    """벤치마크 시세의 이번 표 — 받아 판정이 정상이면 그 표(수정주가가 있으면 그것), 아니면 지금 파일, 없으면 빈 표(모두 「벤치마크 없음」)."""
    outcome = outcomes.get(benchmark.name)
    if outcome is not None and not outcome.abnormal:
        return _check_target(outcome).table
    by_basis = {parse_price_file_name(path.name)[1]: path for path in benchmark.files}
    path = root / (by_basis.get(PriceBasis.ADJUSTED) or by_basis[PriceBasis.RAW])
    return load_prices(path) if path.exists() else pd.DataFrame(columns=REQUIRED_COLUMNS)


def _reference_series(reference: Dataset, outcomes: Mapping[str, _DatasetOutcome], root: Path) -> pd.DataFrame:
    """비교 대상 계열의 이번 표 — 받아 판정이 정상이면 그 표, 아니면 지금 파일, 없으면 빈 표."""
    outcome = outcomes.get(reference.name)
    if outcome is not None and not outcome.abnormal:
        return outcome.files[0].table
    path = root / reference.files[0]
    return load_series(path) if path.exists() else pd.DataFrame(columns=SERIES_COLUMNS)


def _validate_before_write(outcomes: Mapping[str, _DatasetOutcome], products: Products) -> None:
    """쓸 시세 · 계열을 모두 먼저 검사한다 — 쓰는 도중에 걸려 일부 파일만 바뀐 버전이 남지 않게."""
    for outcome in outcomes.values():
        for file in outcome.files:
            if file.form is _Form.PRICES:
                validate_price_series(file.table)
            elif file.form is _Form.SERIES:
                validate_series(file.table)
    for table in products.prices.values():
        validate_price_series(round_prices(table))


def _write(root: Path, outcomes: Mapping[str, _DatasetOutcome], products: Products) -> list[Path]:
    written: list[Path] = []
    for outcome in outcomes.values():
        for file in outcome.files:
            if file.form is _Form.PRICES:
                save_prices(file.table, root / file.path)
            elif file.form is _Form.SERIES:
                save_series(file.table, root / file.path, decimals=outcome.dataset.decimals)
            elif file.form is _Form.MONTHLY:
                save_monthly_data(file.table, root / file.path)
            else:
                raise RuntimeError(f"내부 불변조건 위반: 쓸 수 없는 모양 {file.form} 의 파일 {file.path} 를 받았습니다")
            written.append(file.path)
    for path, table in products.prices.items():
        save_prices(table, root / path)
        written.append(path)
    for path, table in products.tables.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(root / path, index=False, encoding=_TABLE_ENCODING)
        written.append(path)
    return written


def _form_of(dataset: Dataset, path: Path) -> _Form:
    if dataset.kind in (*_YAHOO_KINDS, Kind.BITSTAMP):
        return _Form.PRICES
    if dataset.kind is Kind.KRX_ETF:
        return _Form.PRICES if path == dataset.files[0] else _Form.SERIES
    if dataset.kind in (Kind.KRX_INDEX, Kind.KRX_NAV, Kind.COINMETRICS):
        return _Form.SERIES
    if dataset.kind in (Kind.FRED_MONTHLY, Kind.MANUAL_MONTHLY):
        return _Form.MONTHLY
    return _Form.OTHER


def _manifest_entries(
    root: Path,
    catalog: Sequence[Dataset],
    outcomes: Mapping[str, _DatasetOutcome],
    products: Products,
    previous: Mapping[str, object] | None,
    exclude: Collection[str],
) -> dict[Path, dict[str, object]]:
    """매니페스트의 파일 항목 — 표 순서, 그다음 가공 시세. 받지 않은 파일은 지금 파일로 기간을 잰다."""
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
                entry = _period_entry(
                    dataset.name, _read_for_period(dataset, root, path), _idle_status(dataset, exclude)
                )
                carried = previous_files.get(path.as_posix(), {}) if isinstance(previous_files, dict) else {}
                first_dividend = carried.get(KEY_FIRST_DIVIDEND) if isinstance(carried, dict) else None
            if dataset.kind in _YAHOO_KINDS:
                entry[KEY_FIRST_DIVIDEND] = first_dividend
            entries[path] = entry
    for path, table in products.prices.items():
        ticker, _ = parse_price_file_name(path.name)
        entries[path] = _period_entry(ticker, table, STATUS_PRODUCT)
        if path in products.notes:
            entries[path][KEY_DISTRIBUTION_CHECK] = list(products.notes[path])
    return entries


def _idle_status(dataset: Dataset, exclude: Collection[str]) -> str:
    if dataset.method is Method.FIXED:
        return STATUS_FIXED
    return STATUS_EXCLUDED if dataset.name in exclude else STATUS_NOT_FETCHED


def _read_for_period(dataset: Dataset, root: Path, path: Path) -> pd.DataFrame:
    # 모양은 표의 상대 경로로 가름 — 국내 ETF 는 두 파일의 모양이 달라, 절대 경로를 넘기면 원본가를 계열로 읽음
    form = _form_of(dataset, path)
    if form is _Form.PRICES:
        return load_prices(root / path)
    if form is _Form.SERIES:
        return load_series(root / path)
    return pd.read_csv(root / path, dtype=str)


def _period_entry(ticker: str, table: pd.DataFrame, status: str) -> dict[str, object]:
    """종목 · 첫날 · 끝날 · 행 수 · 상태 — 날짜는 첫 열(시세 · 계열의 Date · 월별의 DATE). 행이 없으면 날짜는 None."""
    first_column = table.columns[0]
    empty = table.empty
    return {
        KEY_TICKER: ticker,
        KEY_FIRST_DAY: None if empty else _day_text(table[first_column].iloc[0]),
        KEY_LAST_DAY: None if empty else _day_text(table[first_column].iloc[-1]),
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
    멈춘 갱신의 원인 — 사용자가 그대로 AI 에 붙여 판단을 받는다. 시세 비정상은 진단 출력(--accept · --exclude 안내),
    계열 · 월별 비정상은 진단 줄, 신규 일자 실패는 허용 목록에 적을 줄의 앞 세 칸과 함께 낸다.
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
            "[신규 일자 검사 실패 — 실제 대폭락 · 대폭등이면 허용 목록에 근거와 함께 적고 다시 실행하세요]",
            f"허용 목록: {ALLOWLIST_PATH} — 한 줄에 종목,날짜,검사,사유,근거 (근거 없이 적지 않습니다)",
        ]
        lines += [
            f"  - {failure.ticker},{failure.day},{failure.check.value} — {failure.detail}"
            for failure in result.new_day_failures
        ]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
