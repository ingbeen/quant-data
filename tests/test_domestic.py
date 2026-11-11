"""
domestic 모듈 테스트 — 국내 수정주가(C-2) · 국내 분할 기록 · KRX 수정주가 대조

이 파일은 무엇을 검증하나요?
1. C-2: KRX 원본가에 분배일마다 그 앞 값 전체 × (1 − 분배금 ÷ 전 거래일 원본 종가)를 곱하는가? 국내 분할 기록의 비율도
   같은 방식(그 앞 값 × 1 ÷ 비율)으로 입히는가? (결정 Q14)
2. 국내 분할 기록 파일이 모든 칸(종목 · 날짜 · 비율 · 근거)을 갖춘 줄만 받는가?
3. KRX 수정주가와 견줘 원 단위 반올림만으로 설명되지 않는 날만 어긋난 날로 세는가? (결정 Q28)

왜 중요한가요?
KRX 는 수정주가를 최근 3,000거래일만 준다. 상장일부터의 수정주가는 원본가와 분배 기록으로 만들어야 하고,
분배 한 건이 빠지거나 분할이 섞이면 그 앞 전 구간의 수익률이 에러 없이 틀린다.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_data.constants import (
    COL_CHANGE_RATE,
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    PRICE_COLUMNS,
    REQUIRED_COLUMNS,
)
from quant_data.domestic import KrAction, build_kr_adjusted, krx_mismatch_days, load_kr_actions, split_ratios_for

DAYS = [date(2024, 7, 22), date(2024, 7, 23), date(2024, 7, 24), date(2024, 7, 25), date(2024, 7, 26)]
CLOSES = [10000, 10100, 10050, 10200, 10300]


def _raw(closes: list[int] | None = None, dates: list[date] | None = None) -> pd.DataFrame:
    """KRX 원본가 — 원 단위 정수, 시가 · 고가 · 저가는 종가에서 일정 원 떨어짐, 공식 등락률 열 포함."""
    values = closes if closes is not None else CLOSES
    return pd.DataFrame(
        {
            COL_DATE: dates if dates is not None else DAYS[: len(values)],
            COL_OPEN: [v - 20 for v in values],
            COL_HIGH: [v + 50 for v in values],
            COL_LOW: [v - 60 for v in values],
            COL_CLOSE: values,
            COL_VOLUME: [1000 + i for i in range(len(values))],
            COL_CHANGE_RATE: [0.0] * len(values),
        }
    ).astype({col: "int64" for col in PRICE_COLUMNS})


def _dividends(records: dict[date, float]) -> pd.Series:
    return pd.Series(records, dtype=float)


class TestBuildKrAdjusted:
    """C-2 — KRX 원본가 + 야후 분배 기록 (+ 국내 분할 기록)"""

    def test_no_events_keeps_raw_values(self) -> None:
        """
        목적: 분배 · 분할 기록이 없으면 원본가 그대로다 — 열은 시세 표 열이고 공식 등락률은 남기지 않는다

        Given: 5일 원본가, 기록 없음
        When: build_kr_adjusted
        Then: 열 = REQUIRED_COLUMNS, 가격 · 거래량이 원본가와 같다
        """
        # Given
        raw = _raw()

        # When
        adjusted = build_kr_adjusted(raw, _dividends({}), {})

        # Then
        assert list(adjusted.columns) == REQUIRED_COLUMNS
        assert adjusted[COL_CLOSE].tolist() == pytest.approx([float(c) for c in CLOSES], abs=1e-12)
        assert adjusted[COL_VOLUME].tolist() == raw[COL_VOLUME].tolist()

    def test_dividend_scales_all_rows_before_ex_day(self) -> None:
        """
        목적: 분배일 앞 행 전체에 (1 − 분배금 ÷ 전 거래일 원본 종가)를 곱하고, 분배일부터는 원본가 그대로다 —
              마지막 날은 원본가와 같다(수정주가는 지금 값에 맞춘다)

        Given: 07-24 분배금 101원 (전 거래일 종가 10,100 → 비율 0.99)
        When: build_kr_adjusted
        Then: 07-22 · 07-23 의 네 가격 = 원본가 × 0.99, 07-24 부터 원본가
        """
        # Given
        raw = _raw()

        # When
        adjusted = build_kr_adjusted(raw, _dividends({DAYS[2]: 101.0}), {})

        # Then
        for col in PRICE_COLUMNS:
            expected = [raw[col].iloc[0] * 0.99, raw[col].iloc[1] * 0.99, *raw[col].iloc[2:].astype(float)]
            assert adjusted[col].tolist() == pytest.approx(expected, abs=1e-9)

    def test_two_dividends_compound(self) -> None:
        """
        목적: 분배가 둘이면 앞쪽 행에 두 비율이 겹쳐 곱해진다

        Given: 07-23 분배 100원(비율 0.99) · 07-25 분배 100.5원(전날 종가 10,050 → 비율 0.99)
        When: build_kr_adjusted
        Then: 07-22 종가 = 10,000 × 0.99 × 0.99, 07-23 · 07-24 = 원본 × 0.99, 07-25 부터 원본
        """
        # Given
        raw = _raw()

        # When
        adjusted = build_kr_adjusted(raw, _dividends({DAYS[1]: 100.0, DAYS[3]: 100.5}), {})

        # Then
        assert adjusted[COL_CLOSE].tolist() == pytest.approx(
            [10000 * 0.99 * 0.99, 10100 * 0.99, 10050 * 0.99, 10200.0, 10300.0], abs=1e-9
        )

    def test_record_on_non_trading_day_applies_to_next_trading_day(self) -> None:
        """
        목적: 거래일이 아닌 날의 기록은 그다음 거래일에 건다 — 판정 규칙 ① 과 같은 규칙. 날짜가 맞지 않는다고 버리면
              분배 한 건이 조용히 빠진다

        Given: 07-26(금) 다음 거래일이 07-29(월)인 원본가, 07-27(토) 분배 103원 (전 거래일 07-26 종가 10,300 → 비율 0.99)
        When: build_kr_adjusted
        Then: 07-26 까지 × 0.99, 07-29 원본
        """
        # Given
        dates = [*DAYS, date(2024, 7, 29)]
        raw = _raw([*CLOSES, 10400], dates)

        # When
        adjusted = build_kr_adjusted(raw, _dividends({date(2024, 7, 27): 103.0}), {})

        # Then
        assert adjusted[COL_CLOSE].iloc[4] == pytest.approx(10300 * 0.99, abs=1e-9)
        assert adjusted[COL_CLOSE].iloc[5] == pytest.approx(10400.0, abs=1e-9)

    def test_record_on_first_row_changes_nothing(self) -> None:
        """
        목적: 첫 행 날짜의 기록은 그 앞 행이 없어 아무 가격도 바꾸지 않는다 (경계) — 원본가가 시작하기 전의 분배는 반영할 곳이 없다

        Given: 첫 날(07-22) 분배 100원
        When: build_kr_adjusted
        Then: 원본가 그대로
        """
        # When
        adjusted = build_kr_adjusted(_raw(), _dividends({DAYS[0]: 100.0}), {})

        # Then
        assert adjusted[COL_CLOSE].tolist() == pytest.approx([float(c) for c in CLOSES], abs=1e-12)

    def test_record_after_last_row_changes_nothing(self) -> None:
        """
        목적: 마지막 행 뒤의 기록은 넣지 않는다 (경계) — 넣으면 구간 전체의 수준만 낮아져 마지막 날 값이 원본가와 달라진다.
              수익률은 바뀌지 않으므로 그 분배는 다음 갱신에서 그날이 붙을 때 반영된다

        Given: 마지막 행(07-26) 뒤 07-29 분배 103원
        When: build_kr_adjusted
        Then: 원본가 그대로
        """
        # When
        adjusted = build_kr_adjusted(_raw(), _dividends({date(2024, 7, 29): 103.0}), {})

        # Then
        assert adjusted[COL_CLOSE].tolist() == pytest.approx([float(c) for c in CLOSES], abs=1e-12)

    def test_split_record_scales_rows_before_by_inverse_ratio(self) -> None:
        """
        목적: 국내 분할 기록의 비율(주식 수 배수)은 그날 앞 행에 1 ÷ 비율을 곱한다 — 원본가 파일은 KRX 값 그대로 두고
              수정주가만 이어지게 한다

        Given: 07-24 에 2:1 분할(20,000 → 10,050), 분할 기록 {07-24: 2.0}
        When: build_kr_adjusted
        Then: 07-22 · 07-23 = 원본 ÷ 2, 07-24 부터 원본
        """
        # Given
        raw = _raw([20000, 20200, 10050, 10200, 10300])

        # When
        adjusted = build_kr_adjusted(raw, _dividends({}), {DAYS[2]: 2.0})

        # Then
        assert adjusted[COL_CLOSE].tolist() == pytest.approx([10000.0, 10100.0, 10050.0, 10200.0, 10300.0], abs=1e-9)

    def test_input_is_not_changed(self) -> None:
        """
        목적: 원본가 표를 바꾸지 않는다 — 원본가 파일은 KRX 값 그대로 저장된다

        Given: 원본가 표와 그 복사본
        When: build_kr_adjusted(분배 하나)
        Then: 원본가 표가 복사본과 같다
        """
        # Given
        raw = _raw()
        before = raw.copy()

        # When
        build_kr_adjusted(raw, _dividends({DAYS[2]: 101.0}), {})

        # Then
        pd.testing.assert_frame_equal(raw, before)

    def test_dividend_not_below_previous_close_raises(self) -> None:
        """
        목적: 분배금이 전 거래일 종가 이상이면 비율이 0 이하라 멈춘다 — 그대로 곱하면 앞 구간이 0 · 음수가 된다

        Given: 07-24 분배금 10,100원 (= 전 거래일 종가)
        When: build_kr_adjusted
        Then: ValueError (「분배금」)
        """
        # When & Then
        with pytest.raises(ValueError, match="분배금"):
            build_kr_adjusted(_raw(), _dividends({DAYS[2]: 10100.0}), {})


KR_ACTIONS_HEADER = "종목,날짜,비율,근거"


def _write_actions(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([KR_ACTIONS_HEADER, *rows]) + "\n", encoding="utf-8-sig")
    return path


class TestLoadKrActions:
    """국내 분할 기록 — 사람이 운용사 공시를 확인한 뒤 적는 파일"""

    def test_reads_entries_and_ratios_by_ticker(self, tmp_path: Path) -> None:
        """
        목적: 칸을 모두 갖춘 줄을 읽고, 종목마다 날짜 → 비율로 꺼낸다

        Given: 두 종목의 분할 기록 한 줄씩
        When: load_kr_actions → split_ratios_for
        Then: KrAction 둘, 069500 의 비율 {2024-07-24: 2.0}
        """
        # Given
        path = _write_actions(
            tmp_path / "kr_actions.csv",
            ["069500,2024-07-24,2,운용사 공시 2024-07-10 액면분할 2:1", "229200,2023-03-02,0.2,운용사 공시 병합 5:1"],
        )

        # When
        actions = load_kr_actions(path)

        # Then
        assert actions == [
            KrAction("069500", date(2024, 7, 24), 2.0, "운용사 공시 2024-07-10 액면분할 2:1"),
            KrAction("229200", date(2023, 3, 2), 0.2, "운용사 공시 병합 5:1"),
        ]
        assert split_ratios_for(actions, "069500") == {date(2024, 7, 24): 2.0}

    def test_header_only_is_empty(self, tmp_path: Path) -> None:
        """
        목적: 머리만 있는 파일은 빈 목록이다 (경계) — 처음 만든 국내 분할 기록의 모양

        Given: 머리만 있는 파일
        When: load_kr_actions
        Then: []
        """
        # When & Then
        assert load_kr_actions(_write_actions(tmp_path / "kr_actions.csv", [])) == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """
        목적: 파일이 없으면 멈춘다 — 빈 기록으로 넘기면 지워진 분할 기록이 조용히 빠져 C-2 가 틀린다

        Given: 없는 경로
        When: load_kr_actions
        Then: FileNotFoundError
        """
        # When & Then
        with pytest.raises(FileNotFoundError):
            load_kr_actions(tmp_path / "kr_actions.csv")

    @pytest.mark.parametrize(
        ("row", "pattern"),
        [
            ("069500,2024-07-24,0,공시", "비율"),
            ("069500,2024-07-24,-2,공시", "비율"),
            ("069500,2024-07-24,두배,공시", "비율"),
            ("069500,2024-07-24,2,", "근거"),
            ("069500,24-07-24,2,공시", "날짜"),
        ],
        ids=["zero", "negative", "not_number", "no_evidence", "bad_date"],
    )
    def test_bad_row_raises(self, tmp_path: Path, row: str, pattern: str) -> None:
        """
        목적: 비율이 양수가 아니거나 숫자가 아닌 줄, 근거가 빈 줄, 날짜 모양이 틀린 줄은 받지 않는다

        Given: 잘못된 줄 하나
        When: load_kr_actions
        Then: ValueError (잘못된 칸 이름)
        """
        # Given
        path = _write_actions(tmp_path / "kr_actions.csv", [row])

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            load_kr_actions(path)

    def test_duplicate_ticker_day_raises(self, tmp_path: Path) -> None:
        """
        목적: 같은 종목 · 날짜가 두 줄이면 멈춘다 — 어느 비율이 맞는지 알 수 없다

        Given: 069500 · 2024-07-24 두 줄
        When: load_kr_actions
        Then: ValueError (「중복」)
        """
        # Given
        path = _write_actions(tmp_path / "kr_actions.csv", ["069500,2024-07-24,2,공시 하나", "069500,2024-07-24,4,공시 둘"])

        # When & Then
        with pytest.raises(ValueError, match="중복"):
            load_kr_actions(path)


def _built(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            COL_DATE: DAYS[: len(closes)],
            COL_OPEN: closes,
            COL_HIGH: closes,
            COL_LOW: closes,
            COL_CLOSE: closes,
            COL_VOLUME: 0,
        }
    )


class TestKrxMismatchDays:
    """C-2 ↔ KRX 수정주가 — 원 단위 반올림만으로 설명되지 않는 하루 수익률 차이가 있는 날 (Q28)"""

    def test_rounded_krx_values_have_no_mismatch(self) -> None:
        """
        목적: KRX 수정주가가 C-2 를 원 단위로 반올림한 값이면 어긋난 날이 없다

        Given: C-2 종가 9,999.6 · 10,100.4 · 10,049.5 · 10,200.2, KRX = 각 값의 원 단위 반올림
        When: krx_mismatch_days
        Then: []
        """
        # Given
        built = _built([9999.6, 10100.4, 10049.5, 10200.2])
        krx = _built([10000.0, 10100.0, 10050.0, 10200.0])

        # When & Then
        assert krx_mismatch_days(built, krx) == []

    def test_low_price_rounding_is_explained(self) -> None:
        """
        목적: 가격이 낮아 반올림 한 원이 수익률을 크게 흔들어도 반올림으로 설명되면 어긋난 날이 아니다 (경계) —
              퍼센트 기준을 고르면 가격 수준에 따라 오탐이 갈린다

        Given: C-2 1,000.4 → 1,001.4 (+0.0999%), KRX 1,000 → 1,001 (+0.1%)
        When: krx_mismatch_days
        Then: []
        """
        # Given
        built = _built([1000.4, 1001.4])
        krx = _built([1000.0, 1001.0])

        # When & Then
        assert krx_mismatch_days(built, krx) == []

    def test_missing_dividend_shows_on_its_day_only(self) -> None:
        """
        목적: 두 출처의 분배 기록이 다른 날은 그날 하루만 어긋난다 — 수준이 아니라 하루 수익률로 견주므로 그 앞 전 구간이
              어긋난 날로 쏟아지지 않는다(착수 전 측정: 069500 2,999일 중 2일)

        Given: C-2 는 07-24 분배(앞 행 × 0.99)를 반영, KRX 는 반영하지 않음
        When: krx_mismatch_days
        Then: [07-24]
        """
        # Given
        built = _built([10000 * 0.99, 10100 * 0.99, 10050.0, 10200.0, 10300.0])
        krx = _built([10000.0, 10100.0, 10050.0, 10200.0, 10300.0])

        # When & Then
        assert krx_mismatch_days(built, krx) == [DAYS[2]]

    def test_only_common_days_compared(self) -> None:
        """
        목적: KRX 수정주가가 있는 구간(최근 3,000거래일)만 견준다 — 그 앞은 견줄 값이 없어 어긋난 날로 세지 않는다

        Given: C-2 5일, KRX 는 뒤 3일만 (그 셋은 원 단위로 같음)
        When: krx_mismatch_days
        Then: []
        """
        # Given
        built = _built([9000.0, 9500.0, 10050.0, 10200.0, 10300.0])
        krx = _built([10050.0, 10200.0, 10300.0])
        krx[COL_DATE] = DAYS[2:]

        # When & Then
        assert krx_mismatch_days(built, krx) == []
