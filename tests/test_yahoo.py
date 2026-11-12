"""
sources.yahoo 모듈 테스트 — 야후 받기 · 수정 가격(C-1) · 받을 마지막 날

이 파일은 무엇을 검증하나요?
1. 전체 기간을 원본가로 받고(auto_adjust=False), 조회 실패가 빈 결과가 아니라 예외로 오는가(raise_errors=True)?
2. 한 응답에서 원본가 · 수정주가 · 배당 · 분할 기록을 함께 돌려주고 파일은 쓰지 않는가? (결정 Q17)
3. 응답에 기록 열이 없거나 비었으면 멈추는가?
4. 받을 마지막 날이 기본(그저께) · --end(뉴욕에서 그날 봉이 끝나기 전인 날은 뺀다)대로 정해지는가?
5. 수정 가격이 yfinance auto_adjust 와 같은 식인가? (C-1)

왜 중요한가요?
auto_adjust 의 라이브러리 기본값은 True 라 인자를 빠뜨리면 수정주가가 원본가 자리에 조용히 저장된다.
배당 · 분할 기록과 원본 종가가 같은 응답에서 와야 다시 받은 시세의 변화를 기록과 맞춰 볼 수 있다.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, REQUIRED_COLUMNS
from quant_data.sources import yahoo
from quant_data.sources.yahoo import (
    COL_ADJ_CLOSE,
    COL_DIVIDENDS,
    COL_STOCK_SPLITS,
    adjust_prices,
    fetch_yahoo,
    resolve_cutoff_date,
)

SEOUL = ZoneInfo("Asia/Seoul")
DATES = [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)]


def _history(
    adj_close: list[float] | None = None,
    dividends: list[float] | None = None,
    splits: list[float] | None = None,
) -> pd.DataFrame:
    """history(auto_adjust=False) 모양 — 날짜가 인덱스, 원본가 · 수정 종가 · 배당 · 분할 열."""
    closes = [103.0, 104.0, 105.0]
    df = pd.DataFrame(
        {
            COL_OPEN: [100.0, 101.0, 102.0],
            COL_HIGH: [105.0, 106.0, 107.0],
            COL_LOW: [99.0, 100.0, 101.0],
            COL_CLOSE: closes,
            COL_ADJ_CLOSE: adj_close if adj_close is not None else closes,
            COL_VOLUME: [1000000, 1100000, 1200000],
            COL_DIVIDENDS: dividends if dividends is not None else [0.0, 0.0, 0.0],
            COL_STOCK_SPLITS: splits if splits is not None else [0.0, 0.0, 0.0],
        },
        index=pd.to_datetime(DATES),
    )
    df.index.name = COL_DATE
    return df


def _mock_ticker(monkeypatch: pytest.MonkeyPatch, history: pd.DataFrame) -> MagicMock:
    ticker = MagicMock()
    ticker.history.return_value = history
    monkeypatch.setattr("quant_data.sources.yahoo.yf.Ticker", lambda _: ticker)
    return ticker


class TestFetchYahoo:
    """야후 받기 — 한 응답에서 원본가 · 수정주가 · 배당 · 분할, 파일은 쓰지 않는다"""

    def test_requests_full_period_raw_with_errors_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 결과를 좌우하는 인자를 기본값에 맡기지 않는다 — 전체 기간 · 원본가 · 실패는 예외

        Given: 대역 응답
        When: fetch_yahoo("TEST")
        Then: history 가 period="max", auto_adjust=False, raise_errors=True 로 한 번 불린다
        """
        # Given
        ticker = _mock_ticker(monkeypatch, _history())

        # When
        fetch_yahoo("TEST")

        # Then
        ticker.history.assert_called_once_with(period="max", auto_adjust=False, raise_errors=True)

    def test_raw_and_adjusted_from_one_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 원본가는 응답의 원본가 그대로, 수정주가는 같은 응답의 C-1 이다 — 둘이 다른 응답에서 오면
              배당 기록과 수정 비율이 어긋날 수 있다

        Given: 원본 종가 103 · 104 · 105, 수정 종가 101 · 102 · 105
        When: fetch_yahoo
        Then: raw = 원본가(REQUIRED_COLUMNS, 날짜는 date), adjusted = adjust_prices(응답), 둘 다 3행
        """
        # Given
        history = _history(adj_close=[101.0, 102.0, 105.0])
        _mock_ticker(monkeypatch, history)

        # When
        response = fetch_yahoo("TEST")

        # Then
        assert list(response.raw.columns) == REQUIRED_COLUMNS
        assert response.raw[COL_DATE].tolist() == DATES
        assert response.raw[COL_CLOSE].tolist() == [103.0, 104.0, 105.0]
        assert response.adjusted[COL_CLOSE].tolist() == [101.0, 102.0, 105.0]
        flat = history.reset_index()
        flat[COL_DATE] = flat[COL_DATE].dt.date
        pd.testing.assert_frame_equal(response.adjusted, adjust_prices(flat))

    def test_events_hold_only_days_with_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 배당 · 분할 기록은 값이 있는 날만, 원본 종가는 응답 전체 — 판정이 기록 날짜로 계단을 맞춘다

        Given: 2023-01-03 배당 $0.50, 2023-01-04 2배 분할
        When: fetch_yahoo
        Then: dividends = {01-03: 0.5}, splits = {01-04: 2.0}, raw_close = 세 날의 원본 종가
        """
        # Given
        _mock_ticker(monkeypatch, _history(dividends=[0.0, 0.5, 0.0], splits=[0.0, 0.0, 2.0]))

        # When
        events = fetch_yahoo("TEST").events

        # Then
        assert events.dividends.to_dict() == {date(2023, 1, 3): 0.5}
        assert events.splits.to_dict() == {date(2023, 1, 4): 2.0}
        assert events.raw_close.to_dict() == {DATES[0]: 103.0, DATES[1]: 104.0, DATES[2]: 105.0}

    def test_does_not_write_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """
        목적: 받기는 파일을 쓰지 않는다 — 쓰기는 모든 받기 · 판정이 끝난 뒤 갱신이 한꺼번에 한다(결정 Q17)

        Given: 빈 실행 위치(임시 폴더)
        When: fetch_yahoo
        Then: 실행 위치에 아무 파일도 생기지 않는다
        """
        # Given
        _mock_ticker(monkeypatch, _history())
        monkeypatch.chdir(tmp_path)

        # When
        fetch_yahoo("TEST")

        # Then
        assert list(tmp_path.iterdir()) == []

    def test_missing_action_columns_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 응답에 수정 종가 · 배당 · 분할 열이 없으면 판정할 수 없어 멈춘다

        Given: Dividends 열이 없는 응답
        When: fetch_yahoo
        Then: ValueError (열 이름 포함)
        """
        # Given
        _mock_ticker(monkeypatch, _history().drop(columns=[COL_DIVIDENDS]))

        # When & Then
        with pytest.raises(ValueError, match=COL_DIVIDENDS):
            fetch_yahoo("TEST")

    def test_empty_data_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 빈 응답이면 멈춘다 — 빈 표를 넘기면 판정이 「날짜가 모두 사라짐」으로 엉뚱한 원인을 낸다

        Given: 빈 DataFrame 응답
        When: fetch_yahoo
        Then: ValueError (「데이터를 찾을 수 없습니다」)
        """
        # Given
        _mock_ticker(monkeypatch, pd.DataFrame())

        # When & Then
        with pytest.raises(ValueError, match="데이터를 찾을 수 없습니다"):
            fetch_yahoo("INVALID_TICKER")


class TestResolveCutoffDate:
    """받을 마지막 날 — 인자 없으면 그저께, `--end` 는 뉴욕에서 그날 봉이 끝나기 전인 날을 뺀다"""

    def test_default_is_two_days_before_today(self) -> None:
        """
        목적: `--end` 가 없으면 실행한 날(현지)에서 2일 전까지

        Given: 지금 2026-11-07 20:00 KST
        When: resolve_cutoff_date(None, 지금)
        Then: 2026-11-05
        """
        # Given
        now = datetime(2026, 11, 7, 20, 0, tzinfo=SEOUL)

        # When & Then
        assert resolve_cutoff_date(None, now) == date(2026, 11, 5)

    def test_past_end_date_is_kept(self) -> None:
        """
        목적: 이미 마감된 날을 주면 그날까지

        Given: 지금 2026-11-07 20:00 KST, --end 2026-11-03
        When: resolve_cutoff_date
        Then: 2026-11-03
        """
        # Given
        now = datetime(2026, 11, 7, 20, 0, tzinfo=SEOUL)

        # When & Then
        assert resolve_cutoff_date(date(2026, 11, 3), now) == date(2026, 11, 3)

    @pytest.mark.parametrize(
        ("utc_now", "expected"),
        [
            (datetime(2026, 11, 6, 21, 30, tzinfo=UTC), date(2026, 11, 5)),  # 뉴욕 16:30 EST — 주식은 끝, 금 선물은 거래 중
            (datetime(2026, 11, 6, 22, 59, tzinfo=UTC), date(2026, 11, 5)),  # 뉴욕 17:59 EST — 그날 봉이 끝나기 전
            (datetime(2026, 11, 6, 23, 0, tzinfo=UTC), date(2026, 11, 6)),  # 뉴욕 18:00 EST — 그날 봉이 다 끝남
            (datetime(2026, 7, 1, 21, 59, tzinfo=UTC), date(2026, 6, 30)),  # 뉴욕 17:59 EDT — 서머타임, 끝나기 전
            (datetime(2026, 7, 1, 22, 0, tzinfo=UTC), date(2026, 7, 1)),  # 뉴욕 18:00 EDT — 서머타임, 다 끝남
        ],
    )
    def test_today_is_capped_by_new_york_day_end(self, utc_now: datetime, expected: date) -> None:
        """
        목적: 한국에서 `--end` 에 오늘을 주면 뉴욕에서 그날 봉이 다 끝난 마지막 날까지 — 거래 중인 봉을 저장하지 않는다.
              주식이 끝난 뒤에도 금 선물(GC=F)은 거래 중이라 그 사이는 뺀다. 서머타임 경계도 시간대 자료로 맞게 가른다

        Given: 한국 시각으로 바꾼 지금, --end = 그 한국 날짜(오늘)
        When: resolve_cutoff_date
        Then: 뉴욕 18:00 전이면 뉴욕 어제, 이후면 뉴욕 오늘
        """
        # Given
        now = utc_now.astimezone(SEOUL)

        # When & Then
        assert resolve_cutoff_date(now.date(), now) == expected

    def test_future_end_date_raises(self) -> None:
        """
        목적: 오늘보다 뒤의 날은 받을 수 없어 멈춘다 — 오타를 조용히 오늘로 바꾸지 않는다

        Given: 지금 2026-11-07 20:00 KST, --end 2026-11-08
        When: resolve_cutoff_date
        Then: ValueError (「오늘」 포함)
        """
        # Given
        now = datetime(2026, 11, 7, 20, 0, tzinfo=SEOUL)

        # When & Then
        with pytest.raises(ValueError, match="오늘"):
            resolve_cutoff_date(date(2026, 11, 8), now)

    def test_naive_now_raises(self) -> None:
        """
        목적: 시간대 없는 시각은 뉴욕 마감을 가를 수 없어 멈춘다

        Given: 시간대 없는 지금
        When: resolve_cutoff_date
        Then: ValueError (「시간대」 포함)
        """
        # When & Then
        with pytest.raises(ValueError, match="시간대"):
            resolve_cutoff_date(None, datetime(2026, 11, 7, 20, 0))

    def test_missing_new_york_zone_raises_with_guidance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 뉴욕 시간대 자료가 없는 컴퓨터에서는 무엇을 설치할지 알리고 멈춘다

        Given: ZoneInfo 가 ZoneInfoNotFoundError 를 내도록 바꿈
        When: resolve_cutoff_date(--end 있음)
        Then: ZoneInfoNotFoundError (「뉴욕 시간대」 · 「tzdata」 포함)
        """

        # Given
        def missing_zone(_key: str) -> ZoneInfo:
            raise ZoneInfoNotFoundError("없음")

        monkeypatch.setattr(yahoo, "ZoneInfo", missing_zone)
        now = datetime(2026, 11, 7, 20, 0, tzinfo=SEOUL)

        # When & Then
        with pytest.raises(ZoneInfoNotFoundError, match="뉴욕 시간대.*tzdata"):
            resolve_cutoff_date(date(2026, 11, 6), now)


class TestAdjustPrices:
    """수정 가격(C-1) — yfinance auto_adjust 와 같은 식"""

    def test_scales_open_high_low_by_adj_close_ratio(self) -> None:
        """
        목적: 시가 · 고가 · 저가 × (수정 종가 ÷ 원본 종가), 종가 = 수정 종가, 거래량 그대로 — auto_adjust=True 로 받던 값과 같다

        Given: 원본 시가 101 · 고가 102 · 저가 99 · 종가 100, 수정 종가 98, 거래량 5000
        When: adjust_prices
        Then: 열 = REQUIRED_COLUMNS, 시가 98.98 · 고가 99.96 · 저가 97.02 · 종가 98.0 · 거래량 5000 (손 계산)
        """
        # Given
        raw = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2)],
                COL_OPEN: [101.0],
                COL_HIGH: [102.0],
                COL_LOW: [99.0],
                COL_CLOSE: [100.0],
                COL_ADJ_CLOSE: [98.0],
                COL_VOLUME: [5000],
                COL_DIVIDENDS: [0.0],
                COL_STOCK_SPLITS: [0.0],
            }
        )

        # When
        adjusted = adjust_prices(raw)

        # Then
        assert list(adjusted.columns) == REQUIRED_COLUMNS
        row = adjusted.iloc[0]
        assert row[COL_OPEN] == pytest.approx(98.98, abs=1e-12)
        assert row[COL_HIGH] == pytest.approx(99.96, abs=1e-12)
        assert row[COL_LOW] == pytest.approx(97.02, abs=1e-12)
        assert row[COL_CLOSE] == 98.0
        assert row[COL_VOLUME] == 5000
