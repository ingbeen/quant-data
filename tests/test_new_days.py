"""
new_days 모듈 테스트 — 새로 붙는 날 검사 (판정 규칙 ②) 와 패스 목록

이 파일은 무엇을 검증하나요?
1. 새로 붙는 날은 기존 끝날 뒤의 날뿐이고, 기존 파일이 없으면 없는가? (결정 Q29 · Q34)
2. 미국: 대상 하루 수익률 − 배율 × 짝 하루 수익률이 배율 × 1%p 를 넘는 날만 걸리는가? (결정 Q29 · Q30 · Q31)
3. 국내: KRX 원본가 ↔ 야후 원본가가 1원이라도 다르면 걸리고, 야후에 그날이 없으면 건너뛰는가?
4. 국내: 기준가가 바뀐 날의 「종가 ÷ 기준가 − 1」이 공식 등락률과 반 단위 밖이면 걸리는가? (KRX 자료끼리 — 결정 Q14)
5. 비트코인: Bitstamp 종가 ↔ Coin Metrics 기준가 차이가 5% 를 넘거나 그날 기준가가 없으면 걸리는가?
6. 패스 목록이 모든 칸(종목 · 날짜 · 검사 · 사유 · 근거)을 갖춘 줄만 받고, 같은 종목 · 날짜 · 검사의 실패만 놓아주는가?

왜 중요한가요?
급등락은 저장을 막지 않고 이 검사가 멈춘다(결정 Q26). 기준이 느슨하면 오류가 새 날짜로 섞여 들어오고,
기준이 엄하면 실제 대폭락 날마다 멈춘다 — 실제 대폭락은 패스 목록에 근거와 함께 적고 다시 실행한다.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_data.constants import (
    COL_BASE_PRICE,
    COL_CHANGE_RATE,
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VALUE,
    COL_VOLUME,
)
from quant_data.new_days import (
    COIN_TWO_SOURCES_TOLERANCE,
    PAIR_TOLERANCE_PER_LEVERAGE,
    Check,
    NewDayFailure,
    PassEntry,
    appended_days,
    check_coin_two_sources,
    check_kr_base_rate,
    check_kr_two_sources,
    check_pair,
    load_pass_list,
    remaining_failures,
)

DAYS = [date(2020, 3, 9), date(2020, 3, 10), date(2020, 3, 11), date(2020, 3, 12), date(2020, 3, 13)]


def _prices(closes: list[float], dates: list[date] | None = None) -> pd.DataFrame:
    """종가로 만든 시세 — 검사는 종가만 본다."""
    return pd.DataFrame(
        {
            COL_DATE: dates if dates is not None else DAYS[: len(closes)],
            COL_OPEN: closes,
            COL_HIGH: closes,
            COL_LOW: closes,
            COL_CLOSE: closes,
            COL_VOLUME: 0,
        }
    )


def _krx(
    closes: list[int], rates: list[float], dates: list[date] | None = None, bases: list[int] | None = None
) -> pd.DataFrame:
    """KRX 원본가 — 원 단위 정수 가격, 기준가(주지 않으면 전날 종가 · 첫 행은 자기 종가), 공식 등락률(%, KRX 표기 그대로)."""
    frame = _prices([float(c) for c in closes], dates)
    frame[[COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE]] = frame[[COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE]].astype("int64")
    frame[COL_BASE_PRICE] = bases if bases is not None else [closes[0], *closes[:-1]]
    frame[COL_CHANGE_RATE] = rates
    return frame


def _value_series(values: list[float], dates: list[date] | None = None) -> pd.DataFrame:
    """하루 한 값 계열 (Coin Metrics 기준가 등)."""
    return pd.DataFrame({COL_DATE: dates if dates is not None else DAYS[: len(values)], COL_VALUE: values})


class TestAppendedDays:
    """새로 붙는 날 — 기존 끝날 뒤의 날"""

    def test_days_after_existing_end(self) -> None:
        """
        목적: 새로 붙는 날은 기존 끝날 뒤의 날뿐이다 — 과거 행은 판정 규칙 ① 의 상대 2e-5 가 지킨다(Q29)

        Given: 기존 3일(03-09 ~ 03-11), 갱신 뒤 5일
        When: appended_days
        Then: [03-12, 03-13]
        """
        # Given
        existing = _prices([100.0, 101.0, 102.0])
        updated = _prices([100.0, 101.0, 102.0, 103.0, 104.0])

        # When & Then
        assert appended_days(existing, updated) == [DAYS[3], DAYS[4]]

    def test_no_days_without_existing_file(self) -> None:
        """
        목적: 기존 파일이 없으면 새로 붙는 날이 없다 — 첫 판의 미국 짝 대조는 걸지 않는다. 전 기간으로 재면 꼬리가 굵어
              (QQQ ↔ 나스닥100 2000년 1%p 넘는 날 145) 패스 목록이 수백 줄이 된다(Q34)

        Given: 기존 없음, 갱신 뒤 5일
        When: appended_days
        Then: []
        """
        # When & Then
        assert appended_days(None, _prices([100.0, 101.0, 102.0, 103.0, 104.0])) == []


class TestCheckPair:
    """미국 짝 차이 — 대상 하루 수익률 − 배율 × 짝 하루 수익률, 기준 배율 × 1%p"""

    @pytest.mark.parametrize("leverage", [1.0, 2.0, 3.0])
    @pytest.mark.parametrize(("margin", "fails"), [(-0.0001, False), (0.0001, True)])
    def test_limit_is_leverage_times_one_percent_point(self, leverage: float, margin: float, fails: bool) -> None:
        """
        목적: 기준은 배율 × 1%p 이고 넘을 때만 걸린다 (경계) — 2016년 이후 넘은 날이 QQQ 2 · SPY 1 · TQQQ 2 이고 모두 2020-03(Q30)

        Given: 짝 +1%, 대상 = 배율 × 1% + (배율 × 1%p ± 0.01%p)
        When: check_pair(새로 붙는 날 = 둘째 날)
        Then: 기준 안이면 실패 없음, 넘으면 그날 짝 차이 실패 하나
        """
        # Given
        pair = _prices([100.0, 101.0])
        difference = leverage * PAIR_TOLERANCE_PER_LEVERAGE + margin
        target = _prices([100.0, 100.0 * (1 + leverage * 0.01 + difference)])

        # When
        failures = check_pair(target, pair, ticker="T", pair_name="^P", leverage=leverage, days=[DAYS[1]])

        # Then
        if fails:
            assert [(f.ticker, f.day, f.check) for f in failures] == [("T", DAYS[1], Check.PAIR)]
            assert "^P" in failures[0].detail
        else:
            assert failures == []

    def test_negative_difference_also_fails(self) -> None:
        """
        목적: 방향을 가리지 않는다 — 대상이 짝보다 크게 덜 움직여도 걸린다

        Given: 짝 −10%, 대상 −8% (배율 1, 차이 +2%p)
        When: check_pair
        Then: 실패 하나
        """
        # Given
        pair = _prices([100.0, 90.0])
        target = _prices([100.0, 92.0])

        # When
        failures = check_pair(target, pair, ticker="T", pair_name="^P", leverage=1.0, days=[DAYS[1]])

        # Then
        assert len(failures) == 1

    def test_large_move_matching_pair_passes(self) -> None:
        """
        목적: 짝과 함께 움직인 대폭락은 걸리지 않는다 — 하루 50% 기준이 막던 실제 급락(3배 −35% 등)이 짝 대조로는 통과한다

        Given: 짝 −12%, 대상(3배) −36%
        When: check_pair(배율 3)
        Then: 실패 없음
        """
        # Given
        pair = _prices([100.0, 88.0])
        target = _prices([100.0, 64.0])

        # When & Then
        assert check_pair(target, pair, ticker="T", pair_name="^P", leverage=3.0, days=[DAYS[1]]) == []

    def test_past_rows_are_not_checked(self) -> None:
        """
        목적: 넘긴 날(새로 붙는 날)만 본다 — 과거 행의 큰 차이(2000년 꼬리 같은)로는 멈추지 않는다

        Given: 둘째 날 차이 +20%p(과거), 넷째 날 차이 0, 새로 붙는 날 = 넷째 날
        When: check_pair
        Then: 실패 없음
        """
        # Given
        pair = _prices([100.0, 100.0, 100.0, 101.0])
        target = _prices([100.0, 120.0, 120.0, 121.2])

        # When & Then
        assert check_pair(target, pair, ticker="T", pair_name="^P", leverage=1.0, days=[DAYS[3]]) == []

    def test_missing_pair_day_fails(self) -> None:
        """
        목적: 짝 시세에 그날(또는 전날)이 없으면 견줄 수 없어 실패로 보인다 — 건너뛰면 검사 없이 새 날짜가 들어온다

        Given: 대상 3일, 짝은 셋째 날이 없음, 새로 붙는 날 = 셋째 날
        When: check_pair
        Then: 실패 하나, 설명에 「짝」 · 「없」
        """
        # Given
        target = _prices([100.0, 101.0, 102.0])
        pair = _prices([100.0, 101.0], dates=DAYS[:2])

        # When
        failures = check_pair(target, pair, ticker="T", pair_name="^P", leverage=1.0, days=[DAYS[2]])

        # Then
        assert len(failures) == 1
        assert "짝" in failures[0].detail and "없" in failures[0].detail


class TestCheckKrTwoSources:
    """국내 KRX 원본가 ↔ 야후 원본가 — 완전 일치(원 단위), 야후에 그날이 없으면 건너뜀"""

    def test_equal_closes_pass(self) -> None:
        """
        목적: 두 출처의 종가가 원 단위로 같으면 통과한다 — 야후는 실수로 주므로 원 단위로 반올림해 견준다

        Given: KRX 35,420 · 35,500, 야후 35,420.0000001 · 35,500.0
        When: check_kr_two_sources(두 날)
        Then: 실패 없음
        """
        # Given
        krx = _krx([35420, 35500], [0.0, 0.23])
        yahoo = _prices([35420.0000001, 35500.0])

        # When & Then
        assert check_kr_two_sources(krx, yahoo, ticker="069500", days=DAYS[:2]) == []

    def test_one_won_difference_fails(self) -> None:
        """
        목적: 1원이라도 다르면 걸린다 — 두 출처가 값이 있는 날 9종 모두 같았다(시세_받기_판정.md 6.3)

        Given: 둘째 날 KRX 35,500 · 야후 35,501
        When: check_kr_two_sources
        Then: 그날 두 출처 일치 실패 하나, 설명에 두 값
        """
        # Given
        krx = _krx([35420, 35500], [0.0, 0.23])
        yahoo = _prices([35420.0, 35501.0])

        # When
        failures = check_kr_two_sources(krx, yahoo, ticker="069500", days=DAYS[:2])

        # Then
        assert [(f.day, f.check) for f in failures] == [(DAYS[1], Check.KR_TWO_SOURCES)]
        assert "35,500" in failures[0].detail and "35,501" in failures[0].detail

    @pytest.mark.parametrize("yahoo_close", [None, np.nan], ids=["row_missing", "price_empty"])
    def test_missing_yahoo_day_is_skipped(self, yahoo_close: float | None) -> None:
        """
        목적: 야후에 그날이 없거나 가격이 빈 행이면 건너뛴다 — 야후는 KRX 에 있는 날을 빠뜨리고(069500 567일),
              빈 가격 행(거래량 0)을 주기도 한다. 그날은 KRX 자료끼리의 대조만 한다

        Given: 둘째 날 KRX 35,500, 야후는 그날 행이 없거나 가격이 비었음
        When: check_kr_two_sources
        Then: 실패 없음
        """
        # Given
        krx = _krx([35420, 35500], [0.0, 0.23])
        if yahoo_close is None:
            yahoo = _prices([35420.0], dates=DAYS[:1])
        else:
            yahoo = _prices([35420.0, yahoo_close])

        # When & Then
        assert check_kr_two_sources(krx, yahoo, ticker="069500", days=DAYS[:2]) == []


class TestCheckKrBaseRate:
    """국내 KRX 자료끼리 — 기준가가 바뀐 날의 「종가 ÷ 기준가 − 1」 ↔ 공식 등락률, 표기 자릿수(2자리)의 반 단위"""

    def test_unchanged_base_day_is_not_checked(self) -> None:
        """
        목적: 공식 등락률이 원본가 하루 변화와 맞는 날(기준가 = 전날 종가)은 기준가 칸을 보지 않는다 — 2005년 069500 의
              대비만 어긋난 4일이 멈추지 않는다

        Given: 10,000 → 10,123, 공식 등락률 = 하루 변화의 2자리, 기준가 칸은 10,010 (대비 오기)
        When: check_kr_base_rate(둘째 날)
        Then: 실패 없음
        """
        # Given
        krx = _krx([10000, 10123], [0.0, round((10123 / 10000 - 1) * 100, 2)], bases=[10000, 10010])

        # When & Then
        assert check_kr_base_rate(krx, ticker="069500", days=[DAYS[1]]) == []

    def test_distribution_day_consistent_with_base_passes(self) -> None:
        """
        목적: 분배락일(기준가가 내려간 날)은 그 기준가로 낸 등락률이 공식 등락률과 맞으면 통과한다 — 기준가가 바뀐
              80일이 모두 이 모양이었다(시세_받기_판정.md 6.4)

        Given: 전날 32,105 → 32,245, 기준가 32,035 (70원 분배), 공식 등락률 0.66 (= 32,245 ÷ 32,035 − 1)
        When: check_kr_base_rate
        Then: 실패 없음
        """
        # Given
        krx = _krx([32105, 32245], [0.0, 0.66], bases=[32105, 32035])

        # When & Then
        assert check_kr_base_rate(krx, ticker="069500", days=[DAYS[1]]) == []

    def test_base_inconsistent_with_official_rate_fails(self) -> None:
        """
        목적: 기준가가 바뀐 날인데 그 기준가로 낸 등락률이 공식 등락률과 반 단위 밖이면 걸린다 — KRX 의 대비 · 등락률이
              서로 맞지 않으면 수정주가를 만들 기준가를 믿을 수 없다

        Given: 전날 32,105 → 32,245, 기준가 32,000, 공식 등락률 0.66 (32,245 ÷ 32,000 − 1 = +0.77%)
        When: check_kr_base_rate
        Then: 그날 기준가 등락률 실패 하나
        """
        # Given
        krx = _krx([32105, 32245], [0.0, 0.66], bases=[32105, 32000])

        # When
        failures = check_kr_base_rate(krx, ticker="069500", days=[DAYS[1]])

        # Then
        assert [(f.day, f.check) for f in failures] == [(DAYS[1], Check.KR_BASE_RATE)]

    def test_first_row_is_skipped(self) -> None:
        """
        목적: 앞 행이 없는 첫 행은 건너뛴다 (경계) — 첫 판은 전 기간에 걸므로(Q34) 첫 행이 늘 들어온다

        Given: 한 행, 공식 등락률 3.0 (상장 첫날 공모가 대비 등)
        When: check_kr_base_rate
        Then: 실패 없음
        """
        # Given
        krx = _krx([10000], [3.0])

        # When & Then
        assert check_kr_base_rate(krx, ticker="069500", days=[DAYS[0]]) == []


class TestCheckCoinTwoSources:
    """비트코인 Bitstamp 종가 ↔ Coin Metrics 기준가 — 차이 5% 를 넘으면 걸림 (결정 Q6)"""

    @pytest.mark.parametrize(("ratio", "fails"), [(1.049, False), (0.951, False), (1.051, True), (0.949, True)])
    def test_tolerance_both_directions(self, ratio: float, fails: bool) -> None:
        """
        목적: 차이율 = Bitstamp ÷ Coin Metrics − 1 의 절대값이 5% 를 넘을 때만 걸린다 (경계, 방향 무관) — verify-lab 이
              두 출처 대조에 쓰던 목록 경계 그대로다

        Given: Coin Metrics 100, Bitstamp 100 × ratio
        When: check_coin_two_sources(그날)
        Then: ±4.9% 통과, ±5.1% 는 두 출처 차이 실패
        """
        # Given
        target = _prices([100.0 * ratio])
        pair = _value_series([100.0])

        # When
        failures = check_coin_two_sources(target, pair, ticker="BTCUSD", pair_name="BTC_PriceUSD", days=[DAYS[0]])

        # Then
        assert COIN_TWO_SOURCES_TOLERANCE == 0.05
        assert [f.check for f in failures] == ([Check.COIN_TWO_SOURCES] if fails else [])

    def test_missing_pair_day_fails(self) -> None:
        """
        목적: Coin Metrics 에 그날 값이 없으면 견줄 수 없어 실패로 보인다 — 건너뛰면 대조 없이 새 날짜가 들어온다

        Given: Bitstamp 두 날, Coin Metrics 첫날만
        When: check_coin_two_sources(둘째 날)
        Then: 실패 하나, 설명에 「없」
        """
        # Given
        target = _prices([100.0, 101.0])
        pair = _value_series([100.0])

        # When
        failures = check_coin_two_sources(target, pair, ticker="BTCUSD", pair_name="BTC_PriceUSD", days=[DAYS[1]])

        # Then
        assert len(failures) == 1 and "없" in failures[0].detail


PASS_LIST_HEADER = "종목,날짜,검사,사유,근거"


def _write_pass_list(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([PASS_LIST_HEADER, *rows]) + "\n", encoding="utf-8-sig")
    return path


class TestLoadPassList:
    """패스 목록 파일 — 한 줄에 종목 · 날짜 · 검사 · 사유 · 근거, 사람과 AI 가 적는다"""

    def test_reads_entries(self, tmp_path: Path) -> None:
        """
        목적: 칸을 모두 갖춘 줄을 읽는다 — 한글 머리 · BOM 붙은 CSV

        Given: 두 줄 (짝 차이 · 두 출처 차이)
        When: load_pass_list
        Then: 두 PassEntry
        """
        # Given
        path = _write_pass_list(
            tmp_path / "pass_list.csv",
            [
                "QQQ,2020-03-13,짝 차이,코로나 급락 반등,그날 나스닥100 +9.35% · TQQQ 도 함께 넘음",
                "BTCUSD,2014-02-24,두 출처 차이,거래소 장애,Coin Metrics 기준가와 −8% · 같은 날 Mt.Gox 거래 중단",
            ],
        )

        # When
        entries = load_pass_list(path)

        # Then
        assert entries == [
            PassEntry("QQQ", date(2020, 3, 13), Check.PAIR, "코로나 급락 반등", "그날 나스닥100 +9.35% · TQQQ 도 함께 넘음"),
            PassEntry(
                "BTCUSD",
                date(2014, 2, 24),
                Check.COIN_TWO_SOURCES,
                "거래소 장애",
                "Coin Metrics 기준가와 −8% · 같은 날 Mt.Gox 거래 중단",
            ),
        ]

    def test_header_only_is_empty(self, tmp_path: Path) -> None:
        """
        목적: 머리만 있는 파일은 빈 목록이다 (경계) — 처음 만든 패스 목록의 모양

        Given: 머리만 있는 파일
        When: load_pass_list
        Then: []
        """
        # When & Then
        assert load_pass_list(_write_pass_list(tmp_path / "pass_list.csv", [])) == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """
        목적: 파일이 없으면 멈춘다 — 빈 목록으로 넘기면 지워진 파일을 알아채지 못한다

        Given: 없는 경로
        When: load_pass_list
        Then: FileNotFoundError
        """
        # When & Then
        with pytest.raises(FileNotFoundError):
            load_pass_list(tmp_path / "pass_list.csv")

    @pytest.mark.parametrize(
        ("row", "pattern"),
        [
            ("QQQ,2020-03-13,짝 차이,코로나 급락,", "근거"),
            ("QQQ,2020-03-13,짝 차이,,그날 나스닥100 +9.35%", "사유"),
            ("QQQ,2020-3-13,짝 차이,코로나 급락,그날 나스닥100 +9.35%", "날짜"),
            ("QQQ,2020-03-13,급등락,코로나 급락,그날 나스닥100 +9.35%", "검사"),
        ],
        ids=["no_evidence", "no_reason", "bad_date", "unknown_check"],
    )
    def test_incomplete_row_raises(self, tmp_path: Path, row: str, pattern: str) -> None:
        """
        목적: 칸이 빠지거나 모양이 틀린 줄은 받지 않는다 — 근거 없는 패스가 진짜 오류를 덮는다(Risks: AI 작성 허용).
              검사 이름이 틀리면 어떤 실패도 놓아주지 못해 같은 날이 계속 멈춘다

        Given: 근거 · 사유가 빈 줄, 날짜가 YYYY-MM-DD 가 아닌 줄, 없는 검사 이름의 줄
        When: load_pass_list
        Then: ValueError (빠진 칸 이름)
        """
        # Given
        path = _write_pass_list(tmp_path / "pass_list.csv", [row])

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            load_pass_list(path)

    def test_duplicate_entry_raises(self, tmp_path: Path) -> None:
        """
        목적: 같은 종목 · 날짜 · 검사가 두 줄이면 멈춘다 — 어느 근거가 맞는지 알 수 없다

        Given: 같은 (QQQ, 2020-03-13, 짝 차이) 두 줄
        When: load_pass_list
        Then: ValueError (「중복」)
        """
        # Given
        path = _write_pass_list(
            tmp_path / "pass_list.csv",
            ["QQQ,2020-03-13,짝 차이,사유 하나,근거 하나", "QQQ,2020-03-13,짝 차이,사유 둘,근거 둘"],
        )

        # When & Then
        with pytest.raises(ValueError, match="중복"):
            load_pass_list(path)

    def test_wrong_header_raises(self, tmp_path: Path) -> None:
        """
        목적: 머리가 다르면 멈춘다 — 열 순서가 바뀌면 사유가 근거 자리에 읽힌다

        Given: 머리 「종목,날짜,검사,근거,사유」
        When: load_pass_list
        Then: ValueError (「머리」)
        """
        # Given
        path = tmp_path / "pass_list.csv"
        path.write_text("종목,날짜,검사,근거,사유\n", encoding="utf-8-sig")

        # When & Then
        with pytest.raises(ValueError, match="머리"):
            load_pass_list(path)


class TestRemainingFailures:
    """패스 목록이 놓아주는 실패 — 같은 종목 · 날짜 · 검사만"""

    def test_only_matching_failures_are_released(self) -> None:
        """
        목적: 종목 · 날짜 · 검사가 모두 같은 실패만 놓아준다 — 같은 날의 다른 검사, 같은 검사의 다른 날은 남는다

        Given: 실패 셋 (QQQ 03-13 짝 차이 · QQQ 03-13 두 출처 차이 · QQQ 03-12 짝 차이), 패스 목록 (QQQ 03-13 짝 차이)
        When: remaining_failures
        Then: 뒤의 둘이 남는다
        """
        # Given
        failures = [
            NewDayFailure("QQQ", DAYS[4], Check.PAIR, "차이"),
            NewDayFailure("QQQ", DAYS[4], Check.COIN_TWO_SOURCES, "차이"),
            NewDayFailure("QQQ", DAYS[3], Check.PAIR, "차이"),
        ]
        entries = [PassEntry("QQQ", DAYS[4], Check.PAIR, "사유", "근거")]

        # When
        remaining = remaining_failures(failures, entries)

        # Then
        assert remaining == failures[1:]
