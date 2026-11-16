"""
sources.fear_greed 모듈 테스트 — CNN 공포탐욕지수 공개 결합본 받기

이 파일은 무엇을 검증하나요?
1. 결합본 CSV(Date · Fear Greed · Rating)를 계열(Date · Value)로 바꾸는가? Rating 은 버리고 값은 그대로인가?
2. 0 ~ 100 밖의 값 · 결측 · 중복 날짜 · 다른 헤더에서 멈추는가? 0 · 100 은 받는가? (0 인 날이 실재한다 — 2014-10-13)
3. 받기가 결합본 URL 하나를 묻고, HTTP 오류를 알아볼 수 있는 ValueError 로 바꾸는가?

왜 중요한가요?
CNN 은 과거 시계열을 내지 않아 이 결합본이 유일한 긴 출처다. 저장소가 모양을 바꾸면 값이 에러 없이 다른 칸에서 읽힐 수 있다.
"""

import urllib.error
import urllib.request
from datetime import date

import pytest

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.sources.fear_greed import FEAR_GREED_URL, fetch_fear_greed, parse_fear_greed_csv

HEADER = "Date,Fear Greed,Rating"


def _csv(*rows: str) -> str:
    return "\n".join((HEADER, *rows)) + "\n"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestParse:
    """결합본 CSV → 계열"""

    def test_converts_to_date_value(self) -> None:
        """
        목적: 결합본의 두 시기(복원본 정수 · CNN 피드 소수)를 같은 계열로 바꾸고 Rating 을 버린다

        Given: 정수 값 하루 · 소수 13자리 값 하루 (순서를 거꾸로 둠)
        When: parse_fear_greed_csv
        Then: Date · Value 두 열 · 날짜 오름차순 · 값 그대로
        """
        # Given
        text = _csv("2021-02-01,35.9428571428571,fear", "2011-01-03,68.0,greed")

        # When
        frame = parse_fear_greed_csv(text)

        # Then
        assert list(frame.columns) == [COL_DATE, COL_VALUE]
        assert frame[COL_DATE].tolist() == [date(2011, 1, 3), date(2021, 2, 1)]
        assert frame[COL_VALUE].tolist() == pytest.approx([68.0, 35.9428571428571], abs=1e-12)

    def test_accepts_range_edges(self) -> None:
        """
        목적: 범위 양 끝(0 · 100)은 받는다 — 0 인 날이 실재한다(2014-10-13)

        Given: 값 0 · 100
        When: parse_fear_greed_csv
        Then: 두 행 그대로
        """
        # Given
        text = _csv("2014-10-13,0.0,extreme fear", "2014-10-14,100.0,extreme greed")

        # When
        frame = parse_fear_greed_csv(text)

        # Then
        assert frame[COL_VALUE].tolist() == pytest.approx([0.0, 100.0], abs=1e-12)

    def test_rejects_row_with_extra_field(self) -> None:
        """
        목적: 칸이 헤더보다 많은 행은 값을 옆 칸에서 읽게 된다(pandas 가 첫 칸을 인덱스로 돌림) — 멈춘다

        Given: 칸이 넷인 행
        When: parse_fear_greed_csv
        Then: ValueError (칸 수)
        """
        # Given
        text = _csv("2011-01-03,2011-01-05,68.0,greed")

        # When / Then
        with pytest.raises(ValueError, match="칸 수"):
            parse_fear_greed_csv(text)

    @pytest.mark.parametrize("day", ["", "2011/01/04", "2011-01-04T00:00:00-05:00"])
    def test_rejects_blank_or_other_date_format(self, day: str) -> None:
        """
        목적: 빈 날짜 · 다른 형식은 결측(NaT)으로 남아 뒤의 기준일 자르기에서 조용히 빠진다 — 받기에서 멈춘다

        Given: 그런 날짜의 행
        When: parse_fear_greed_csv
        Then: ValueError (날짜 형식)
        """
        # Given
        text = _csv("2011-01-03,68.0,greed", f"{day},50.0,neutral")

        # When / Then
        with pytest.raises(ValueError, match="YYYY|%Y-%m-%d"):
            parse_fear_greed_csv(text)

    @pytest.mark.parametrize("value", ["-0.1", "100.1"])
    def test_rejects_out_of_range(self, value: str) -> None:
        """
        목적: 0 ~ 100 밖의 값은 지수가 아니다 — 멈춘다

        Given: 범위 밖 값 하루
        When: parse_fear_greed_csv
        Then: ValueError
        """
        # Given
        text = _csv("2011-01-03,68.0,greed", f"2011-01-04,{value},fear")

        # When / Then
        with pytest.raises(ValueError, match="0 ~ 100"):
            parse_fear_greed_csv(text)

    def test_rejects_missing_value(self) -> None:
        """
        목적: 값이 비거나 숫자가 아니면 메우지 않고 멈춘다

        Given: 값이 빈 날 · 숫자가 아닌 날
        When: parse_fear_greed_csv
        Then: ValueError (결측)
        """
        # Given
        text = _csv("2011-01-03,,greed", "2011-01-04,abc,fear")

        # When / Then
        with pytest.raises(ValueError, match="결측"):
            parse_fear_greed_csv(text)

    def test_rejects_duplicate_dates(self) -> None:
        """
        목적: 같은 날이 둘이면 어느 값이 맞는지 고르지 않고 멈춘다

        Given: 같은 날 두 행
        When: parse_fear_greed_csv
        Then: ValueError (중복 날짜)
        """
        # Given
        text = _csv("2011-01-03,68.0,greed", "2011-01-03,67.0,greed")

        # When / Then
        with pytest.raises(ValueError, match="중복 날짜"):
            parse_fear_greed_csv(text)

    def test_rejects_other_header(self) -> None:
        """
        목적: 헤더가 다르면 저장소가 모양을 바꾼 것이다 — 값을 다른 칸에서 읽지 않게 멈춘다

        Given: 열 이름이 다른 CSV
        When: parse_fear_greed_csv
        Then: ValueError (헤더)
        """
        # Given
        text = "Date,Score,Rating\n2011-01-03,68.0,greed\n"

        # When / Then
        with pytest.raises(ValueError, match="헤더"):
            parse_fear_greed_csv(text)

    def test_rejects_empty(self) -> None:
        """
        목적: 행이 없는 응답은 받은 것이 아니다 — 빈 계열로 넘기지 않는다

        Given: 헤더만 있는 CSV
        When: parse_fear_greed_csv
        Then: ValueError (비어 있음)
        """
        with pytest.raises(ValueError, match="비어"):
            parse_fear_greed_csv(HEADER + "\n")


class TestFetch:
    """받기 — 결합본 URL 하나"""

    def test_requests_canonical_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 결합본의 대표 파일 하나를 묻고 그 응답을 계열로 돌려준다

        Given: 대역 서버(정상 CSV)
        When: fetch_fear_greed
        Then: 물은 URL 이 FEAR_GREED_URL 하나 · 계열 두 행
        """
        # Given
        requested: list[str] = []

        def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
            requested.append(request.full_url)
            return _FakeResponse(_csv("2011-01-03,68.0,greed", "2011-01-04,70.0,greed").encode("utf-8"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        # When
        frame = fetch_fear_greed()

        # Then
        assert requested == [FEAR_GREED_URL]
        assert len(frame) == 2

    def test_http_error_becomes_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 저장소가 사라지면(HTTP 404) 무엇이 실패했는지 알 수 있게 멈춘다

        Given: 404 를 내는 대역 서버
        When: fetch_fear_greed
        Then: ValueError (HTTP 오류 · 상태 코드)
        """

        # Given
        def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        # When / Then
        with pytest.raises(ValueError, match="404"):
            fetch_fear_greed()
