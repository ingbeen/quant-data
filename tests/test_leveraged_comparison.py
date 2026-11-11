"""레버리지 합성 검증 테스트

검증 ④ (가정만 바꾼 판)와 배당 보정 폭의 계산을 검증한다. ② 추적 · ③ 펀드 대조는 상장 뒤 시뮬레이션이 필요해
고정 시점 기록으로 굳혔다(결정 Q32).

왜 중요한가요?
합성 생성은 이 숫자를 저장 · 표시만 하고 멈추지 않는다(합격선 없음). 계산이 틀리면 틀린 판단 근거가 에러 없이 남는다.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from quant_data.constants import ANNUAL_DAYS, COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME
from quant_data.leveraged.comparison import (
    VARIANT_ADOPTED,
    VARIANT_DIVIDEND,
    VARIANT_UNCAPPED,
    VARIANT_ZERO_SPREAD,
    annual_gap_rate,
    assumption_variants,
)
from quant_data.leveraged.constants import COL_EXPENSE_DATE, COL_EXPENSE_VALUE, COL_FFR_DATE, COL_FFR_VALUE
from quant_data.leveraged.synthetic import build_cost_inputs, simulate_leveraged


def _df(dates: list[date], closes: list[float], *, opens: list[float] | None = None) -> pd.DataFrame:
    opens = opens if opens is not None else closes
    return pd.DataFrame(
        {
            COL_DATE: dates,
            COL_OPEN: opens,
            COL_HIGH: [max(o, c) for o, c in zip(opens, closes, strict=True)],
            COL_LOW: [min(o, c) for o, c in zip(opens, closes, strict=True)],
            COL_CLOSE: closes,
            COL_VOLUME: [0] * len(closes),
        }
    )


class TestAnnualGapRate:
    """배당 보정 폭 — 한 연 수익을 다른 연 수익으로 맞추는 연 비율"""

    def test_ratio_not_difference(self):
        """
        목적: 보정 폭은 두 연 수익의 비로 정한다 — 단순 차(0.57%p)를 복리로 붙이면 실물 QQQ(10.71%)를 넘는다

        Given: 지수 10.14%, 실물 10.71%
        When: annual_gap_rate
        Then: 1.1071 ÷ 1.1014 − 1 (약 0.0052), 단순 차 0.0057 보다 작다
        """
        # When
        gap = annual_gap_rate(10.14, 10.71)

        # Then
        assert gap == pytest.approx(1.1071 / 1.1014 - 1, abs=1e-15)
        assert gap < 0.0057

    def test_zero_when_equal(self):
        """
        목적: 두 연 수익이 같으면 보정하지 않는다 (경계)

        Given: 같은 연 수익
        When: annual_gap_rate
        Then: 0
        """
        # When / Then
        assert annual_gap_rate(8.0, 8.0) == pytest.approx(0.0, abs=1e-15)


class TestAssumptionVariants:
    """검증 ④ — 같은 기초로 가정만 바꾼 판의 Buy & Hold 연 수익 · 최악 낙폭"""

    @staticmethod
    def _underlying(start: date, n: int) -> pd.DataFrame:
        dates = [start + timedelta(days=i) for i in range(n)]
        closes = [100.0 * (1.01 if i % 2 else 0.995) ** i for i in range(n)]
        return _df(dates, closes)

    @staticmethod
    def _ffr_df() -> pd.DataFrame:
        return pd.DataFrame({COL_FFR_DATE: ["1998-12", "1999-01"], COL_FFR_VALUE: [0.08, 0.08]})

    @staticmethod
    def _expense_df() -> pd.DataFrame:
        return pd.DataFrame({COL_EXPENSE_DATE: ["2010-02"], COL_EXPENSE_VALUE: [0.0095]})

    def _run(self, start: date, n: int = 10) -> list:
        underlying = self._underlying(start, n)
        return assumption_variants(
            underlying,
            self._ffr_df(),
            self._expense_df(),
            [("TQQQ", 3.0), ("QLD", 2.0)],
            end=underlying[COL_DATE].iloc[-1],
            dividend_gap_rate=0.0057,
        )

    def test_rows_are_variants_by_product(self):
        """
        목적: 판 넷 × 상품의 행을 판 순서 · 상품 순서로 낸다

        Given: 상품 TQQQ · QLD
        When: assumption_variants
        Then: (채택, TQQQ), (채택, QLD), (상한 없음, TQQQ) … 8행
        """
        # When
        rows = self._run(date(1998, 12, 20))

        # Then
        variants = [VARIANT_ADOPTED, VARIANT_UNCAPPED, VARIANT_ZERO_SPREAD, VARIANT_DIVIDEND]
        assert [(r.variant, r.product, r.leverage) for r in rows] == [
            (v, p, lev) for v in variants for p, lev in (("TQQQ", 3.0), ("QLD", 2.0))
        ]

    def test_no_dividend_variant_without_gap(self):
        """
        목적: 보정 폭을 주지 않으면(None) 배당 보정 판을 내지 않고 나머지 판은 그대로다 — 기초가 배당을 담으면(VFINX)
              보정할 것이 없다

        Given: 같은 기초 · 상품, 보정 폭 None 과 0.0057
        When: assumption_variants
        Then: None 은 (채택 · 상한 없음 · 가산금리 0) × 상품 6행이고, 0.0057 판의 앞 6행과 같다
        """
        # Given
        underlying = self._underlying(date(1998, 12, 20), 10)

        # When
        rows = assumption_variants(
            underlying,
            self._ffr_df(),
            self._expense_df(),
            [("TQQQ", 3.0), ("QLD", 2.0)],
            end=underlying[COL_DATE].iloc[-1],
            dividend_gap_rate=None,
        )

        # Then
        variants = [VARIANT_ADOPTED, VARIANT_UNCAPPED, VARIANT_ZERO_SPREAD]
        assert [(r.variant, r.product) for r in rows] == [(v, p) for v in variants for p in ("TQQQ", "QLD")]
        assert rows == self._run(date(1998, 12, 20))[: len(rows)]

    def test_adopted_equals_buy_and_hold_of_synthetic(self):
        """
        목적: 채택 판은 합성 파일과 같은 비용 입력으로 만든 시세의 종가 Buy & Hold 다 — 연 수익은 달력일 기준

        Given: 1998-12 걸친 10일
        When: assumption_variants
        Then: 채택 TQQQ 의 연 수익 · 최악 낙폭 = simulate_leveraged 종가로 직접 잰 값
        """
        # Given
        underlying = self._underlying(date(1998, 12, 20), 10)
        costs = build_cost_inputs(self._ffr_df(), self._expense_df(), "1998-12")
        closes = simulate_leveraged(underlying, 3.0, costs)[COL_CLOSE]
        days = (underlying[COL_DATE].iloc[-1] - underlying[COL_DATE].iloc[0]).days
        expected_cagr = ((closes.iloc[-1] / closes.iloc[0]) ** (ANNUAL_DAYS / days) - 1) * 100
        expected_mdd = (closes / closes.cummax() - 1).min() * 100

        # When
        adopted = next(r for r in self._run(date(1998, 12, 20)) if r.variant == VARIANT_ADOPTED and r.product == "TQQQ")

        # Then
        assert adopted.cagr == pytest.approx(expected_cagr, abs=1e-9)
        assert adopted.mdd == pytest.approx(expected_mdd, abs=1e-9)

    def test_cap_matters_only_before_1999(self):
        """
        목적: 상한은 1998-12 까지만 걸리므로 1999년 뒤만 있는 구간에서는 채택 = 상한 없음, 1998-12 고금리 달이 있으면 채택이 더 높다

        Given: 1999-01 만 있는 구간 · 1998-12 를 걸친 구간 (금리 8%)
        When: assumption_variants
        Then: 앞은 연 수익이 같고, 뒤는 채택 > 상한 없음
        """

        # Given / When
        def cagr(rows: list, variant: str) -> float:
            return next(r.cagr for r in rows if r.variant == variant and r.product == "TQQQ")

        only_1999 = self._run(date(1999, 1, 5))
        across = self._run(date(1998, 12, 20))

        # Then
        assert cagr(only_1999, VARIANT_ADOPTED) == pytest.approx(cagr(only_1999, VARIANT_UNCAPPED), abs=1e-12)
        assert cagr(across, VARIANT_ADOPTED) > cagr(across, VARIANT_UNCAPPED)

    def test_zero_spread_and_dividend_raise_return(self):
        """
        목적: 가산금리 0 판과 배당 보정 판은 채택 판보다 연 수익이 높다 — 비용을 덜 빼거나 기초 수익을 더한다

        Given: 1998-12 를 걸친 구간
        When: assumption_variants
        Then: 두 판의 연 수익 > 채택
        """
        # When
        rows = self._run(date(1998, 12, 20))
        by_variant = {r.variant: r.cagr for r in rows if r.product == "QLD"}

        # Then
        assert by_variant[VARIANT_ZERO_SPREAD] > by_variant[VARIANT_ADOPTED]
        assert by_variant[VARIANT_DIVIDEND] > by_variant[VARIANT_ADOPTED]

    def test_dividend_drift_compounds_exactly_on_calendar_days(self):
        """
        목적: 배당 보정 판의 기초는 연 수익이 정확히 보정 폭만큼 복리로 오른다 — 연 수익을 달력일로 재므로 달력일 비례로 붙인다
              (거래일 수로 나누면 해마다 거래일이 다른 만큼 어긋난다)

        Given: 비용이 0 인 1배 (운용비율 0, 배율 1 이라 금리 비용 없음), 띄엄띄엄한 날짜(주말 포함), 보정 폭 0.0052
        When: assumption_variants
        Then: 배당 보정 판의 연 수익 = (1 + 채택) × (1 + 0.0052) − 1
        """
        # Given
        dates = [date(1999, 1, 4), date(1999, 1, 5), date(1999, 1, 8), date(1999, 1, 11), date(1999, 1, 20)]
        underlying = _df(dates, [100.0, 101.0, 99.5, 102.0, 103.5])
        no_expense = pd.DataFrame({COL_EXPENSE_DATE: ["1999-01"], COL_EXPENSE_VALUE: [0.0]})
        gap = 0.0052

        # When
        rows = assumption_variants(
            underlying,
            self._ffr_df(),
            no_expense,
            [("X", 1.0)],
            end=dates[-1],
            dividend_gap_rate=gap,
        )

        # Then
        by_variant = {r.variant: r.cagr for r in rows}
        expected = ((1 + by_variant[VARIANT_ADOPTED] / 100) * (1 + gap) - 1) * 100
        assert by_variant[VARIANT_DIVIDEND] == pytest.approx(expected, abs=1e-9)

    def test_rejects_window_under_two_days(self):
        """
        목적: 구간에 날이 2일 미만이면 멈춘다 (경계)

        Given: 끝날이 기초 첫날
        When: assumption_variants
        Then: ValueError
        """
        # Given
        underlying = self._underlying(date(1999, 1, 5), 5)

        # When / Then
        with pytest.raises(ValueError, match="2"):
            assumption_variants(
                underlying,
                self._ffr_df(),
                self._expense_df(),
                [("TQQQ", 3.0)],
                end=underlying[COL_DATE].iloc[0],
                dividend_gap_rate=0.0057,
            )
