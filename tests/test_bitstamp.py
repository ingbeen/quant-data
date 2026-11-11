"""
sources.bitstamp 모듈 테스트 — Bitstamp 일봉 받기 (verify-lab 수집기의 실측 함정을 옮김, 네트워크 없이)

이 파일은 무엇을 검증하나요?
1. 첫 요청이 첫 거래일(2011-08-18 00:00 UTC)부터인가? — 그보다 앞이면 서버가 에러 없이 빈 응답을 준다
2. 덜 찬 페이지에서 멈추지 않고, 시작이 마지막 봉보다 뒤일 때 서버가 다시 주는 최근 봉을 새 봉으로 받지 않는가?
3. UTC 자정이 아닌 봉 · 같은 봉 두 번 · HTTP 오류 · 모양이 다른 응답을 막는가?
4. UTC 로 끝나지 않은 봉을 빼고, 받은 이력의 양 끝과 사이에 빈틈이 있으면 멈추는가? (「지금」은 인자로 받는다)

왜 중요한가요?
잘린 이력 · 진행 중인 봉이 저장되면 에러 없이 비트코인 시세가 틀린다.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime

import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_VOLUME, REQUIRED_COLUMNS
from quant_data.sources import bitstamp
from quant_data.sources.bitstamp import (
    FIRST_TRADE_TIMESTAMP,
    fetch_bitstamp_history,
    fetch_ohlc_history,
    parse_ohlc_rows,
)

DAY = 86_400
FIRST = FIRST_TRADE_TIMESTAMP  # 2011-08-18 00:00 UTC


def _row(timestamp: int, close: float, volume: float = 1.5) -> dict[str, str]:
    """Bitstamp 가 주는 모양의 하루치 행 — 값이 전부 문자열로 온다."""
    value = f"{close:.2f}"
    return {
        "timestamp": str(timestamp),
        "open": value,
        "high": value,
        "low": value,
        "close": value,
        "volume": f"{volume:.8f}",
    }


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _install_pages(monkeypatch: pytest.MonkeyPatch, pages: dict[int, list[dict[str, str]]]) -> list[str]:
    """요청 URL 의 start 로 페이지를 골라 주는 대역 서버 — 목록에 없는 start 는 빈 페이지. 받은 URL 목록을 돌려준다."""
    requested: list[str] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        url = request.full_url
        requested.append(url)
        start = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["start"][0])
        return _FakeResponse(json.dumps({"data": {"ohlc": pages.get(start, [])}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requested


def _start(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["start"][0]


def _at(text: str) -> datetime:
    """UTC 시각."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class TestFetchOhlcHistory:
    """페이지 잇기 · 해석"""

    def test_first_request_starts_at_first_trade_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 첫 요청이 첫 거래일 00:00 UTC 부터 하루 봉을 최대 개수로 묻는다

        Given: 한 행짜리 첫 페이지
        When: fetch_ohlc_history
        Then: 첫 URL 의 start = 1313625600, step = 86400, limit = PAGE_LIMIT
        """
        # Given
        requested = _install_pages(monkeypatch, {FIRST: [_row(FIRST, 10.9)]})

        # When
        fetch_ohlc_history()

        # Then
        query = urllib.parse.parse_qs(urllib.parse.urlparse(requested[0]).query)
        assert query["start"] == ["1313625600"]
        assert query["step"] == [str(DAY)]
        assert query["limit"] == [str(bitstamp.PAGE_LIMIT)]

    def test_rows_are_parsed_into_market_schema(self) -> None:
        """
        목적: 문자열 응답을 시세 표(날짜 + OHLCV 실수)로 바꾼다 — 날짜는 UTC 날짜

        Given: 2011-08-18 00:00 UTC 한 행
        When: parse_ohlc_rows
        Then: 필수 열 순서, 날짜 2011-08-18, 종가 10.9, 거래량 0.48990826
        """
        # When
        frame = parse_ohlc_rows([_row(FIRST, 10.9, volume=0.48990826)])

        # Then
        assert list(frame.columns) == REQUIRED_COLUMNS
        assert frame[COL_DATE].tolist() == [date(2011, 8, 18)]
        assert frame[COL_CLOSE].tolist() == pytest.approx([10.9], abs=1e-12)
        assert frame[COL_VOLUME].tolist() == pytest.approx([0.48990826], abs=1e-12)

    def test_short_page_does_not_end_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 덜 찬 페이지에서 멈추지 않고 새 봉이 없을 때까지 묻는다 — 서버가 덜 주면 뒤가 잘린 채 끝난다

        Given: 첫 페이지 2행 · 둘째 페이지 1행 · 그 뒤 빈 페이지
        When: fetch_ohlc_history
        Then: 3행, 요청 셋의 start 가 앞 페이지 마지막 봉 + 하루
        """
        # Given
        requested = _install_pages(
            monkeypatch,
            {FIRST: [_row(FIRST, 10.0), _row(FIRST + DAY, 11.0)], FIRST + 2 * DAY: [_row(FIRST + 2 * DAY, 12.0)]},
        )

        # When
        frame = fetch_ohlc_history()

        # Then
        assert frame[COL_DATE].tolist() == [date(2011, 8, 18), date(2011, 8, 19), date(2011, 8, 20)]
        assert [_start(url) for url in requested] == [str(FIRST), str(FIRST + 2 * DAY), str(FIRST + 3 * DAY)]

    def test_latest_bar_for_future_start_ends_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 시작이 마지막 봉보다 뒤일 때 서버가 최근 봉을 다시 줘도 새 봉으로 받지 않고 끝난다 (실측 함정)

        Given: 첫 페이지 2행, 다음 시작을 물으면 마지막 봉을 다시 주는 서버
        When: fetch_ohlc_history
        Then: 2행(중복 없음), 요청 둘
        """
        # Given
        latest = _row(FIRST + DAY, 11.0)
        requested = _install_pages(monkeypatch, {FIRST: [_row(FIRST, 10.0), latest], FIRST + 2 * DAY: [latest]})

        # When
        frame = fetch_ohlc_history()

        # Then
        assert frame[COL_DATE].tolist() == [date(2011, 8, 18), date(2011, 8, 19)]
        assert len(requested) == 2

    def test_empty_first_page_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 첫 페이지가 비면 「데이터 없음」이 아니라 멈춘다 — 시작이 첫 거래일보다 앞이면 에러 없이 빈 응답이 온다

        Given: 빈 첫 페이지
        When: fetch_ohlc_history
        Then: ValueError (「빈 응답」)
        """
        # Given
        _install_pages(monkeypatch, {})

        # When & Then
        with pytest.raises(ValueError, match="빈 응답"):
            fetch_ohlc_history()

    def test_off_midnight_timestamp_raises(self) -> None:
        """
        목적: UTC 자정이 아닌 봉은 하루 봉으로 받지 않는다 — 봉의 하루가 바뀌면 Coin Metrics 와 조용히 어긋난다

        Given: 자정에서 1시간 벗어난 시각
        When: parse_ohlc_rows
        Then: ValueError (「자정」)
        """
        with pytest.raises(ValueError, match="자정"):
            parse_ohlc_rows([_row(FIRST + 3_600, 10.0)])

    def test_duplicate_timestamps_keep_one_row(self) -> None:
        """
        목적: 같은 봉이 두 번 와도 한 행만 남는다

        Given: 같은 시각 두 행
        When: parse_ohlc_rows
        Then: 한 행
        """
        assert len(parse_ohlc_rows([_row(FIRST, 10.0), _row(FIRST, 10.0)])) == 1

    def test_http_error_is_translated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: HTTP 오류를 상태 코드와 함께 ValueError 로 올린다

        Given: HTTP 429 를 주는 서버
        When: fetch_ohlc_history
        Then: ValueError (「429」)
        """

        # Given
        def fake_urlopen(request: object, timeout: float | None = None) -> None:
            raise urllib.error.HTTPError("https://example.invalid", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        # When & Then
        with pytest.raises(ValueError, match="429"):
            fetch_ohlc_history()

    def test_malformed_response_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 모양이 다른 응답을 빈 결과로 넘기지 않는다

        Given: data.ohlc 가 없는 JSON
        When: fetch_ohlc_history
        Then: ValueError (「응답」)
        """
        # Given
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: _FakeResponse(b'{"code": "API0001", "errors": []}')
        )

        # When & Then
        with pytest.raises(ValueError, match="응답"):
            fetch_ohlc_history()


class TestFetchBitstampHistory:
    """끝나지 않은 봉 · 빈틈 — 「지금」은 받기 전에 잰 값을 인자로"""

    def test_unfinished_utc_day_is_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: UTC 로 끝나지 않은 봉은 뺀다 — 한국 시각 09:00 에 하루가 바뀐다

        Given: 08-18 ~ 08-21 네 봉, 지금 UTC 2011-08-21 00:30 (08-21 봉은 진행 중)
        When: fetch_bitstamp_history
        Then: 08-18 ~ 08-20 세 행
        """
        # Given
        _install_pages(monkeypatch, {FIRST: [_row(FIRST + i * DAY, 10.0 + i) for i in range(4)]})

        # When
        frame = fetch_bitstamp_history(_at("2011-08-21T00:30:00"))

        # Then
        assert frame[COL_DATE].tolist() == [date(2011, 8, 18), date(2011, 8, 19), date(2011, 8, 20)]

    @pytest.mark.parametrize(
        ("rows", "now", "pattern"),
        [
            ([0, 1, 3], "2011-08-22T00:30:00", "빠진 날"),
            ([1, 2, 3], "2011-08-22T00:30:00", "시작"),
            ([0, 1, 2], "2011-08-25T00:30:00", "끝"),
        ],
        ids=["gap", "late_start", "early_end"],
    )
    def test_incomplete_history_raises(
        self, monkeypatch: pytest.MonkeyPatch, rows: list[int], now: str, pattern: str
    ) -> None:
        """
        목적: 사이에 빠진 날 · 첫 거래일에서 시작하지 않음 · 끝난 마지막 날에 닿지 않음이면 멈춘다 — 비트코인은 휴장이
              없어 빠진 날은 소스의 결함이고, 잘린 이력이 전체 파일을 덮으면 안 된다

        Given: 첫 거래일에서 rows 번째 날들의 봉, 지금 now
        When: fetch_bitstamp_history
        Then: ValueError (빠진 날 / 시작 / 끝)
        """
        # Given
        _install_pages(monkeypatch, {FIRST: [_row(FIRST + i * DAY, 10.0 + i) for i in rows]})

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            fetch_bitstamp_history(_at(now))

    def test_now_without_timezone_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 시간대 없는 「지금」은 받지 않는다 — PC 의 시간대로 읽히면 PC 마다 끝난 날의 경계가 하루 갈린다

        Given: 시간대 없는 시각
        When: fetch_bitstamp_history
        Then: ValueError (「시간대」)
        """
        # Given
        _install_pages(monkeypatch, {FIRST: [_row(FIRST, 10.0)]})

        # When & Then
        with pytest.raises(ValueError, match="시간대"):
            fetch_bitstamp_history(datetime(2011, 8, 19, 0, 30))
