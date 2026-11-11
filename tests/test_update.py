"""
update 모듈 테스트 — 갱신 명령: 받기 → 판정 → 가공 → (전부 성공했을 때만) 쓰기 → 판 요약

이 파일은 무엇을 검증하나요?
1. 비정상 · 새로 붙는 날 실패가 하나라도 있으면 끝까지 받아 판정해 한 번에 보이고 아무 파일도 쓰지 않는가?
   받기 실패 · 가공 실패는 그 자리에서 멈추고 역시 쓰지 않는가? (결정 Q17)
2. --exclude 는 옛 값 · 옛 끝날을 두고, --accept 는 이번 응답으로 덮어쓰는가? 둘 다 판정 규칙 ② 의 실패는 놓아주지 않는가? (결정 Q16)
3. 분할은 비정상으로 멈추고 원인에 「분할로 보이는 변화」를 적는가? (결정 Q23)
4. 고정 자료는 요청하지 않는가? (결정 Q20)
5. 새로 붙는 날만 짝 대조 · 하루 변동 검사를 걸고, 패스 목록에 있으면 통과하며, 급등락으로 저장이 거부되지 않는가?
   기존 파일이 없으면 미국 짝 대조를 걸지 않는가? (결정 Q26 · Q27 · Q29 · Q34)
6. 월별 금리는 지난 달이 그대로일 때만 새 달을 붙이는가? (결정 Q36)
7. 판 요약에 파일마다 종목 · 기간 · 행 수 · 상태 · 분배 기록 첫날이 적히는가? (결정 Q12)

왜 중요한가요?
「수정주가가 배당으로 바뀌는 것 말고는 데이터가 바뀌면 오류다. 정상이면 최신 데이터만 추가된다」(판정 원칙).
판정이 멈췄는데 일부 파일만 쓰이면, 사용처가 반쯤 갱신된 판을 가져가도 에러가 나지 않는다.
"""

import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant_data.catalog import Dataset, Kind, Method
from quant_data.constants import (
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    EDITION_PATH,
    KR_ACTIONS_PATH,
    PASS_LIST_PATH,
    REQUIRED_COLUMNS,
    SERIES_DIR,
)
from quant_data.edition import (
    KEY_CUTOFF,
    KEY_FILES,
    KEY_FIRST_DAY,
    KEY_FIRST_DIVIDEND,
    KEY_LAST_DAY,
    KEY_ROWS,
    KEY_STATUS,
    KEY_TICKER,
    STATUS_ACCEPTED,
    STATUS_EXCLUDED,
    STATUS_FIXED,
    STATUS_NEW,
    STATUS_NOISE,
    STATUS_NOT_FETCHED,
    STATUS_PRODUCT,
)
from quant_data.leveraged.monthly_data import load_monthly_data, save_monthly_data
from quant_data.new_days import TEMP_DAILY_MOVE_LIMIT, Check
from quant_data.prices import PriceBasis, load_prices, price_path, save_prices
from quant_data.revision import PriceEvents
from quant_data.sources.yahoo import YahooResponse
from quant_data.update import Fetchers, Products, UpdateResult, format_stop_report, run_update

DAYS = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
EXISTING_ROWS = 3  # 기존 파일은 11-02 ~ 11-04, 새로 붙는 날은 11-05 · 11-06
CUTOFF = date(2026, 11, 6)
QQQ_CLOSES = [100.0, 101.0, 102.0, 103.0, 104.0]
NDX_CLOSES = [c * 10 for c in QQQ_CLOSES]  # QQQ 와 하루 수익률이 같다 — 짝 차이 0
VFINX_CLOSES = [50.0, 50.5, 51.0]

QQQ_RAW = price_path("QQQ", PriceBasis.RAW)
QQQ_ADJUSTED = price_path("QQQ", PriceBasis.ADJUSTED)
NDX_RAW = price_path("^NDX", PriceBasis.RAW)
VFINX_ADJUSTED = price_path("VFINX", PriceBasis.ADJUSTED)
FFR_FILE = SERIES_DIR / "federal_funds_rate_monthly.csv"
QQQ_SYNTHETIC = price_path("QQQ", PriceBasis.SYNTHETIC)
SUMMARY_TABLE = Path("storage/validation/summary.csv")

QQQ = Dataset(
    name="QQQ",
    kind=Kind.YAHOO_FUND,
    method=Method.REFETCH,
    files=(QQQ_RAW, QQQ_ADJUSTED),
    pair="^NDX",
    leverage=1.0,
)
NDX = Dataset(name="^NDX", kind=Kind.YAHOO_INDEX, method=Method.APPEND, files=(NDX_RAW,))
VFINX = Dataset(name="VFINX", kind=Kind.YAHOO_FUND, method=Method.FIXED, files=(VFINX_ADJUSTED,))
FFR = Dataset(name="FFR", kind=Kind.FRED_MONTHLY, method=Method.APPEND, files=(FFR_FILE,))
CATALOG = (QQQ, NDX, VFINX, FFR)

FFR_EXISTING = pd.DataFrame({"DATE": ["2026-08", "2026-09"], "VALUE": [0.0433, 0.0422]})
FFR_RESPONSE = pd.DataFrame({"DATE": ["2026-08", "2026-09", "2026-10"], "VALUE": [0.0433, 0.0422, 0.0409]})


def _table(closes: list[float], days: list[date] | None = None) -> pd.DataFrame:
    """시세 표 — 시가 · 고가 · 저가 = 종가 (조정 비율이 네 열에 똑같이 걸린다)."""
    return pd.DataFrame(
        {
            COL_DATE: days if days is not None else DAYS[: len(closes)],
            COL_OPEN: closes,
            COL_HIGH: closes,
            COL_LOW: closes,
            COL_CLOSE: closes,
            COL_VOLUME: 1000,
        }
    )[REQUIRED_COLUMNS]


def _response(
    closes: list[float],
    *,
    adjusted: list[float] | None = None,
    dividends: dict[date, float] | None = None,
    splits: dict[date, float] | None = None,
    days: list[date] | None = None,
) -> YahooResponse:
    """야후 응답 — 원본가 · 수정주가(주지 않으면 원본가와 같음) · 기록."""
    used_days = days if days is not None else DAYS[: len(closes)]
    return YahooResponse(
        raw=_table(closes, used_days),
        adjusted=_table(adjusted if adjusted is not None else closes, used_days),
        events=PriceEvents(
            dividends=pd.Series(dividends or {}, dtype=float),
            splits=pd.Series(splits or {}, dtype=float),
            raw_close=pd.Series(closes, index=used_days, dtype=float),
        ),
    )


class FakeSources:
    """받기 대역 — 부른 자료를 순서대로 남기고, fail 에 든 티커는 받기 실패를 낸다."""

    def __init__(
        self,
        yahoo: Mapping[str, YahooResponse],
        ffr: pd.DataFrame = FFR_RESPONSE,
        fail: frozenset[str] = frozenset(),
    ) -> None:
        self.responses = dict(yahoo)
        self.ffr = ffr
        self.fail = fail
        self.calls: list[str] = []

    def _yahoo(self, ticker: str) -> YahooResponse:
        self.calls.append(ticker)
        if ticker in self.fail:
            raise ConnectionError(f"받기 실패 대역: {ticker}")
        return self.responses[ticker]

    def _ffr(self) -> pd.DataFrame:
        self.calls.append("FFR")
        return self.ffr

    def fetchers(self) -> Fetchers:
        return Fetchers(yahoo=self._yahoo, ffr_monthly=self._ffr)


def _normal_sources(**overrides: YahooResponse) -> FakeSources:
    responses = {"QQQ": _response(QQQ_CLOSES), "^NDX": _response(NDX_CLOSES)}
    responses.update(overrides)
    return FakeSources(responses)


def _no_products(_updated: Mapping[Path, pd.DataFrame]) -> Products:
    return Products(prices={}, tables={})


def _write_records(root: Path) -> None:
    for path, header in ((PASS_LIST_PATH, "종목,날짜,검사,사유,근거"), (KR_ACTIONS_PATH, "종목,날짜,비율,근거")):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(header + "\n", encoding="utf-8-sig")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """저장소 루트 대역 — QQQ · ^NDX 는 앞 3일, VFINX 는 고정 파일, 월별 금리는 두 달, 기록 파일은 머리만."""
    save_prices(_table(QQQ_CLOSES[:EXISTING_ROWS]), tmp_path / QQQ_RAW)
    save_prices(_table(QQQ_CLOSES[:EXISTING_ROWS]), tmp_path / QQQ_ADJUSTED)
    save_prices(_table(NDX_CLOSES[:EXISTING_ROWS]), tmp_path / NDX_RAW)
    save_prices(_table(VFINX_CLOSES), tmp_path / VFINX_ADJUSTED)
    save_monthly_data(FFR_EXISTING, tmp_path / FFR_FILE)
    _write_records(tmp_path)
    return tmp_path


def _snapshot(root: Path) -> dict[Path, bytes]:
    """storage 아래 모든 파일의 바이트."""
    return {p.relative_to(root): p.read_bytes() for p in sorted((root / "storage").rglob("*")) if p.is_file()}


def _run(
    root: Path,
    sources: FakeSources,
    *,
    catalog: tuple[Dataset, ...] = CATALOG,
    exclude: frozenset[str] = frozenset(),
    accept: frozenset[str] = frozenset(),
    cutoff: date = CUTOFF,
    build_products=_no_products,
) -> UpdateResult:
    return run_update(
        catalog,
        sources.fetchers(),
        root=root,
        cutoff_date=cutoff,
        exclude=exclude,
        accept=accept,
        build_products=build_products,
    )


def _edition(root: Path) -> dict:
    return json.loads((root / EDITION_PATH).read_text(encoding="utf-8"))


class TestNormalUpdate:
    """전부 정상 — 기존 행은 그대로 두고 새 날짜만 붙인다"""

    def test_appends_new_days_and_keeps_existing_rows(self, root: Path) -> None:
        """
        목적: 정상이면 최신 데이터만 추가된다 — 기존 파일의 머리 · 기존 행은 글자 그대로, 새 날짜 행만 붙는다

        Given: 기존 3일, 같은 값에 2일이 더해진 응답
        When: run_update
        Then: 멈추지 않음, QQQ 원본가 · 수정주가 · ^NDX 가 5행이고 앞 4줄(머리 + 3행)이 글자 그대로
        """
        # Given
        before = {path: (root / path).read_text().splitlines() for path in (QQQ_RAW, QQQ_ADJUSTED, NDX_RAW)}

        # When
        result = _run(root, _normal_sources())

        # Then
        assert not result.stopped
        for path, lines in before.items():
            after = (root / path).read_text().splitlines()
            assert after[: EXISTING_ROWS + 1] == lines
            assert len(after) == len(DAYS) + 1

    def test_raw_file_gets_raw_prices(self, root: Path) -> None:
        """
        목적: 원본가 파일에는 응답의 원시 가격이, 수정주가 파일에는 C-1 이 붙는다 — 한 응답에서 두 파일

        Given: 11-06 배당 $0.50 (전날 원시 종가 103 → 비율 102.5 ÷ 103) — 응답의 수정 종가는 11-05 까지 그 비율만큼 낮다
        When: run_update
        Then: 원본가 11-05 종가 103(원시 그대로), 수정주가 11-05 종가 102.5
        """
        # Given
        factor = 102.5 / 103.0
        response = _response(
            QQQ_CLOSES,
            adjusted=[c * factor for c in QQQ_CLOSES[:4]] + [104.0],
            dividends={DAYS[4]: 103.0 * (1 - factor)},
        )

        # When
        result = _run(root, _normal_sources(QQQ=response))

        # Then
        assert not result.stopped
        assert load_prices(root / QQQ_RAW)[COL_CLOSE].iloc[3] == 103.0
        assert load_prices(root / QQQ_ADJUSTED)[COL_CLOSE].iloc[3] == pytest.approx(102.5, abs=1e-6)

    def test_fixed_datasets_are_not_requested(self, root: Path) -> None:
        """
        목적: 고정 자료는 요청하지 않는다 — 쓰는 곳이 없으면 고정이 기본이고, 받으면 판정에 걸려 멈출 일만 는다(Q20)

        Given: 다시 받음 QQQ · 덧붙이기 ^NDX · FFR · 고정 VFINX
        When: run_update
        Then: 받은 자료 = {QQQ, ^NDX, FFR}, VFINX 파일은 바이트 그대로
        """
        # Given
        sources = _normal_sources()
        vfinx_before = (root / VFINX_ADJUSTED).read_bytes()

        # When
        _run(root, sources)

        # Then
        assert sorted(sources.calls) == sorted(["QQQ", "^NDX", "FFR"])
        assert (root / VFINX_ADJUSTED).read_bytes() == vfinx_before

    def test_ffr_appends_new_month(self, root: Path) -> None:
        """
        목적: 월별 금리는 지난 달이 그대로면 새로 나온 달을 붙인다(Q36)

        Given: 기존 2026-08 · 09, 응답 2026-08 ~ 10 (앞 두 달 같음)
        When: run_update
        Then: 금리 파일이 세 달
        """
        # When
        _run(root, _normal_sources())

        # Then
        assert load_monthly_data(root / FFR_FILE)["DATE"].tolist() == ["2026-08", "2026-09", "2026-10"]


class TestRawFileJudgement:
    """원본가 파일은 배당으로 설명하지 않는다 — 야후 원본가는 분할만 과거에 반영된다"""

    def test_dividend_like_change_in_raw_file_stops(self, root: Path) -> None:
        """
        목적: 갱신이 원본가 파일을 배당 기록으로 설명하지 않는 판정에 넘긴다 — 수정주가는 같은 응답으로 설명돼도
              원본가 과거가 배당 비율만큼 바뀌면 원본가 파일이 비정상이다

        Given: 응답의 원본가 · 수정주가 모두 11-02 · 11-03 이 × 0.99, 11-04 배당 $0.9999 기록(응답의 전날 원시 종가 99.99
               → 비율 정확히 0.99)
        When: run_update
        Then: 멈춤, 비정상 파일 = QQQ 원본가 하나 (수정주가는 설명되는 변화)
        """
        # Given
        changed = [QQQ_CLOSES[0] * 0.99, QQQ_CLOSES[1] * 0.99, *QQQ_CLOSES[2:]]
        sources = _normal_sources(QQQ=_response(changed, dividends={DAYS[2]: 0.9999}))

        # When
        result = _run(root, sources)

        # Then
        assert result.stopped
        assert [(abnormal.name, abnormal.path) for abnormal in result.abnormal] == [("QQQ", QQQ_RAW)]


class TestNoFetch:
    """--no-fetch — 받지 않고 지금 파일로 가공 · 판 요약만 (첫 판 · 가공 코드를 고친 뒤)"""

    def test_requests_nothing_and_writes_products_and_edition(self, root: Path) -> None:
        """
        목적: 아무것도 받지 않고, 받은 자료 파일은 그대로 두며, 가공 · 판 요약만 쓴다 — 받지 않은 자료는 「받지 않음」
              (고정 자료는 「고정」)으로 적는다

        Given: 지금 파일들, 합성 하나를 돌려주는 가공
        When: run_update(fetch=False)
        Then: 받은 자료 없음, QQQ 수정주가 바이트 그대로, 판 요약의 QQQ 수정주가 = 받지 않음 · VFINX = 고정 · 합성 = 가공
        """
        # Given
        sources = _normal_sources()
        before = (root / QQQ_ADJUSTED).read_bytes()

        def products(updated: Mapping[Path, pd.DataFrame]) -> Products:
            assert updated == {}
            return Products(prices={QQQ_SYNTHETIC: _table(QQQ_CLOSES[:EXISTING_ROWS])}, tables={})

        # When
        result = run_update(
            CATALOG,
            sources.fetchers(),
            root=root,
            cutoff_date=date(2026, 11, 4),
            exclude=frozenset(),
            accept=frozenset(),
            build_products=products,
            fetch=False,
        )

        # Then
        assert not result.stopped
        assert sources.calls == []
        assert (root / QQQ_ADJUSTED).read_bytes() == before
        files = _edition(root)[KEY_FILES]
        assert files[QQQ_ADJUSTED.as_posix()][KEY_STATUS] == STATUS_NOT_FETCHED
        assert files[VFINX_ADJUSTED.as_posix()][KEY_STATUS] == STATUS_FIXED
        assert files[QQQ_SYNTHETIC.as_posix()][KEY_STATUS] == STATUS_PRODUCT

    def test_options_are_rejected(self, root: Path) -> None:
        """
        목적: 받지 않는 갱신에는 --exclude · --accept 를 쓸 수 없다 — 판정할 응답이 없다

        Given: --exclude QQQ
        When: run_update(fetch=False)
        Then: ValueError (「--no-fetch」)
        """
        # When & Then
        with pytest.raises(ValueError, match="--no-fetch"):
            run_update(
                CATALOG,
                _normal_sources().fetchers(),
                root=root,
                cutoff_date=CUTOFF,
                exclude=frozenset({"QQQ"}),
                accept=frozenset(),
                build_products=_no_products,
                fetch=False,
            )


class TestCatalogCheck:
    """자료별 갱신 방식 표 자체의 검사 — 받기 전에 멈춘다"""

    @pytest.mark.parametrize(
        ("dataset", "pattern"),
        [
            (
                Dataset(name="QQQ", kind=Kind.YAHOO_FUND, method=Method.REFETCH, files=(QQQ_RAW,), pair="^XYZ"),
                "짝",
            ),
            (Dataset(name="EXP", kind=Kind.MANUAL_MONTHLY, method=Method.APPEND, files=(FFR_FILE,)), "받는 함수"),
        ],
        ids=["pair_missing", "manual_not_fixed"],
    )
    def test_bad_catalog_raises(self, root: Path, dataset: Dataset, pattern: str) -> None:
        """
        목적: 짝이 표에 없거나, 받는 함수가 없는 종류(손 갱신 등)를 고정이 아닌 방식으로 두면 받기 전에 멈춘다 —
              짝이 없으면 새로 붙는 날이 모두 「짝 없음」으로 멈추고, 받는 함수가 없으면 갱신 도중에 깨진다

        Given: 잘못된 줄 하나가 든 표
        When: run_update
        Then: ValueError, 아무것도 받지 않음
        """
        # Given
        sources = _normal_sources()

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            _run(root, sources, catalog=(dataset,))
        assert sources.calls == []


class TestStopReport:
    """멈춘 갱신의 원인 — 사용자가 그대로 AI 에 붙인다"""

    def test_report_has_price_block_monthly_lines_and_pass_list_guidance(self, root: Path) -> None:
        """
        목적: 시세 비정상은 원인 블록(--accept · --exclude 안내), 월별 비정상은 원인 줄, 새로 붙는 날 실패는 패스 목록에 적을
              「종목,날짜,검사」와 함께 한 보고에 낸다

        Given: QQQ 수정주가 첫 행 +0.4% · 금리 2026-08 값 바뀜 · (QQQ 를 받아들이면) 11-06 짝 차이 실패 — 두 번 돌려 두 보고
        When: format_stop_report
        Then: 첫 보고에 「--accept QQQ」 · 「FFR —」, 둘째 보고에 「QQQ,2026-11-06,짝 차이」 · 패스 목록 경로
        """
        # Given
        sources = _normal_sources(QQQ=_response(QQQ_CLOSES, adjusted=[100.4, *QQQ_CLOSES[1:]]))
        sources.ffr = pd.DataFrame({"DATE": ["2026-08", "2026-09", "2026-10"], "VALUE": [0.0440, 0.0422, 0.0409]})
        run_at = datetime(2026, 11, 11, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        first = _run(root, sources)
        closes = [*QQQ_CLOSES[:4], 103.0 * 1.03]
        second = _run(
            root,
            _normal_sources(QQQ=_response(closes), **{"^NDX": _response([*NDX_CLOSES[:4], 1030.0 * 1.01])}),
        )

        # When
        first_report = format_stop_report(first, run_at=run_at, cutoff_date=CUTOFF, yfinance_version="0.2.66")
        second_report = format_stop_report(second, run_at=run_at, cutoff_date=CUTOFF, yfinance_version="0.2.66")

        # Then
        assert "--accept QQQ" in first_report
        assert "FFR —" in first_report
        assert "QQQ,2026-11-06,짝 차이" in second_report
        assert str(PASS_LIST_PATH) in second_report


class TestStopWritesNothing:
    """멈추면 아무 파일도 쓰지 않는다 (Q17)"""

    def test_abnormal_writes_nothing(self, root: Path) -> None:
        """
        목적: 비정상이 하나라도 있으면 다른 정상 자료 · 가공 · 판 요약도 쓰지 않는다 — 반쯤 갱신된 판이 남지 않는다

        Given: QQQ 수정주가 첫 행만 +0.4% (기록 없음), 나머지 정상
        When: run_update
        Then: 멈춤, 비정상 = [QQQ], storage 아래 모든 파일 바이트 그대로, 가공을 부르지 않음
        """
        # Given
        before = _snapshot(root)
        calls: list[Mapping[Path, pd.DataFrame]] = []

        def products(updated: Mapping[Path, pd.DataFrame]) -> Products:
            calls.append(updated)
            return _no_products(updated)

        sources = _normal_sources(QQQ=_response(QQQ_CLOSES, adjusted=[100.4, *QQQ_CLOSES[1:]]))

        # When
        result = _run(root, sources, build_products=products)

        # Then
        assert result.stopped
        assert [abnormal.name for abnormal in result.abnormal] == ["QQQ"]
        assert result.written == ()
        assert _snapshot(root) == before
        assert calls == []

    def test_all_abnormal_reported_at_once(self, root: Path) -> None:
        """
        목적: 끝까지 받아 판정하고 비정상을 한 번에 보인다 — 하나씩 멈추면 사람이 같은 실행을 비정상 수만큼 되풀이한다

        Given: QQQ 수정주가 · ^NDX 원본가 모두 첫 행이 바뀜
        When: run_update
        Then: 멈춤, 비정상 = QQQ · ^NDX 둘, 네 자료(QQQ · ^NDX · FFR)를 모두 받았다
        """
        # Given
        sources = _normal_sources(
            QQQ=_response(QQQ_CLOSES, adjusted=[100.4, *QQQ_CLOSES[1:]]),
            **{"^NDX": _response([1004.0, *NDX_CLOSES[1:]])},
        )

        # When
        result = _run(root, sources)

        # Then
        assert result.stopped
        assert sorted(abnormal.name for abnormal in result.abnormal) == ["QQQ", "^NDX"]
        assert sorted(sources.calls) == sorted(["QQQ", "^NDX", "FFR"])

    def test_fetch_failure_stops_without_writing(self, root: Path) -> None:
        """
        목적: 받기 실패(예외)는 그 자리에서 멈추고 아무것도 쓰지 않는다 — 앞서 받은 정상 자료도 쓰지 않는다

        Given: ^NDX 받기가 실패하는 대역
        When: run_update
        Then: 그 예외가 그대로 올라오고, storage 아래 모든 파일 바이트 그대로
        """
        # Given
        before = _snapshot(root)
        sources = _normal_sources()
        sources.fail = frozenset({"^NDX"})

        # When & Then
        with pytest.raises(ConnectionError, match="받기 실패 대역"):
            _run(root, sources)
        assert _snapshot(root) == before

    def test_product_failure_writes_nothing(self, root: Path) -> None:
        """
        목적: 가공(합성 등)이 실패해도 받은 시세를 쓰지 않는다 — 받은 실물만 바뀌고 합성이 낡은 판이 남지 않는다

        Given: 판정은 모두 정상, 가공이 RuntimeError
        When: run_update
        Then: 그 예외가 올라오고, storage 아래 모든 파일 바이트 그대로
        """
        # Given
        before = _snapshot(root)

        def failing_products(_updated: Mapping[Path, pd.DataFrame]) -> Products:
            raise RuntimeError("내부 불변조건 위반: 가공 대역")

        # When & Then
        with pytest.raises(RuntimeError, match="가공 대역"):
            _run(root, _normal_sources(), build_products=failing_products)
        assert _snapshot(root) == before

    def test_changed_ffr_month_stops(self, root: Path) -> None:
        """
        목적: 월별 금리의 지난 달 값이 바뀌면 비정상으로 멈춘다 — 「데이터가 바뀌면 오류」(판정 원칙 · Q36)

        Given: 응답의 2026-08 = 0.0440 (기존 0.0433)
        When: run_update
        Then: 멈춤, 비정상 = [FFR], 파일 바이트 그대로
        """
        # Given
        before = _snapshot(root)
        sources = _normal_sources()
        sources.ffr = pd.DataFrame({"DATE": ["2026-08", "2026-09", "2026-10"], "VALUE": [0.0440, 0.0422, 0.0409]})

        # When
        result = _run(root, sources)

        # Then
        assert result.stopped
        assert [abnormal.name for abnormal in result.abnormal] == ["FFR"]
        assert _snapshot(root) == before


class TestExcludeAndAccept:
    """사람이 정하는 두 출구 — --exclude 는 옛 파일 그대로, --accept 는 이번 응답으로 (Q16)"""

    ABNORMAL_QQQ = _response(QQQ_CLOSES, adjusted=[100.4, *QQQ_CLOSES[1:]])

    def test_exclude_keeps_old_files_without_fetching(self, root: Path) -> None:
        """
        목적: --exclude 한 종목은 받지 않고 옛 값 · 옛 끝날 그대로 두며, 나머지는 쓴다

        Given: QQQ 비정상 응답, --exclude QQQ
        When: run_update
        Then: 멈추지 않음, QQQ 를 받지 않았고 두 파일 바이트 그대로, ^NDX 는 5행, 결과의 제외 = (QQQ,)
        """
        # Given
        qqq_before = {path: (root / path).read_bytes() for path in (QQQ_RAW, QQQ_ADJUSTED)}
        sources = _normal_sources(QQQ=self.ABNORMAL_QQQ)

        # When
        result = _run(root, sources, exclude=frozenset({"QQQ"}))

        # Then
        assert not result.stopped
        assert "QQQ" not in sources.calls
        assert {path: (root / path).read_bytes() for path in (QQQ_RAW, QQQ_ADJUSTED)} == qqq_before
        assert len(load_prices(root / NDX_RAW)) == len(DAYS)
        assert result.excluded == ("QQQ",)

    def test_accept_overwrites_with_response(self, root: Path) -> None:
        """
        목적: --accept 한 종목은 비정상이어도 이번 응답으로 덮어쓴다 — 바뀐 과거 행까지 응답 값이다

        Given: QQQ 수정주가 첫 행 +0.4% 응답, --accept QQQ
        When: run_update
        Then: 멈추지 않음, QQQ 수정주가 첫 행 종가 100.4, 결과의 받아들임 = (QQQ,)
        """
        # When
        result = _run(root, _normal_sources(QQQ=self.ABNORMAL_QQQ), accept=frozenset({"QQQ"}))

        # Then
        assert not result.stopped
        assert load_prices(root / QQQ_ADJUSTED)[COL_CLOSE].iloc[0] == pytest.approx(100.4, abs=1e-9)
        assert result.accepted == ("QQQ",)

    def test_accept_does_not_release_new_day_failure(self, root: Path) -> None:
        """
        목적: --accept 는 판정 규칙 ①(과거 행)만 넘긴다 — 새로 붙는 날의 짝 차이 실패는 패스 목록으로만 넘긴다

        Given: QQQ 첫 행 +0.4% 이고 11-06 이 +3%(짝 +1%), --accept QQQ
        When: run_update
        Then: 멈춤, 새로 붙는 날 실패 = [(QQQ, 11-06, 짝 차이)]
        """
        # Given
        closes = [*QQQ_CLOSES[:4], 103.0 * 1.03]
        ndx = [*NDX_CLOSES[:4], 1030.0 * 1.01]
        sources = _normal_sources(QQQ=_response(closes, adjusted=[100.4, *closes[1:]]), **{"^NDX": _response(ndx)})

        # When
        result = _run(root, sources, accept=frozenset({"QQQ"}))

        # Then
        assert result.stopped
        assert [(f.ticker, f.day, f.check) for f in result.new_day_failures] == [("QQQ", DAYS[4], Check.PAIR)]

    @pytest.mark.parametrize(
        ("exclude", "accept"),
        [
            (frozenset({"XYZ"}), frozenset()),
            (frozenset(), frozenset({"VFINX"})),
            (frozenset({"QQQ"}), frozenset({"QQQ"})),
        ],
        ids=["unknown_name", "fixed_dataset", "both_options"],
    )
    def test_bad_option_raises_before_fetching(
        self, root: Path, exclude: frozenset[str], accept: frozenset[str]
    ) -> None:
        """
        목적: 표에 없는 이름 · 고정 자료 · 두 옵션에 같은 이름이면 받기 전에 멈춘다 — 오타가 조용히 무시되면
              사람이 정한 제외 · 받아들임이 걸리지 않은 채 갱신이 진행된다

        Given: 잘못된 --exclude / --accept
        When: run_update
        Then: ValueError, 아무것도 받지 않음
        """
        # Given
        sources = _normal_sources()

        # When & Then
        with pytest.raises(ValueError):
            _run(root, sources, exclude=exclude, accept=accept)
        assert sources.calls == []


class TestSplit:
    """분할은 비정상으로 멈춘다 (Q23)"""

    def test_split_stops_with_split_cause(self, root: Path) -> None:
        """
        목적: 응답에 분할 기록이 있고 과거 가격이 그 비율로 바뀌어도 비정상으로 멈추고 원인에 분할로 보이는 날짜 · 비율을 적는다

        Given: 11-03 2배 분할 — 응답의 11-02 원본가 · 수정주가가 50 (기존 100)
        When: run_update
        Then: 멈춤, QQQ 비정상의 원인 줄에 「분할로 보이는 변화: 2026-11-03 · 2배 (야후 기록)」
        """
        # Given
        closes = [50.0, *QQQ_CLOSES[1:]]
        sources = _normal_sources(QQQ=_response(closes, splits={DAYS[1]: 2.0}))

        # When
        result = _run(root, sources)

        # Then
        assert result.stopped
        issues = [line for abnormal in result.abnormal if abnormal.name == "QQQ" for line in abnormal.issues]
        assert any("분할로 보이는 변화: 2026-11-03 · 2배 (야후 기록)" in line for line in issues)


class TestNewDayChecks:
    """새로 붙는 날 검사 (판정 규칙 ②)"""

    PAIR_BREAK_QQQ = [*QQQ_CLOSES[:4], 103.0 * 1.03]  # 11-06 +3%
    PAIR_BREAK_NDX = [*NDX_CLOSES[:4], 1030.0 * 1.01]  # 11-06 +1%

    def test_pair_difference_stops(self, root: Path) -> None:
        """
        목적: 새로 붙는 날의 짝 차이가 배율 × 1%p 를 넘으면 멈추고 아무것도 쓰지 않는다

        Given: 11-06 QQQ +3%, 나스닥100 +1% (차이 2%p)
        When: run_update
        Then: 멈춤, 실패 = [(QQQ, 11-06, 짝 차이)], 파일 바이트 그대로
        """
        # Given
        before = _snapshot(root)
        sources = _normal_sources(
            QQQ=_response(self.PAIR_BREAK_QQQ), **{"^NDX": _response(self.PAIR_BREAK_NDX)}
        )

        # When
        result = _run(root, sources)

        # Then
        assert result.stopped
        assert [(f.ticker, f.day, f.check) for f in result.new_day_failures] == [("QQQ", DAYS[4], Check.PAIR)]
        assert _snapshot(root) == before

    def test_pass_list_entry_releases_failure(self, root: Path) -> None:
        """
        목적: 패스 목록에 그 종목 · 날짜 · 검사가 근거와 함께 있으면 통과해 쓴다 — 실제 대폭락 · 대폭등의 탈출구

        Given: 같은 짝 차이, 패스 목록에 「QQQ,2026-11-06,짝 차이,…」
        When: run_update
        Then: 멈추지 않음, QQQ 수정주가 5행
        """
        # Given
        with (root / PASS_LIST_PATH).open("a", encoding="utf-8") as file:
            file.write("QQQ,2026-11-06,짝 차이,테스트 사유,테스트 근거\n")
        sources = _normal_sources(
            QQQ=_response(self.PAIR_BREAK_QQQ), **{"^NDX": _response(self.PAIR_BREAK_NDX)}
        )

        # When
        result = _run(root, sources)

        # Then
        assert not result.stopped
        assert len(load_prices(root / QQQ_ADJUSTED)) == len(DAYS)

    def test_past_rows_are_not_checked(self, root: Path) -> None:
        """
        목적: 과거 행의 큰 짝 차이로는 멈추지 않는다 — 과거는 판정 규칙 ① 이 지킨다

        Given: 기존 QQQ 11-03 이 +50%(나스닥100 +1%), 새로 붙는 날은 짝과 같이 +1%
        When: run_update
        Then: 멈추지 않음
        """
        # Given
        qqq = [100.0, 150.0, 151.0, 151.0 * 1.01, 151.0 * 1.01 * 1.01]
        ndx = [1000.0, 1010.0, 1020.0, 1020.0 * 1.01, 1020.0 * 1.01 * 1.01]
        save_prices(_table(qqq[:EXISTING_ROWS]), root / QQQ_RAW)
        save_prices(_table(qqq[:EXISTING_ROWS]), root / QQQ_ADJUSTED)
        save_prices(_table(ndx[:EXISTING_ROWS]), root / NDX_RAW)
        sources = _normal_sources(QQQ=_response(qqq), **{"^NDX": _response(ndx)})

        # When
        result = _run(root, sources)

        # Then
        assert not result.stopped

    def test_spike_matching_pair_is_saved(self, root: Path) -> None:
        """
        목적: 하루 +60% 라도 짝과 함께 움직였으면 저장한다 — 급등락으로 저장이 거부되지 않는다(Q26)

        Given: 11-06 QQQ · 나스닥100 모두 +60%
        When: run_update
        Then: 멈추지 않음(예외 없음), QQQ 수정주가 마지막 종가 164.8
        """
        # Given
        qqq = [*QQQ_CLOSES[:4], 103.0 * 1.6]
        ndx = [*NDX_CLOSES[:4], 1030.0 * 1.6]

        # When
        result = _run(root, _normal_sources(QQQ=_response(qqq), **{"^NDX": _response(ndx)}))

        # Then
        assert not result.stopped
        assert load_prices(root / QQQ_ADJUSTED)[COL_CLOSE].iloc[-1] == pytest.approx(164.8, abs=1e-6)

    def test_unpaired_daily_move_stops(self, root: Path) -> None:
        """
        목적: 짝이 없는 금 · 장기채는 하루 변동이 임시 한도 이상이면 멈춘다 — 저장 거부(ValueError)가 아니라
              「멈춤 → 확인 → 다시 실행」 경로다(Q26 · Q27)

        Given: 하루 변동 한도가 있는 GLD, 11-06 +60%
        When: run_update
        Then: 멈춤, 실패 = [(GLD, 11-06, 하루 변동)]
        """
        # Given
        gld_files = (price_path("GLD", PriceBasis.RAW), price_path("GLD", PriceBasis.ADJUSTED))
        gld = Dataset(
            name="GLD",
            kind=Kind.YAHOO_FUND,
            method=Method.REFETCH,
            files=gld_files,
            daily_move_limit=TEMP_DAILY_MOVE_LIMIT,
        )
        closes = [150.0, 151.0, 152.0, 153.0, 153.0 * 1.6]
        for file in gld_files:
            save_prices(_table(closes[:EXISTING_ROWS]), root / file)
        sources = FakeSources({"GLD": _response(closes)})

        # When
        result = _run(root, sources, catalog=(gld,))

        # Then
        assert result.stopped
        assert [(f.ticker, f.day, f.check) for f in result.new_day_failures] == [("GLD", DAYS[4], Check.DAILY_MOVE)]

    def test_new_file_skips_pair_check(self, root: Path) -> None:
        """
        목적: 기존 파일이 없는 종목(첫 판)에는 미국 짝 대조를 걸지 않고 새 파일로 쓴다(Q34)

        Given: QQQ 파일 없음, 응답의 11-03 이 +50%(나스닥100 +1%)
        When: run_update
        Then: 멈추지 않음, QQQ 수정주가 5행
        """
        # Given
        (root / QQQ_RAW).unlink()
        (root / QQQ_ADJUSTED).unlink()
        qqq = [100.0, 150.0, 151.0, 152.0, 153.0]

        # When
        result = _run(root, _normal_sources(QQQ=_response(qqq)))

        # Then
        assert not result.stopped
        assert len(load_prices(root / QQQ_ADJUSTED)) == len(DAYS)


class TestCutoff:
    """받을 마지막 날"""

    def test_rows_after_cutoff_are_not_written(self, root: Path) -> None:
        """
        목적: 받을 마지막 날 뒤의 행은 쓰지 않는다 — 다 끝나지 않은 봉이 섞이지 않는다

        Given: 응답에 11-09 가 더 있음, 기준일 11-06
        When: run_update
        Then: QQQ 수정주가 마지막 날 11-06
        """
        # Given
        days = [*DAYS, date(2026, 11, 9)]
        sources = _normal_sources(
            QQQ=_response([*QQQ_CLOSES, 105.0], days=days), **{"^NDX": _response([*NDX_CLOSES, 1050.0], days=days)}
        )

        # When
        _run(root, sources)

        # Then
        assert load_prices(root / QQQ_ADJUSTED)[COL_DATE].iloc[-1] == CUTOFF

    def test_existing_end_after_cutoff_is_kept(self, root: Path) -> None:
        """
        목적: 기존 파일이 기준일보다 뒤까지 있으면 기존 끝날까지 견준다 — `--end` 로 받아 둔 끝 행을 기본 기준으로
              다시 받을 때 「날짜가 사라졌다」로 오탐하지 않는다

        Given: 기존 끝날 11-04, 기준일 11-03
        When: run_update
        Then: 멈추지 않음, QQQ · ^NDX 파일 바이트 그대로
        """
        # Given
        before = {path: (root / path).read_bytes() for path in (QQQ_RAW, QQQ_ADJUSTED, NDX_RAW)}

        # When
        result = _run(root, _normal_sources(), cutoff=date(2026, 11, 3))

        # Then
        assert not result.stopped
        assert {path: (root / path).read_bytes() for path in before} == before


class TestFixedFiles:
    """고정 자료 파일"""

    def test_missing_fixed_file_raises_before_fetching(self, root: Path) -> None:
        """
        목적: 고정 자료의 파일이 없으면 받기 전에 멈춘다 — 다시 받지 않는 자료라 없어진 채 가공이 돌면 합성이 엉뚱하게 멈춘다

        Given: VFINX 파일 없음
        When: run_update
        Then: ValueError (「고정」), 아무것도 받지 않음
        """
        # Given
        (root / VFINX_ADJUSTED).unlink()
        sources = _normal_sources()

        # When & Then
        with pytest.raises(ValueError, match="고정"):
            _run(root, sources)
        assert sources.calls == []


class TestProducts:
    """가공 — 갱신된 표를 받아 합성 · 검증 표를 만들고, 쓰기는 갱신이 한다"""

    def test_products_receive_updated_tables_and_are_written(self, root: Path) -> None:
        """
        목적: 가공은 이번에 쓸 표(저장소 루트 기준 경로 → 표)를 받고, 돌려준 시세는 6자리로 반올림해, 검증 표는 BOM 붙은
              CSV 로 쓴다 — 가공이 파일을 다시 읽지 않아도 쓰기 전의 새 값으로 만든다

        Given: 정상 응답, 합성 하나 · 검증 표 하나를 돌려주는 가공
        When: run_update
        Then: 가공이 받은 표에 QQQ 수정주가(5행) · ^NDX · 금리가 있고 고정 VFINX 는 없다, 합성 종가 1.123457, 검증 표가 BOM 으로 시작
        """
        # Given
        received: list[Mapping[Path, pd.DataFrame]] = []

        def products(updated: Mapping[Path, pd.DataFrame]) -> Products:
            received.append(updated)
            return Products(
                prices={QQQ_SYNTHETIC: _table([1.1234567] * len(DAYS))},
                tables={SUMMARY_TABLE: pd.DataFrame({"대상": ["QQQ"], "일간 상관": [0.9812]})},
            )

        # When
        result = _run(root, _normal_sources(), build_products=products)

        # Then
        assert not result.stopped
        updated = received[0]
        assert {QQQ_ADJUSTED, QQQ_RAW, NDX_RAW, FFR_FILE} <= set(updated)
        assert VFINX_ADJUSTED not in updated
        assert len(updated[QQQ_ADJUSTED]) == len(DAYS)
        assert load_prices(root / QQQ_SYNTHETIC)[COL_CLOSE].iloc[0] == pytest.approx(1.123457, abs=1e-9)
        assert (root / SUMMARY_TABLE).read_bytes().startswith("﻿".encode())


class TestEdition:
    """판 요약 — 파일마다 종목 · 기간 · 행 수 · 상태 · 분배 기록 첫날 (Q12)"""

    def _run_with_product(self, root: Path, sources: FakeSources, **options: frozenset[str]) -> UpdateResult:
        def products(_updated: Mapping[Path, pd.DataFrame]) -> Products:
            return Products(prices={QQQ_SYNTHETIC: _table(QQQ_CLOSES)}, tables={})

        return _run(root, sources, build_products=products, **options)

    def test_entries_for_fetched_fixed_and_product_files(self, root: Path) -> None:
        """
        목적: 판 요약에 받은 파일 · 고정 파일 · 가공 파일이 모두 적히고, 받은 파일에는 응답의 분배 기록 첫날이 적힌다 —
              사용처가 가져간 사본이 어느 판인지 이 파일로 말한다

        Given: 첫 분배 기록이 2026-10-01 인 QQQ 응답, 합성 하나를 돌려주는 가공
        When: run_update
        Then: 기준일 2026-11-06, QQQ 수정주가 = QQQ · 2026-11-02 ~ 2026-11-06 · 5행 · 흔들림뿐 · 분배 기록 첫날 2026-10-01,
              VFINX = 고정 · 3행, 금리 = 2026-08 ~ 2026-10 · 3행, QQQ 합성 = QQQ · 가공
        """
        # Given
        sources = _normal_sources(QQQ=_response(QQQ_CLOSES, dividends={date(2026, 10, 1): 0.6}))

        # When
        result = self._run_with_product(root, sources)

        # Then
        assert EDITION_PATH in result.written
        edition = _edition(root)
        files = edition[KEY_FILES]
        assert edition[KEY_CUTOFF] == "2026-11-06"
        assert files[QQQ_ADJUSTED.as_posix()] == {
            KEY_TICKER: "QQQ",
            KEY_FIRST_DAY: "2026-11-02",
            KEY_LAST_DAY: "2026-11-06",
            KEY_ROWS: 5,
            KEY_STATUS: STATUS_NOISE,
            KEY_FIRST_DIVIDEND: "2026-10-01",
        }
        assert files[VFINX_ADJUSTED.as_posix()][KEY_STATUS] == STATUS_FIXED
        assert files[VFINX_ADJUSTED.as_posix()][KEY_ROWS] == len(VFINX_CLOSES)
        ffr = files[FFR_FILE.as_posix()]
        assert (ffr[KEY_FIRST_DAY], ffr[KEY_LAST_DAY], ffr[KEY_ROWS]) == ("2026-08", "2026-10", 3)
        assert files[QQQ_SYNTHETIC.as_posix()][KEY_TICKER] == "QQQ"
        assert files[QQQ_SYNTHETIC.as_posix()][KEY_STATUS] == STATUS_PRODUCT

    def test_excluded_and_accepted_status(self, root: Path) -> None:
        """
        목적: 제외한 종목은 옛 기간 그대로 「제외」, 받아들인 종목은 「받아들임」으로 적는다 — 실행 끝 경고가 사라진 뒤에도
              판 요약이 그 판의 예외를 말한다

        Given: QQQ · ^NDX 모두 비정상 응답, --exclude QQQ · --accept ^NDX
        When: run_update
        Then: QQQ 수정주가 = 제외 · 끝날 2026-11-04 · 3행, ^NDX 원본가 = 받아들임
        """
        # Given
        sources = _normal_sources(
            QQQ=_response(QQQ_CLOSES, adjusted=[100.4, *QQQ_CLOSES[1:]]),
            **{"^NDX": _response([1004.0, *NDX_CLOSES[1:]])},
        )

        # When
        self._run_with_product(root, sources, exclude=frozenset({"QQQ"}), accept=frozenset({"^NDX"}))

        # Then
        files = _edition(root)[KEY_FILES]
        qqq = files[QQQ_ADJUSTED.as_posix()]
        assert (qqq[KEY_STATUS], qqq[KEY_LAST_DAY], qqq[KEY_ROWS]) == (STATUS_EXCLUDED, "2026-11-04", 3)
        assert files[NDX_RAW.as_posix()][KEY_STATUS] == STATUS_ACCEPTED

    def test_new_file_status(self, root: Path) -> None:
        """
        목적: 기존 파일이 없던 파일은 「새로」로 적는다 — 첫 판에서 처음 받은 파일과 이어 붙인 파일을 가른다

        Given: QQQ 파일 없음
        When: run_update
        Then: QQQ 원본가 = 새로
        """
        # Given
        (root / QQQ_RAW).unlink()
        (root / QQQ_ADJUSTED).unlink()

        # When
        self._run_with_product(root, _normal_sources())

        # Then
        assert _edition(root)[KEY_FILES][QQQ_RAW.as_posix()][KEY_STATUS] == STATUS_NEW
