"""
domestic 모듈 테스트 — 국내 수정주가(C-2): KRX 기준가 사슬과 야후 분배 대조

이 파일은 무엇을 검증하나요?
1. 공식 등락률이 원본가 하루 변화와 표기 자릿수의 반 단위 밖인 날만 「기준가가 바뀐 날」인가? (착수 전 측정 ① — 2자리)
2. 기준가가 바뀐 날 그 앞 값 전체에 「기준가 ÷ 전날 종가」를 곱해, 마지막 날 값이 원본가와 같은가? (결정 Q14)
3. 기준가가 내려간 날의 금액은 같은 날 야후 분배금이 0 ≤ 야후 − KRX < 5원이면 야후 금액, 아니면 KRX 차이인가?
4. 야후 분배 대조의 어긋남(금액 다름 · 야후 기록 없음 · 야후에만 · 기준가 상승)을 날짜순으로 내는가? (결정 Q28)

왜 중요한가요?
KRX 는 분배락일에 기준가를 분배금만큼(5원 호가 단위) 내린다 — 원본가의 하루 등락에는 분배가 빠져 있고, 기준가 하나가
그 날을 알려준다. 기준가를 놓치거나 잘못 쓰면 그 앞 전 구간의 수익률이 에러 없이 틀린다.
"""

from datetime import date

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
    PRICE_COLUMNS,
    REQUIRED_COLUMNS,
)
from quant_data.domestic import OFFICIAL_RATE_DECIMALS, YAHOO_AMOUNT_WINDOW_WON, build_kr_adjusted, is_base_changed

DAYS = [date(2024, 7, 22), date(2024, 7, 23), date(2024, 7, 24), date(2024, 7, 25), date(2024, 7, 26)]
CLOSES = [10000, 10100, 10050, 10200, 10300]
EX_DAY = 2  # 분배락 · 액션이 걸리는 행


def _raw(
    closes: list[int] | None = None,
    *,
    bases: dict[int, int] | None = None,
    rates: dict[int, float] | None = None,
) -> pd.DataFrame:
    """KRX 원본가 — 기준가는 주지 않으면 전날 종가(첫 행은 자기 종가), 공식 등락률은 주지 않으면 종가 ÷ 기준가 − 1 의 2자리."""
    values = closes if closes is not None else CLOSES
    base_list: list[int] = []
    rate_list: list[float] = []
    for i, close in enumerate(values):
        base = (bases or {}).get(i, values[i - 1] if i > 0 else close)
        base_list.append(base)
        given = (rates or {}).get(i)
        rate_list.append(given if given is not None else round((close / base - 1) * 100, OFFICIAL_RATE_DECIMALS))
    return pd.DataFrame(
        {
            COL_DATE: DAYS[: len(values)],
            COL_OPEN: [v - 20 for v in values],
            COL_HIGH: [v + 50 for v in values],
            COL_LOW: [v - 60 for v in values],
            COL_CLOSE: values,
            COL_VOLUME: [1000 + i for i in range(len(values))],
            COL_BASE_PRICE: base_list,
            COL_CHANGE_RATE: rate_list,
        }
    ).astype({col: "int64" for col in [*PRICE_COLUMNS, COL_BASE_PRICE]})


def _dividends(records: dict[date, float]) -> pd.DataFrame:
    return pd.DataFrame({COL_DATE: list(records), COL_VALUE: list(records.values())})


def _expected(raw: pd.DataFrame, factor_before_ex_day: float) -> pd.DataFrame:
    """분배락 행 앞의 가격 전체에 한 비율을 곱한 표."""
    expected = raw[REQUIRED_COLUMNS].copy()
    expected[PRICE_COLUMNS] = expected[PRICE_COLUMNS].astype(float)
    expected.loc[: EX_DAY - 1, PRICE_COLUMNS] *= factor_before_ex_day
    return expected


class TestIsBaseChanged:
    """기준가가 바뀐 날 — 공식 등락률이 원본가 하루 변화와 반 단위(0.005%p) 밖"""

    @pytest.mark.parametrize(("rate", "changed"), [(1.0, False), (1.004, False), (1.006, True), (0.66, True)])
    def test_half_unit_boundary(self, rate: float, changed: bool) -> None:
        """
        목적: 등락률 2자리 반올림으로 설명되면 바뀌지 않은 날, 넘으면 바뀐 날이다 (경계)

        Given: 전날 10,000원 → 10,100원 (+1.00%), 공식 등락률 rate
        When: is_base_changed
        Then: 1.00 · 1.004 는 아님, 1.006 · 0.66 은 바뀜
        """
        assert is_base_changed(10000, 10100, rate) is changed


class TestBuildKrAdjusted:
    """C-2 — KRX 기준가 사슬"""

    def test_no_base_change_keeps_raw_values(self) -> None:
        """
        목적: 기준가가 한 번도 바뀌지 않으면 수정주가 = 원본가, 대조할 어긋남도 없다

        Given: 기준가 = 전날 종가인 5일, 분배 기록 없음
        When: build_kr_adjusted
        Then: 원본가의 필수 열과 같은 값(실수), 어긋남 없음
        """
        # Given
        raw = _raw()

        # When
        result = build_kr_adjusted(raw, _dividends({}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 1.0))
        assert result.notes == ()

    def test_yahoo_amount_within_window_is_used(self) -> None:
        """
        목적: 같은 날 야후 분배금이 KRX 기준가 차이보다 0 ~ 4원 크면 야후 금액을 쓴다 — KRX 는 분배금을 5원 호가 단위로
              맞춰 기준가를 내리므로 야후 금액이 정확한 값이다. 마지막 날 값은 원본가 그대로다

        Given: 셋째 날 기준가 10,030 (전날 10,100 에서 70원), 야후 그날 72원
        When: build_kr_adjusted
        Then: 앞 두 행 × (10,100 − 72) ÷ 10,100, 셋째 행부터 원본가, 어긋남 없음
        """
        # Given
        raw = _raw(bases={EX_DAY: 10030})

        # When
        result = build_kr_adjusted(raw, _dividends({DAYS[EX_DAY]: 72.0}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, (10100 - 72) / 10100))
        assert result.notes == ()

    @pytest.mark.parametrize(("yahoo", "pattern"), [(70.0 + YAHOO_AMOUNT_WINDOW_WON, "금액 다름"), (69.0, "금액 다름")])
    def test_yahoo_amount_outside_window_uses_krx(self, yahoo: float, pattern: str) -> None:
        """
        목적: 야후 금액이 KRX 차이보다 5원 이상 크거나 작으면 KRX 차이를 쓰고 어긋남으로 적는다 (경계 — 5원 · −1원)

        Given: 셋째 날 기준가 차이 70원, 야후 그날 75원 / 69원
        When: build_kr_adjusted
        Then: 앞 두 행 × (10,100 − 70) ÷ 10,100, 어긋남 한 줄(날짜 · 「금액 다름」)
        """
        # Given
        raw = _raw(bases={EX_DAY: 10030})

        # When
        result = build_kr_adjusted(raw, _dividends({DAYS[EX_DAY]: yahoo}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 10030 / 10100))
        assert len(result.notes) == 1
        assert str(DAYS[EX_DAY]) in result.notes[0] and pattern in result.notes[0]

    def test_krx_only_distribution_uses_krx_and_is_noted(self) -> None:
        """
        목적: 야후에 분배 기록이 없는 날도 KRX 기준가로 반영하고 어긋남으로 적는다 — 야후에 없는 분배(2003 ~ 2006 ·
              2022-07-28 등 11일)를 놓치지 않는다

        Given: 셋째 날 기준가 차이 250원, 야후 기록 없음
        When: build_kr_adjusted
        Then: 앞 두 행 × (10,100 − 250) ÷ 10,100, 어긋남에 「야후 기록 없음」
        """
        # Given
        raw = _raw(bases={EX_DAY: 9850})

        # When
        result = build_kr_adjusted(raw, _dividends({}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 9850 / 10100))
        assert len(result.notes) == 1 and "야후 기록 없음" in result.notes[0]

    def test_yahoo_only_distribution_is_noted_without_adjusting(self) -> None:
        """
        목적: 기준가가 바뀌지 않은 날의 야후 분배 기록은 반영하지 않고 어긋남으로 적는다 — KRX 기준가가 날짜의 기준이다
              (069500 2022-10-27 · 261250 2025-12-24)

        Given: 기준가 변화 없음, 야후 넷째 날 85원
        When: build_kr_adjusted
        Then: 수정주가 = 원본가, 어긋남에 「야후에만」
        """
        # Given
        raw = _raw()

        # When
        result = build_kr_adjusted(raw, _dividends({DAYS[3]: 85.0}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 1.0))
        assert len(result.notes) == 1 and "야후에만" in result.notes[0] and str(DAYS[3]) in result.notes[0]

    def test_yahoo_record_outside_raw_period_is_ignored(self) -> None:
        """
        목적: 원본가 기간 밖(첫 행 이전 · 마지막 행 뒤)의 야후 기록은 견줄 KRX 날이 없어 적지 않는다 (경계)

        Given: 야후 기록이 첫 행 날짜와 마지막 행 다음 날
        When: build_kr_adjusted
        Then: 어긋남 없음
        """
        # When
        result = build_kr_adjusted(_raw(), _dividends({DAYS[0]: 50.0, date(2024, 7, 29): 60.0}))

        # Then
        assert result.notes == ()

    def test_base_above_previous_close_scales_up_and_is_noted(self) -> None:
        """
        목적: 기준가가 전날 종가보다 높은 날(병합 등)도 같은 방식으로 앞 값에 「기준가 ÷ 전날 종가」를 곱하고 적는다 —
              KRX 기준가가 분할 · 병합을 반영하므로 국내 분할 기록 없이 맞는다

        Given: 셋째 날 1:2 병합 — 기준가 20,200 (전날 10,100 의 두 배), 종가 20,100
        When: build_kr_adjusted
        Then: 앞 두 행 × 2, 어긋남에 「기준가 상승」
        """
        # Given
        raw = _raw([10000, 10100, 20100, 20300, 20500], bases={EX_DAY: 20200})

        # When
        result = build_kr_adjusted(raw, _dividends({}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 2.0))
        assert len(result.notes) == 1 and "기준가 상승" in result.notes[0]

    def test_inconsistent_base_with_consistent_rate_is_not_a_change(self) -> None:
        """
        목적: 공식 등락률이 원본가 하루 변화와 맞으면 대비가 어긋나도 기준가 = 전날 종가로 본다 — 2005년 069500 4일
              (대비만 ±10 ~ 30원 어긋남)을 분배로 잘못 넣지 않는다

        Given: 셋째 날 기준가 칸 10,090 (전날 10,100), 공식 등락률 = 원본가 하루 변화(−0.50%)
        When: build_kr_adjusted
        Then: 수정주가 = 원본가, 어긋남 없음
        """
        # Given
        raw = _raw(bases={EX_DAY: 10090}, rates={EX_DAY: round((10050 / 10100 - 1) * 100, 2)})

        # When
        result = build_kr_adjusted(raw, _dividends({}))

        # Then
        pd.testing.assert_frame_equal(result.prices, _expected(raw, 1.0))
        assert result.notes == ()

    def test_two_changes_compound_and_notes_are_in_date_order(self) -> None:
        """
        목적: 두 번의 기준가 변화는 곱으로 쌓이고, 어긋남은 날짜순이다

        Given: 둘째 날 기준가 차이 100원(야후 없음), 넷째 날 차이 50원(야후 52원)
        When: build_kr_adjusted
        Then: 첫 행 × (9,900 ÷ 10,000) × (10,050 − 52) ÷ 10,050, 어긋남 한 줄(둘째 날)
        """
        # Given
        raw = _raw(bases={1: 9900, 3: 10000})

        # When
        result = build_kr_adjusted(raw, _dividends({DAYS[3]: 52.0}))

        # Then
        second = (10050 - 52) / 10050
        assert result.prices[COL_CLOSE].tolist() == pytest.approx(
            [10000 * 9900 / 10000 * second, 10100 * second, 10050 * second, 10200, 10300], rel=1e-12
        )
        assert len(result.notes) == 1 and str(DAYS[1]) in result.notes[0]

    def test_input_is_not_changed(self) -> None:
        """
        목적: 원본가 표를 바꾸지 않는다 — 원본가 파일은 KRX 값 그대로 저장된다

        Given: 분배 하나가 있는 원본가와 그 사본
        When: build_kr_adjusted
        Then: 원본가 표가 사본과 같다
        """
        # Given
        raw = _raw(bases={EX_DAY: 10030})
        before = raw.copy()

        # When
        build_kr_adjusted(raw, _dividends({DAYS[EX_DAY]: 72.0}))

        # Then
        pd.testing.assert_frame_equal(raw, before)

    def test_non_positive_base_raises(self) -> None:
        """
        목적: 기준가가 0 이하면 KRX 자료가 깨진 것이라 멈춘다 — 메우지 않는다

        Given: 셋째 날 기준가 0, 공식 등락률이 원본가 변화와 다름
        When: build_kr_adjusted
        Then: ValueError (「기준가」)
        """
        # Given
        raw = _raw(bases={EX_DAY: 0}, rates={EX_DAY: 5.0})

        # When & Then
        with pytest.raises(ValueError, match="기준가"):
            build_kr_adjusted(raw, _dividends({}))
