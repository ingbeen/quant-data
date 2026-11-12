"""
sources.coinmetrics 모듈 테스트 — Coin Metrics 커뮤니티 API 일별 지표 받기 (verify-lab 수집기의 실측 함정을 옮김)

이 파일은 무엇을 검증하나요?
1. 첫 요청이 오래된 행부터(paging_from=start)인가? — 주지 않으면 최신 행부터 와 한 페이지만 받으면 최근 구간만 남는다
2. next_page_url 을 끝까지 따라가고, 제자리를 도는 다음 URL 은 멈추는가?
3. UTC 자정이 아닌 시각 · 빈 응답 · 값이 없는 행 · 0 이하 값을 막는가?
4. UTC 로 끝나지 않은 날을 빼고, 첫 날 · 끝(하루 공개 지연 허용) · 사이의 빈틈을 보는가? (「지금」은 인자로)

왜 중요한가요?
Coin Metrics 기준가는 Bitstamp 일봉의 교차 확인 상대다 — 하루 밀리거나 잘리면 대조가 에러 없이 틀린다.
"""

import json
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from typing import Any

import pytest

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.sources.coinmetrics import fetch_coinmetrics_series, first_page_url, parse_metric_rows

METRIC = "PriceUSD"
NEXT_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?next_page_token=abc"


def _row(day: str, value: str | None) -> dict[str, Any]:
    """Coin Metrics 가 주는 모양의 하루치 행 — 값이 문자열로 오고, 없으면 키 자체가 없다."""
    row: dict[str, Any] = {"asset": "btc", "time": f"{day}T00:00:00.000000000Z"}
    if value is not None:
        row[METRIC] = value
    return row


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _install(
    monkeypatch: pytest.MonkeyPatch, first: dict[str, Any], others: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    """첫 요청은 first, others 에 든 URL 은 그 응답을 주는 대역 서버. 받은 URL 목록을 돌려준다."""
    requested: list[str] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        url = request.full_url
        requested.append(url)
        payload = (others or {}).get(url, first)
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return requested


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class TestPaging:
    """요청 · 페이지 잇기"""

    def test_first_page_url_asks_oldest_first(self) -> None:
        """
        목적: 첫 요청이 오래된 행부터 하루 단위 최대 페이지로 묻는다

        Given: 지표 PriceUSD
        When: first_page_url
        Then: paging_from=start · page_size=10000 · frequency=1d · assets=btc · metrics=PriceUSD
        """
        # When
        query = urllib.parse.parse_qs(urllib.parse.urlparse(first_page_url(METRIC)).query)

        # Then
        assert query["paging_from"] == ["start"]
        assert query["page_size"] == ["10000"]
        assert query["frequency"] == ["1d"]
        assert query["assets"] == ["btc"]
        assert query["metrics"] == [METRIC]

    def test_pages_followed_until_no_next_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: next_page_url 이 없을 때까지 따라간다

        Given: 첫 페이지 2행 + 다음 URL, 둘째 페이지 1행
        When: fetch_coinmetrics_series(지금 2010-07-21 00:30 UTC)
        Then: 3행, 둘째 요청이 다음 URL
        """
        # Given
        requested = _install(
            monkeypatch,
            {"data": [_row("2010-07-18", "0.0858"), _row("2010-07-19", "0.0808")], "next_page_url": NEXT_URL},
            {NEXT_URL: {"data": [_row("2010-07-20", "0.0747")]}},
        )

        # When
        frame = fetch_coinmetrics_series(METRIC, _at("2010-07-21T00:30:00"))

        # Then
        assert len(frame) == 3
        assert requested[1] == NEXT_URL

    def test_repeating_next_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 다음 URL 이 방금 받은 URL 과 같으면 멈춘다 — 같은 페이지를 끝없이 받는다

        Given: 둘째 페이지의 다음 URL 이 자기 자신
        When: fetch_coinmetrics_series
        Then: ValueError (「나아가지 않」)
        """
        # Given
        _install(
            monkeypatch,
            {"data": [_row("2010-07-18", "0.0858")], "next_page_url": NEXT_URL},
            {NEXT_URL: {"data": [_row("2010-07-19", "0.0808")], "next_page_url": NEXT_URL}},
        )

        # When & Then
        with pytest.raises(ValueError, match="나아가지 않"):
            fetch_coinmetrics_series(METRIC, _at("2010-07-21T00:30:00"))


class TestParse:
    """해석"""

    def test_rows_are_parsed_into_series_schema(self) -> None:
        """
        목적: 행을 일별 시계열(날짜 · 값)로 바꾼다 — 날짜는 그 값의 UTC 날짜

        Given: 2010-07-18 한 행
        When: parse_metric_rows
        Then: 열 [Date, Value], 날짜 2010-07-18, 값 0.0858
        """
        # When
        frame = parse_metric_rows([_row("2010-07-18", "0.0858")], METRIC)

        # Then
        assert list(frame.columns) == [COL_DATE, COL_VALUE]
        assert frame[COL_DATE].tolist() == [date(2010, 7, 18)]
        assert frame[COL_VALUE].tolist() == pytest.approx([0.0858], abs=1e-12)

    @pytest.mark.parametrize(
        ("rows", "pattern"),
        [
            ([{"asset": "btc", "time": "2010-07-18T12:00:00.000000000Z", METRIC: "1"}], "자정"),
            ([], "비어"),
        ],
        ids=["off_midnight", "empty"],
    )
    def test_bad_rows_raise(self, rows: list[dict[str, Any]], pattern: str) -> None:
        """
        목적: UTC 자정이 아닌 시각 · 빈 응답은 멈춘다

        Given: 12:00Z 행 / 빈 목록
        When: parse_metric_rows
        Then: ValueError
        """
        with pytest.raises(ValueError, match=pattern):
            parse_metric_rows(rows, METRIC)


class TestFetchSeries:
    """끝나지 않은 날 · 빈틈 · 값의 범위"""

    def test_unfinished_day_excluded_and_one_day_lag_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: UTC 로 끝나지 않은 날은 빼고, 끝난 마지막 날의 값이 아직 없어도 하루는 기다린다 — Coin Metrics 는 d 의 값을
              d+1 일 UTC 02:28 ~ 03:32 에 완성한다(verify-lab 실측)

        Given: 07-18 · 07-19 두 행 + 진행 중인 07-21 행, 지금 UTC 07-21 00:30 (끝난 마지막 날 07-20 은 아직 없음)
        When: fetch_coinmetrics_series
        Then: 07-18 · 07-19 두 행
        """
        # Given
        _install(
            monkeypatch,
            {"data": [_row("2010-07-18", "0.0858"), _row("2010-07-19", "0.0808"), _row("2010-07-21", "0.07")]},
        )

        # When — 07-21 행은 끝나지 않은 날이라 빠지고, 07-19 끝은 하루 지연 안
        frame = fetch_coinmetrics_series(METRIC, _at("2010-07-21T00:30:00"))

        # Then
        assert frame[COL_DATE].tolist() == [date(2010, 7, 18), date(2010, 7, 19)]

    @pytest.mark.parametrize(
        ("rows", "now", "pattern"),
        [
            ([("2010-07-18", "0.0858"), ("2010-07-20", "0.0747")], "2010-07-21T00:30:00", "빠진 날"),
            ([("2010-07-19", "0.0808"), ("2010-07-20", "0.0747")], "2010-07-21T00:30:00", "시작"),
            ([("2010-07-18", "0.0858"), ("2010-07-19", "0.0808")], "2010-07-22T00:30:00", "끝"),
            ([("2010-07-18", "0.0858"), ("2010-07-19", None)], "2010-07-20T00:30:00", "결측"),
            ([("2010-07-18", "0.0858"), ("2010-07-19", "0")], "2010-07-20T00:30:00", "양수"),
        ],
        ids=["gap", "late_start", "beyond_lag", "missing_value", "zero"],
    )
    def test_bad_history_raises(
        self, monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str | None]], now: str, pattern: str
    ) -> None:
        """
        목적: 빈틈 · 늦은 시작 · 하루 지연을 넘은 끝 · 값 없는 행 · 0 이하 값이면 멈춘다 — 값을 메우지 않는다

        Given: rows, 지금 now
        When: fetch_coinmetrics_series
        Then: ValueError
        """
        # Given
        _install(monkeypatch, {"data": [_row(day, value) for day, value in rows]})

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            fetch_coinmetrics_series(METRIC, _at(now))
