"""금 대용 시세 테스트

GLD 상장 전 구간을 채우는 금값 사슬의 계약을 검증한다.
Perth Mint 금값 · FRED 일별 환율의 파싱과 저장, 미국 날짜 붙이기, 「호주달러 × 환율 → Perth 달러 → 금 선물」 사슬을 다룬다.

왜 중요한가요?
금값은 미국 장이 열리기 전(호주 낮)에 정해진다. 미국 날짜에 붙일 호주 날짜가 하루만 어긋나도 금과 주식의
움직임이 다른 날로 밀려, 그 시세로 도는 포트폴리오의 리밸런싱 · 낙폭이 조용히 틀린다(근거: docs/research/합성_시세_연장.md 6.4).
사슬의 이음매 뒤 행이 원본과 한 행이라도 다르면 실물 구간까지 틀린다.
"""

import math
from datetime import date
from pathlib import Path
from urllib.request import Request

import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, REQUIRED_COLUMNS
from quant_data.synthetic import gold_proxy
from quant_data.synthetic.gold_proxy import (
    COL_AUD_ASK,
    COL_AUD_BID,
    COL_SOURCE_DATE,
    COL_SOURCE_VALUE,
    COL_USD_ASK,
    COL_USD_BID,
    FRED_AUD_USD_CSV_URL,
    PERTH_MINT_GOLD_CSV_URL,
    USER_AGENT,
    build_gold_proxy,
    download_gold_proxy_sources,
    load_gold_proxy_sources,
    parse_fred_daily_csv,
    parse_perth_mint_gold_csv,
    save_gold_proxy_sources,
)

REL_TOL = 1e-12

# Perth Mint 보관 CSV 의 헤더 다섯 줄 — 열 순서는 실제 파일과 다르게 둬 «열 이름으로» 찾는지 본다
PERTH_HEADER = (
    "Market,Perth Mint Spot,Perth Mint Spot,Perth Mint Spot,Perth Mint Spot,Perth Mint Spot,Perth Mint Spot,Lease Rates\n"
    "Metal/Currency,Gold,Gold,Gold,Gold,Gold,Gold,6 Month\n"
    "Priced In,USD,USD,AUD,AUD,USD,USD,Gold\n"
    "Price Type,Bid,Ask,Bid,Ask,Bid,Ask,% pa\n"
    "Summary,High,High,Average,Average,Average,Average,\n"
)


def _perth_row(day: str, aud: tuple[str, str] | None, usd: tuple[str, str] | None) -> str:
    """Perth CSV 의 데이터 한 줄 — High 칸은 Average 와 다른 값을 넣어 Average 를 읽는지 본다."""
    aud_cells = [f'"{v}"' for v in aud] if aud else ["", ""]
    usd_cells = list(usd) if usd else ["", ""]
    high_cells = ["999.0", "999.5"] if usd else ["", ""]
    return ",".join([day, *high_cells, *aud_cells, *usd_cells, ""]) + "\n"


FRED_HEADER = "observation_date,DEXUSAL\n"


def _perth_frame(rows: list[tuple[date, float | None, float | None]]) -> pd.DataFrame:
    """저장 형식의 Perth 표 — (호주 날짜, 호주달러 bid · ask 중간, 달러 중간). bid · ask 는 중간 ± 0.5"""
    return pd.DataFrame(
        {
            COL_SOURCE_DATE: [d for d, _, _ in rows],
            COL_AUD_BID: [None if a is None else a - 0.5 for _, a, _ in rows],
            COL_AUD_ASK: [None if a is None else a + 0.5 for _, a, _ in rows],
            COL_USD_BID: [None if u is None else u - 0.5 for _, _, u in rows],
            COL_USD_ASK: [None if u is None else u + 0.5 for _, _, u in rows],
        }
    ).astype({COL_AUD_BID: float, COL_AUD_ASK: float, COL_USD_BID: float, COL_USD_ASK: float})


def _fx_frame(rows: list[tuple[date, float]]) -> pd.DataFrame:
    return pd.DataFrame({COL_SOURCE_DATE: [d for d, _ in rows], COL_SOURCE_VALUE: [v for _, v in rows]})


def _stock_frame(rows: list[tuple[date, float]]) -> pd.DataFrame:
    """진짜 시가 · 고가 · 저가 · 거래량이 있는 시세 (금 선물 대역)."""
    return pd.DataFrame(
        {
            COL_DATE: [d for d, _ in rows],
            COL_OPEN: [c * 0.99 for _, c in rows],
            COL_HIGH: [c * 1.02 for _, c in rows],
            COL_LOW: [c * 0.97 for _, c in rows],
            COL_CLOSE: [c for _, c in rows],
            COL_VOLUME: [1000 + i for i in range(len(rows))],
        }
    )


class TestParsePerthMintGoldCsv:
    """Perth Mint 보관 CSV → 저장 형식 (호주 날짜 · Average 의 호주달러 · 달러 bid · ask)"""

    def test_reads_average_columns_by_label(self) -> None:
        """
        목적: Average 열을 헤더 다섯 줄의 이름으로 찾는다 — 열 순서가 달라도, High 칸이 앞에 있어도 Average 를 읽는다

        Given: 열 순서가 실제와 다르고 High 칸에 다른 값이 든 CSV, 천 단위 쉼표가 든 호주달러 값
        When: parse_perth_mint_gold_csv
        Then: 호주달러 1234.5 · 1235.5, 달러 367.2 · 367.7
        """
        # Given
        text = PERTH_HEADER + _perth_row("21/06/91", ("1,234.50", "1,235.50"), ("367.20", "367.70"))

        # When
        df = parse_perth_mint_gold_csv(text)

        # Then
        row = df.iloc[0]
        assert row[COL_SOURCE_DATE] == date(1991, 6, 21)
        assert (row[COL_AUD_BID], row[COL_AUD_ASK], row[COL_USD_BID], row[COL_USD_ASK]) == pytest.approx(
            (1234.5, 1235.5, 367.2, 367.7), rel=REL_TOL
        )

    def test_two_digit_year_century(self) -> None:
        """
        목적: 두 자리 해의 세기 — 보관 파일은 1968 ~ 2015 라 68 ~ 99 는 1900년대, 00 ~ 67 은 2000년대

        Given: 1/01/68 · 31/12/99 · 3/01/00 세 줄
        When: parse_perth_mint_gold_csv
        Then: 1968-01-01 · 1999-12-31 · 2000-01-03
        """
        # Given
        text = PERTH_HEADER + "".join(
            _perth_row(d, ("500.00", "501.00"), None) for d in ("1/01/68", "31/12/99", "3/01/00")
        )

        # When
        df = parse_perth_mint_gold_csv(text)

        # Then
        assert df[COL_SOURCE_DATE].tolist() == [date(1968, 1, 1), date(1999, 12, 31), date(2000, 1, 3)]

    def test_rows_without_values_are_dropped(self) -> None:
        """
        목적: 값이 하나도 없는 날은 행이 없다 (메우지 않는다). 호주달러만 있는 날은 달러 칸이 빈 채 남는다

        Given: 빈 날 · 호주달러만 있는 날 · 둘 다 있는 날
        When: parse_perth_mint_gold_csv
        Then: 두 행, 첫 행의 달러 칸은 NaN
        """
        # Given
        text = (
            PERTH_HEADER
            + _perth_row("2/01/91", None, None)
            + _perth_row("3/01/91", ("500.00", "501.00"), None)
            + _perth_row("4/01/91", ("502.00", "503.00"), ("380.00", "380.50"))
        )

        # When
        df = parse_perth_mint_gold_csv(text)

        # Then
        assert df[COL_SOURCE_DATE].tolist() == [date(1991, 1, 3), date(1991, 1, 4)]
        assert math.isnan(df[COL_USD_BID].iloc[0])

    @pytest.mark.parametrize(
        "header",
        [
            PERTH_HEADER.replace("Average,Average,Average,Average,\n", "Average,Average,Low,Low,\n"),
            PERTH_HEADER.replace("Priced In,USD,USD,AUD,AUD,USD,USD", "Priced In,USD,USD,AUD,AUD,JPY,JPY"),
            PERTH_HEADER.replace("Market,", "Marchet,"),
        ],
        ids=["no-usd-average", "no-usd-column", "label-changed"],
    )
    def test_changed_format_raises(self, header: str) -> None:
        """
        목적: 형식이 바뀌면(필요한 Average 열이 없거나 헤더 이름이 다르면) 멈춘다 — 엉뚱한 열을 금값으로 읽지 않는다

        Given: 달러 Average 열이 없거나 헤더 이름이 바뀐 CSV
        When: parse_perth_mint_gold_csv
        Then: ValueError
        """
        # Given
        text = header + _perth_row("21/06/91", ("1,234.50", "1,235.50"), ("367.20", "367.70"))

        # When / Then
        with pytest.raises(ValueError, match="Perth"):
            parse_perth_mint_gold_csv(text)

    @pytest.mark.parametrize(
        ("row", "keyword"),
        [
            (_perth_row("21/06/91", ("abc", "1.0"), None), "숫자"),
            (_perth_row("21/06/91", ("0", "1.0"), None), "0 이하"),
            (_perth_row("21/06/91", ("500.00", ""), None), "하나만"),
            (_perth_row("1991-06-21", ("500.00", "501.00"), None), "날짜"),
        ],
        ids=["not-number", "zero", "bid-only", "date-format"],
    )
    def test_bad_value_raises(self, row: str, keyword: str) -> None:
        """
        목적: 숫자가 아님 · 0 이하 · bid · ask 중 하나만 · 날짜 형식이 다름은 멈춘다 (메우지 않는다)

        Given: 잘못된 값이 든 한 줄
        When: parse_perth_mint_gold_csv
        Then: ValueError (원인 키워드)
        """
        # When / Then
        with pytest.raises(ValueError, match=keyword):
            parse_perth_mint_gold_csv(PERTH_HEADER + row)

    def test_dates_not_increasing_raises(self) -> None:
        """
        목적: 날짜가 중복 없는 오름차순이 아니면 멈춘다 — 세기를 잘못 읽은 것도 여기서 드러난다

        Given: 같은 날짜 두 줄
        When: parse_perth_mint_gold_csv
        Then: ValueError
        """
        # Given
        text = PERTH_HEADER + _perth_row("3/01/91", ("500", "501"), None) + _perth_row("3/01/91", ("500", "501"), None)

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            parse_perth_mint_gold_csv(text)


class TestParseFredDailyCsv:
    """FRED 일별 CSV → (날짜, 값) — 값이 없는 날은 행이 없다"""

    def test_missing_values_are_dropped(self) -> None:
        """
        목적: FRED 의 빈 값 · 「.」 인 날(미국 은행 휴일)은 행이 없다 — 메우지 않는다

        Given: 값 · 빈 값 · 「.」 · 값 네 줄
        When: parse_fred_daily_csv
        Then: 두 행 (2024-01-02 0.6812, 2024-01-05 0.6731)
        """
        # Given
        text = FRED_HEADER + "2024-01-02,0.6812\n2024-01-03,\n2024-01-04,.\n2024-01-05,0.6731\n"

        # When
        df = parse_fred_daily_csv(text, "DEXUSAL")

        # Then
        assert df[COL_SOURCE_DATE].tolist() == [date(2024, 1, 2), date(2024, 1, 5)]
        assert df[COL_SOURCE_VALUE].tolist() == pytest.approx([0.6812, 0.6731], rel=REL_TOL)

    @pytest.mark.parametrize(
        ("text", "keyword"),
        [
            ("observation_date,DEXJPUS\n2024-01-02,140.1\n", "헤더"),
            (FRED_HEADER + "2024-01-02,abc\n", "숫자"),
            (FRED_HEADER + "2024-01-02,0\n", "0 이하"),
            (FRED_HEADER + "2024-01-03,0.68\n2024-01-02,0.67\n", "오름차순"),
            (FRED_HEADER + "2024/01/02,0.68\n", "날짜"),
            (FRED_HEADER, "비어"),
        ],
        ids=["header", "not-number", "zero", "order", "date-format", "empty"],
    )
    def test_bad_input_raises(self, text: str, keyword: str) -> None:
        """
        목적: 헤더 · 숫자 · 0 이하 · 순서 · 날짜 형식 · 빈 응답은 멈춘다

        Given: 잘못된 FRED CSV
        When: parse_fred_daily_csv
        Then: ValueError (원인 키워드)
        """
        # When / Then
        with pytest.raises(ValueError, match=keyword):
            parse_fred_daily_csv(text, "DEXUSAL")


# 미국 날짜 붙이기 — 2024-01-03(수) ~ 01-10(수). 호주 날짜는 미국 날짜의 다음 영업일
US_DATES = [date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)]
PERTH_ROWS = [
    (date(2024, 1, 4), 2990.0, None),  # → 미국 01-03 — 호주달러만 (달러 고리 앞)
    (date(2024, 1, 5), 3000.0, 2000.0),  # → 미국 01-04 (목)
    (date(2024, 1, 6), 3999.0, 2999.0),  # 토요일 값 — 다음 영업일 규칙에 쓰이지 않는다
    (date(2024, 1, 8), 3010.0, 2010.0),  # → 미국 01-05 (금)
    (date(2024, 1, 9), 3020.0, 2020.0),  # → 미국 01-08 (월)
    # 01-10 은 호주 휴일 → 미국 01-09 행 없음
    (date(2024, 1, 11), 3040.0, 2040.0),  # → 미국 01-10 (수)
    (date(2024, 1, 12), 3050.0, 2050.0),  # → 미국 01-11 은 달력 밖
]
FX_ROWS = [
    (date(2024, 1, 3), 0.69),
    (date(2024, 1, 4), 0.70),
    (date(2024, 1, 5), 0.71),
    # 01-08 은 미국 은행 휴일 → 그 미국 날짜의 호주달러 값 행 없음
    (date(2024, 1, 9), 0.72),
    (date(2024, 1, 10), 0.73),
]


class TestUsDateAttachment:
    """미국 날짜 d ← 호주 d + 1영업일 Perth 값, 환율은 미국 d 값 (결정 6 · 연구 문서 6.4)"""

    def _build(self) -> gold_proxy.GoldProxy:
        perth = _perth_frame(PERTH_ROWS)
        futures = _stock_frame([(date(2024, 1, 10), 1900.0)])
        return build_gold_proxy(perth, _fx_frame(FX_ROWS), futures, US_DATES)

    def test_perth_usd_takes_next_business_day(self) -> None:
        """
        목적: 달러 고리 — 미국 날짜 d 에 호주 다음 영업일 값. 금요일은 다음 월요일 값(토요일 값이 아니다),
              호주 휴일이면 그 미국 날짜 행이 없고, 달력 밖 날짜는 없다

        Given: PERTH_ROWS (호주 01-10 휴일, 토요일 값, 미국 01-11 은 달력 밖, 미국 01-03 은 호주달러만)
        When: build_gold_proxy(...).perth_usd
        Then: 미국 01-04 · 01-05 · 01-08 · 01-10 에 2000 · 2010 · 2020 · 2040
        """
        # When
        perth_usd = self._build().perth_usd

        # Then
        assert perth_usd[COL_DATE].tolist() == [date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 10)]
        assert perth_usd[COL_CLOSE].tolist() == pytest.approx([2000.0, 2010.0, 2020.0, 2040.0], rel=REL_TOL)

    def test_aud_in_usd_uses_same_us_date_fx(self) -> None:
        """
        목적: 호주달러 고리 — 호주 다음 영업일 호주달러 값 × 그 미국 날짜의 환율. 환율이 없는 미국 날짜는 행이 없다

        Given: PERTH_ROWS · FX_ROWS (미국 01-08 환율 없음)
        When: build_gold_proxy(...).aud_in_usd
        Then: 미국 01-03 2990 × 0.69, 01-04 3000 × 0.70, 01-05 3010 × 0.71, 01-10 3040 × 0.73
              — 01-08 (환율 없음) · 01-09 (호주 휴일) 행 없음
        """
        # When
        aud_in_usd = self._build().aud_in_usd

        # Then
        assert aud_in_usd[COL_DATE].tolist() == [
            date(2024, 1, 3),
            date(2024, 1, 4),
            date(2024, 1, 5),
            date(2024, 1, 10),
        ]
        assert aud_in_usd[COL_CLOSE].tolist() == pytest.approx(
            [2990.0 * 0.69, 3000.0 * 0.70, 3010.0 * 0.71, 3040.0 * 0.73], rel=REL_TOL
        )

    def test_one_value_per_day_and_zero_volume(self) -> None:
        """
        목적: Perth 고리의 행은 하루 한 값 — 시가 · 고가 · 저가 · 종가가 같고 거래량 0, 열은 시세 표 그대로

        Given: PERTH_ROWS
        When: build_gold_proxy(...).perth_usd
        Then: 네 가격 열이 종가와 같고 거래량 0, 열 순서 REQUIRED_COLUMNS
        """
        # When
        perth_usd = self._build().perth_usd

        # Then
        assert list(perth_usd.columns) == REQUIRED_COLUMNS
        for col in (COL_OPEN, COL_HIGH, COL_LOW):
            assert perth_usd[col].tolist() == perth_usd[COL_CLOSE].tolist()
        assert (perth_usd[COL_VOLUME] == 0).all()


# 사슬 — 미국 달력 2024-01-02 ~ 01-12 (01-11 은 미국 휴일). 달러 값은 호주 01-08 부터, 금 선물은 미국 01-09 부터
CHAIN_US_DATES = [
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
    date(2024, 1, 9),
    date(2024, 1, 10),
    date(2024, 1, 12),
]
CHAIN_PERTH_ROWS = [
    (date(2024, 1, 3), 3000.0, None),  # → 미국 01-02
    (date(2024, 1, 4), 3030.0, None),  # → 01-03
    (date(2024, 1, 5), 3060.0, None),  # → 01-04
    (date(2024, 1, 8), 3090.0, 2000.0),  # → 01-05 (달러 고리 첫 미국 날짜)
    (date(2024, 1, 9), 3120.0, 2020.0),  # → 01-08
    (date(2024, 1, 10), 3150.0, 2040.0),  # → 01-09 (금 선물 첫날)
    (date(2024, 1, 11), 3180.0, 2060.0),  # → 01-10
    (date(2024, 1, 15), 3210.0, 2080.0),  # → 01-12
]
CHAIN_FX_ROWS = [(d, 0.70) for d in CHAIN_US_DATES]
CHAIN_FUTURES_ROWS = [
    (date(2024, 1, 9), 1900.0),
    (date(2024, 1, 10), 1910.0),
    (date(2024, 1, 11), 1920.0),  # 미국 휴일 — 사슬에서 빠진다
    (date(2024, 1, 12), 1930.0),
]


class TestBuildGoldProxyChain:
    """호주달러 × 환율 → Perth 달러 → 금 선물. 이음매는 뒤 고리의 첫 미국 날짜이고 그날부터 뒤 고리 행 그대로"""

    def _build(self) -> gold_proxy.GoldProxy:
        return build_gold_proxy(
            _perth_frame(CHAIN_PERTH_ROWS), _fx_frame(CHAIN_FX_ROWS), _stock_frame(CHAIN_FUTURES_ROWS), CHAIN_US_DATES
        )

    def test_chain_dates_follow_us_calendar(self) -> None:
        """
        목적: 사슬의 날짜는 미국 달력 날짜뿐이다 — 금 선물의 미국 휴일(01-11) 행은 빠진다

        Given: CHAIN_* (금 선물에 미국 휴일 01-11 행)
        When: build_gold_proxy(...).chain
        Then: CHAIN_US_DATES 그대로
        """
        # When
        chain = self._build().chain

        # Then
        assert chain[COL_DATE].tolist() == CHAIN_US_DATES

    def test_rows_from_futures_seam_are_futures_closes(self) -> None:
        """
        목적: 금 선물 첫날부터는 금 선물 종가를 하루 한 값으로 쓴다 (불변 조건 ⑥) — 받은 시가 · 고가 · 저가는 미국 주식 장의
              봉이 아니고 종가가 봉 밖인 날도 있어 쓰지 않는다

        Given: CHAIN_* (금 선물에 진짜 시가 · 고가 · 저가 · 거래량)
        When: build_gold_proxy(...).chain
        Then: 미국 01-09 이후 행 = 금 선물 01-09 · 01-10 · 01-12 종가, 네 가격 열이 종가와 같고 거래량 0
        """
        # When
        chain = self._build().chain

        # Then
        from_seam = chain[chain[COL_DATE] >= date(2024, 1, 9)].reset_index(drop=True)
        assert from_seam[COL_DATE].tolist() == [date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 12)]
        assert from_seam[COL_CLOSE].tolist() == pytest.approx([1900.0, 1910.0, 1930.0], rel=REL_TOL)
        for col in (COL_OPEN, COL_HIGH, COL_LOW):
            assert from_seam[col].tolist() == from_seam[COL_CLOSE].tolist()
        assert (from_seam[COL_VOLUME] == 0).all()

    def test_earlier_links_keep_their_returns(self) -> None:
        """
        목적: 앞 고리는 비율만 맞춘다 — 하루 수익률이 그 고리의 원본과 같고, 이음매 날 값이 뒤 고리 값이다

        Given: CHAIN_* — 호주달러 고리 미국 01-02 ~ 01-04, 달러 고리 01-05 ~ 01-08
        When: build_gold_proxy(...).chain
        Then: 01-03 · 01-04 의 수익률 = 호주달러 값 수익률(1%), 01-08 = 달러 값 수익률(1%),
              01-05 의 수익률 = 호주달러 고리의 그날 수익률(3090 / 3060 − 1), 01-09 = 달러 고리의 그날 수익률(2040 / 2020 − 1)
        """
        # When
        chain = self._build().chain

        # Then
        returns = chain.set_index(COL_DATE)[COL_CLOSE].pct_change()
        assert returns[date(2024, 1, 3)] == pytest.approx(0.01, rel=1e-9)
        assert returns[date(2024, 1, 4)] == pytest.approx(3060.0 / 3030.0 - 1, rel=1e-9)
        assert returns[date(2024, 1, 5)] == pytest.approx(3090.0 / 3060.0 - 1, rel=1e-9)
        assert returns[date(2024, 1, 8)] == pytest.approx(0.01, rel=1e-9)
        assert returns[date(2024, 1, 9)] == pytest.approx(2040.0 / 2020.0 - 1, rel=1e-9)

    def test_pre_futures_volume_is_zero(self) -> None:
        """
        목적: 금 선물 앞 고리의 거래량은 0 이다 — 대용의 거래량은 실물 거래량이 아니다

        Given: CHAIN_*
        When: build_gold_proxy(...).chain
        Then: 미국 01-09 앞 행의 거래량 0
        """
        # When
        chain = self._build().chain

        # Then
        assert (chain.loc[chain[COL_DATE] < date(2024, 1, 9), COL_VOLUME] == 0).all()

    def test_seam_missing_in_earlier_link_raises(self) -> None:
        """
        목적: 이음매 날(달러 고리의 첫 미국 날짜)에 호주달러 고리 값이 없으면 멈춘다 — 다른 날로 비율을 맞추지 않는다

        Given: 미국 01-05 의 환율이 없는 CHAIN_* (그날 호주달러 고리 행 없음)
        When: build_gold_proxy
        Then: ValueError (이음매)
        """
        # Given
        fx = _fx_frame([(d, v) for d, v in CHAIN_FX_ROWS if d != date(2024, 1, 5)])

        # When / Then
        with pytest.raises(ValueError, match="이음매"):
            build_gold_proxy(_perth_frame(CHAIN_PERTH_ROWS), fx, _stock_frame(CHAIN_FUTURES_ROWS), CHAIN_US_DATES)


PERTH_TEXT = (
    PERTH_HEADER
    + _perth_row("3/01/91", ("500.00", "501.00"), None)
    + _perth_row("4/01/91", ("502.00", "503.00"), ("380.00", "380.50"))
)
FX_TEXT = FRED_HEADER + "1991-01-02,0.7712\n1991-01-03,0.7720\n"


class TestSaveAndLoadSources:
    """받은 두 원본을 검사한 뒤에만 저장하고, 저장한 파일을 같은 표로 다시 읽는다"""

    def test_round_trip(self, tmp_path: Path) -> None:
        """
        목적: 저장한 파일을 읽으면 파싱한 표와 같다 — 날짜 · 빈 칸(호주달러만 있는 날의 달러)까지

        Given: Perth · FRED CSV 본문
        When: save_gold_proxy_sources → load_gold_proxy_sources
        Then: 파싱 결과와 같은 두 표
        """
        # Given
        perth_path, fx_path = tmp_path / "perth.csv", tmp_path / "fx.csv"

        # When
        save_gold_proxy_sources(PERTH_TEXT, FX_TEXT, perth_path, fx_path)
        perth_df, fx_df = load_gold_proxy_sources(perth_path, fx_path)

        # Then
        pd.testing.assert_frame_equal(perth_df, parse_perth_mint_gold_csv(PERTH_TEXT))
        pd.testing.assert_frame_equal(fx_df, parse_fred_daily_csv(FX_TEXT, "DEXUSAL"))

    def test_truncated_response_keeps_existing_files(self, tmp_path: Path) -> None:
        """
        목적: 받은 표가 기존 파일의 날을 다 덮지 못하면(잘린 응답) 두 파일 모두 쓰지 않는다

        Given: 1991-01-02 ~ 01-03 환율이 저장된 파일, 01-03 만 든 새 응답
        When: save_gold_proxy_sources
        Then: ValueError, 두 파일의 바이트가 그대로
        """
        # Given
        perth_path, fx_path = tmp_path / "perth.csv", tmp_path / "fx.csv"
        save_gold_proxy_sources(PERTH_TEXT, FX_TEXT, perth_path, fx_path)
        before = (perth_path.read_bytes(), fx_path.read_bytes())
        truncated_fx = FRED_HEADER + "1991-01-03,0.7720\n"

        # When / Then
        with pytest.raises(ValueError, match="덮지 못"):
            save_gold_proxy_sources(PERTH_TEXT, truncated_fx, perth_path, fx_path)
        assert (perth_path.read_bytes(), fx_path.read_bytes()) == before

    def test_lost_value_column_keeps_existing_files(self, tmp_path: Path) -> None:
        """
        목적: 날은 모두 있어도 값 칸이 빠진 응답(달러 열만 빈 Perth)은 쓰지 않는다 — 날만 견주면 달러 고리가 조용히 짧아진다

        Given: 1991-01-04 에 달러 값이 저장된 Perth 파일, 같은 날 호주달러만 든 새 응답
        When: save_gold_proxy_sources
        Then: ValueError, 두 파일의 바이트가 그대로
        """
        # Given
        perth_path, fx_path = tmp_path / "perth.csv", tmp_path / "fx.csv"
        save_gold_proxy_sources(PERTH_TEXT, FX_TEXT, perth_path, fx_path)
        before = (perth_path.read_bytes(), fx_path.read_bytes())
        usd_lost = (
            PERTH_HEADER
            + _perth_row("3/01/91", ("500.00", "501.00"), None)
            + _perth_row("4/01/91", ("502.00", "503.00"), None)
        )

        # When / Then
        with pytest.raises(ValueError, match="덮지 못"):
            save_gold_proxy_sources(usd_lost, FX_TEXT, perth_path, fx_path)
        assert (perth_path.read_bytes(), fx_path.read_bytes()) == before


class _FakeResponse:
    """urlopen 이 돌려주는 응답 대역 — with 문과 read 만 쓴다."""

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestDownloadGoldProxySources:
    """두 원본을 받아 저장 — Perth Mint 는 파이썬 기본 UA 를 막고(403), FRED 는 이름을 밝힌 UA 를 응답 없이 붙잡는다"""

    def test_sends_user_agent_only_to_perth_and_saves(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 이름을 밝힌 UA 는 Perth Mint 요청에만 싣고 FRED 는 기본 UA 로 받는다 — FRED 가 그 UA 를 타임아웃까지 붙잡는다
              (2026-11-07 재현). 받은 본문을 저장한다

        Given: 주소별 본문을 돌려주고 요청의 User-Agent 를 기록하는 urlopen 대역
        When: download_gold_proxy_sources
        Then: Perth 요청의 User-Agent 가 USER_AGENT, FRED 요청에는 User-Agent 헤더가 없다. 저장된 파일이 본문의 파싱 결과와 같다
        """
        # Given
        bodies = {PERTH_MINT_GOLD_CSV_URL: PERTH_TEXT, FRED_AUD_USD_CSV_URL: FX_TEXT}
        seen: dict[str, str | None] = {}

        def fake_urlopen(request: Request, timeout: float) -> _FakeResponse:
            seen[request.full_url] = request.get_header("User-agent")
            return _FakeResponse(bodies[request.full_url])

        monkeypatch.setattr(gold_proxy, "urlopen", fake_urlopen)
        perth_path, fx_path = tmp_path / "perth.csv", tmp_path / "fx.csv"

        # When
        download_gold_proxy_sources(perth_path, fx_path)

        # Then
        assert seen == {PERTH_MINT_GOLD_CSV_URL: USER_AGENT, FRED_AUD_USD_CSV_URL: None}
        perth_df, _ = load_gold_proxy_sources(perth_path, fx_path)
        pd.testing.assert_frame_equal(perth_df, parse_perth_mint_gold_csv(PERTH_TEXT))
