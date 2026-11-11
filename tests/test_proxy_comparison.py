"""대용 ↔ 실물 비교 테스트

대용 시세가 실물 ETF 를 얼마나 잘 따르는지 재는 함수의 계약을 검증한다.
겹치는 날 맞추기, 전체 · 기간별 지표, 이동 상관, 결과 표의 행 · 반올림을 다룬다.

왜 중요한가요?
합성 시세를 만들 때마다 이 값을 저장해, 상장 전 구간을 채운 대용이 실물과 얼마나 비슷한지 사람이 판단한다.
겹치는 날을 잘못 맞추거나 수익률 기준일이 하루 어긋나면, 대용이 실물과 다르게 움직이는데도 비슷하다고 읽게 된다.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_data.constants import (
    ANNUAL_DAYS,
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    ROUND_PERCENT,
    ROUND_RATIO,
)
from quant_data.synthetic.proxy_comparison import (
    COL_ACTUAL,
    COL_PROXY,
    DISPLAY_CAGR_DIFF,
    DISPLAY_DAILY_CORR,
    DISPLAY_MDD_DIFF,
    DISPLAY_PERIOD,
    DISPLAY_RETURN_DIFF,
    DISPLAY_ROLLING_MIN_DATE,
    DISPLAY_START,
    Period,
    align_closes,
    calendar_year_periods,
    count_unmatched_days,
    pair_summary_record,
    period_summary_records,
    rolling_correlation,
    round_for_display,
    summarize_pair,
    summarize_periods,
)

DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(8)]
REL_TOL = 1e-12

# 월 마지막 거래일이 넷(1 · 2 · 3 · 4월)인 날짜 — 월간 수익률이 셋 나온다
MONTH_DAYS = [
    date(2021, 1, 15),
    date(2021, 1, 29),
    date(2021, 2, 12),
    date(2021, 2, 26),
    date(2021, 3, 15),
    date(2021, 3, 31),
    date(2021, 4, 15),
    date(2021, 4, 30),
]
MONTH_PROXY = [100.0, 103.0, 101.0, 106.0, 104.0, 102.0, 108.0, 111.0]
MONTH_ACTUAL = [50.0, 51.0, 51.5, 52.0, 51.0, 50.5, 53.0, 54.5]


def _make_df(dates: list[date], closes: list[float]) -> pd.DataFrame:
    """시세 DataFrame 을 만든다. 시가 · 고가 · 저가는 종가에서 만든다."""
    return pd.DataFrame(
        {
            COL_DATE: dates,
            COL_OPEN: [c * 0.99 for c in closes],
            COL_HIGH: [c * 1.01 for c in closes],
            COL_LOW: [c * 0.98 for c in closes],
            COL_CLOSE: closes,
            COL_VOLUME: [1000] * len(dates),
        }
    )


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]


def _corr(a: list[float], b: list[float]) -> float:
    return float(np.corrcoef(a, b)[0, 1])


class TestAlignCloses:
    """두 시세를 실물 첫 거래일부터, 두 시세 모두 있는 날만 맞춘다."""

    def test_starts_at_actual_first_date(self) -> None:
        """
        목적: 실물 첫 거래일 앞의 대용 행은 비교에서 빠진다

        Given: 대용 DAYS[0] – DAYS[5], 실물 DAYS[2] – DAYS[5]
        When: align_closes
        Then: 날짜 = DAYS[2] – DAYS[5], 열 = 날짜 · 대용 · 실물, 값은 각 종가
        """
        # Given
        proxy = _make_df(DAYS[:6], [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:6], [60.0, 66.0, 61.0, 70.0])

        # When
        result = align_closes(proxy, actual)

        # Then
        assert list(result.columns) == [COL_DATE, COL_PROXY, COL_ACTUAL]
        assert result[COL_DATE].tolist() == DAYS[2:6]
        assert result[COL_PROXY].tolist() == [12.0, 13.0, 14.0, 15.0]
        assert result[COL_ACTUAL].tolist() == [60.0, 66.0, 61.0, 70.0]

    def test_keeps_only_dates_in_both(self) -> None:
        """
        목적: 한쪽에만 있는 날은 메우지 않고 뺀다 (시장 달력이 다른 선물 · 펀드)

        Given: 대용에 DAYS[3] 이 없음, 실물 DAYS[2] – DAYS[5]
        When: align_closes
        Then: 날짜 = DAYS[2] · DAYS[4] · DAYS[5]
        """
        # Given
        proxy = _make_df([DAYS[0], DAYS[1], DAYS[2], DAYS[4], DAYS[5]], [10.0, 11.0, 12.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:6], [60.0, 66.0, 61.0, 70.0])

        # When
        result = align_closes(proxy, actual)

        # Then
        assert result[COL_DATE].tolist() == [DAYS[2], DAYS[4], DAYS[5]]
        assert result[COL_PROXY].tolist() == [12.0, 14.0, 15.0]
        assert result[COL_ACTUAL].tolist() == [60.0, 61.0, 70.0]

    def test_ends_at_earlier_end(self) -> None:
        """
        목적: 끝은 두 시세의 끝 중 이른 날이다

        Given: 대용 DAYS[0] – DAYS[3], 실물 DAYS[1] – DAYS[5]
        When: align_closes
        Then: 날짜 = DAYS[1] – DAYS[3]
        """
        # Given
        proxy = _make_df(DAYS[:4], [10.0, 11.0, 12.0, 13.0])
        actual = _make_df(DAYS[1:6], [60.0, 66.0, 61.0, 70.0, 72.0])

        # When
        result = align_closes(proxy, actual)

        # Then
        assert result[COL_DATE].tolist() == DAYS[1:4]

    def test_fewer_than_two_common_dates_raises(self) -> None:
        """
        목적: 겹치는 날이 2개 미만이면 수익률을 하나도 못 만들므로 예외

        Given: 대용 DAYS[0] – DAYS[2], 실물 DAYS[2] – DAYS[5] (겹치는 날 하나)
        When: align_closes
        Then: ValueError
        """
        # Given
        proxy = _make_df(DAYS[:3], [10.0, 11.0, 12.0])
        actual = _make_df(DAYS[2:6], [60.0, 66.0, 61.0, 70.0])

        # When / Then
        with pytest.raises(ValueError, match="겹치는"):
            align_closes(proxy, actual)

    @pytest.mark.parametrize("bad_side", ["proxy", "actual"])
    def test_bad_date_order_raises(self, bad_side: str) -> None:
        """
        목적: 날짜가 중복 없는 오름차순이 아닌 시세는 거부한다

        Given: 대용 또는 실물의 날짜가 정렬되지 않음
        When: align_closes
        Then: ValueError
        """
        # Given
        good = _make_df(DAYS[:4], [10.0, 11.0, 12.0, 13.0])
        bad = _make_df([DAYS[0], DAYS[2], DAYS[1], DAYS[3]], [60.0, 62.0, 61.0, 63.0])
        proxy, actual = (bad, good) if bad_side == "proxy" else (good, bad)

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            align_closes(proxy, actual)

    def test_inputs_not_mutated(self) -> None:
        """
        목적: 입력 DataFrame 을 바꾸지 않는다

        Given: 대용 · 실물과 그 사본
        When: align_closes
        Then: 입력이 사본과 같다
        """
        # Given
        proxy = _make_df(DAYS[:6], [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:6], [60.0, 66.0, 61.0, 70.0])
        proxy_copy, actual_copy = proxy.copy(), actual.copy()

        # When
        align_closes(proxy, actual)

        # Then
        pd.testing.assert_frame_equal(proxy, proxy_copy)
        pd.testing.assert_frame_equal(actual, actual_copy)


class TestSummarizePair:
    """겹치는 기간 전체의 상관 · CAGR · MDD · 이동 상관 최저값."""

    def test_identical_series(self) -> None:
        """
        목적: 같은 시세끼리는 상관 1, CAGR · MDD 가 같다

        Given: 대용과 실물이 같은 종가
        When: summarize_pair
        Then: 일간 · 월간 상관 1.0, CAGR · MDD 같음
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_PROXY))

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.daily_corr == pytest.approx(1.0, rel=REL_TOL)
        assert result.monthly_corr == pytest.approx(1.0, rel=REL_TOL)
        assert result.proxy_cagr == pytest.approx(result.actual_cagr, rel=REL_TOL)
        assert result.proxy_mdd == pytest.approx(result.actual_mdd, rel=REL_TOL)

    def test_period_fields(self) -> None:
        """
        목적: 시작 · 끝 · 거래일 수는 맞춘 기간 그대로다

        Given: 8거래일
        When: summarize_pair
        Then: 시작 MONTH_DAYS[0], 끝 MONTH_DAYS[-1], 거래일 8
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.start == MONTH_DAYS[0]
        assert result.end == MONTH_DAYS[-1]
        assert result.trading_days == 8

    def test_daily_corr_is_close_return_correlation(self) -> None:
        """
        목적: 일간 상관 = 두 종가 수익률의 피어슨 상관

        Given: 8거래일 대용 · 실물
        When: summarize_pair
        Then: numpy 로 계산한 상관과 같다
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))

        # When
        result = summarize_pair(aligned)

        # Then
        expected = _corr(_returns(MONTH_PROXY), _returns(MONTH_ACTUAL))
        assert result.daily_corr == pytest.approx(expected, rel=REL_TOL)

    def test_monthly_corr_uses_last_trading_day_of_month(self) -> None:
        """
        목적: 월간 상관 = 월 마지막 거래일 종가 수익률의 상관. 첫 달 부분 수익은 빠진다

        Given: 월 마지막 거래일 1/29 · 2/26 · 3/31 · 4/30
        When: summarize_pair
        Then: 월간 수익률 3개(2 · 3 · 4월)의 상관, 개월 수 3
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))
        month_end_idx = [1, 3, 5, 7]

        # When
        result = summarize_pair(aligned)

        # Then
        proxy_month = _returns([MONTH_PROXY[i] for i in month_end_idx])
        actual_month = _returns([MONTH_ACTUAL[i] for i in month_end_idx])
        assert result.months == 3
        assert result.monthly_corr == pytest.approx(_corr(proxy_month, actual_month), rel=REL_TOL)

    def test_cagr_annualizes_with_annual_days(self) -> None:
        """
        목적: CAGR(%) = (끝 종가 ÷ 첫 종가)^(ANNUAL_DAYS ÷ 달력일수) − 1

        Given: 2020-01-01 → 2021-01-01 (366일), 대용 100 → 121, 실물 100 → 110
        When: summarize_pair
        Then: 각 CAGR 이 산식과 같다
        """
        # Given
        days = [date(2020, 1, 1), date(2021, 1, 1)]
        aligned = align_closes(_make_df(days, [100.0, 121.0]), _make_df(days, [100.0, 110.0]))

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.proxy_cagr == pytest.approx((1.21 ** (ANNUAL_DAYS / 366) - 1.0) * 100.0, rel=REL_TOL)
        assert result.actual_cagr == pytest.approx((1.10 ** (ANNUAL_DAYS / 366) - 1.0) * 100.0, rel=REL_TOL)

    def test_mdd_is_peak_to_trough_of_close(self) -> None:
        """
        목적: MDD(%) = 종가 ÷ 그때까지 최고 종가 − 1 의 최솟값

        Given: 실물 100 · 120 · 90 · 130, 대용 100 · 110 · 99 · 120
        When: summarize_pair
        Then: 실물 −25.0, 대용 −10.0
        """
        # Given
        aligned = align_closes(
            _make_df(DAYS[:4], [100.0, 110.0, 99.0, 120.0]), _make_df(DAYS[:4], [100.0, 120.0, 90.0, 130.0])
        )

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.actual_mdd == pytest.approx(-25.0, rel=REL_TOL)
        assert result.proxy_mdd == pytest.approx(-10.0, rel=REL_TOL)

    def test_rolling_corr_min_and_date(self) -> None:
        """
        목적: 이동 상관의 최저값과 그 날짜를 낸다

        Given: 8거래일, 창 3
        When: summarize_pair(rolling_window=3)
        Then: rolling_correlation 의 최솟값 · 그 날짜와 같다
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))
        rolling = rolling_correlation(aligned, 3).dropna()

        # When
        result = summarize_pair(aligned, rolling_window=3)

        # Then
        assert result.rolling_corr_min == pytest.approx(float(rolling.min()), rel=REL_TOL)
        assert result.rolling_corr_min_date == rolling.idxmin()

    def test_undefined_values_are_none(self) -> None:
        """
        목적: 계산할 수 없는 값은 None 이다 — 수익률 1개(상관 없음), 월말 1개(월간 없음), 창보다 짧은 기간

        Given: 같은 달 안의 2거래일, 창 252
        When: summarize_pair
        Then: 일간 · 월간 상관, 이동 상관 최저값 · 날짜가 None, 개월 수 0
        """
        # Given
        aligned = align_closes(_make_df(DAYS[:2], [100.0, 101.0]), _make_df(DAYS[:2], [50.0, 50.5]))

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.daily_corr is None
        assert result.monthly_corr is None
        assert result.months == 0
        assert result.rolling_corr_min is None
        assert result.rolling_corr_min_date is None

    def test_constant_series_corr_is_none(self) -> None:
        """
        목적: 한쪽이 움직이지 않으면(분산 0) 상관이 정의되지 않으므로 None

        Given: 실물 종가가 매일 같음
        When: summarize_pair
        Then: 일간 상관 None
        """
        # Given
        aligned = align_closes(_make_df(DAYS[:4], [10.0, 11.0, 12.0, 11.5]), _make_df(DAYS[:4], [50.0] * 4))

        # When
        result = summarize_pair(aligned)

        # Then
        assert result.daily_corr is None


class TestRollingCorrelation:
    """일간 수익률의 이동 상관."""

    def test_values_match_trailing_windows(self) -> None:
        """
        목적: 그날까지 창 길이만큼의 수익률로 잰 상관이고, 창이 차기 전은 NaN 이다

        Given: 8거래일, 창 3
        When: rolling_correlation
        Then: 인덱스 = 날짜, 앞 3개 NaN, 이후 값 = 직전 3개 수익률의 상관
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))
        proxy_ret, actual_ret = _returns(MONTH_PROXY), _returns(MONTH_ACTUAL)

        # When
        result = rolling_correlation(aligned, 3)

        # Then
        assert result.index.tolist() == MONTH_DAYS
        assert result.iloc[:3].isna().all()
        for i in range(3, len(MONTH_DAYS)):
            expected = _corr(proxy_ret[i - 3 : i], actual_ret[i - 3 : i])
            assert float(result.iloc[i]) == pytest.approx(expected, rel=REL_TOL)

    def test_window_below_two_raises(self) -> None:
        """
        목적: 창이 2 미만이면 상관을 잴 수 없으므로 예외

        Given: 창 1
        When: rolling_correlation
        Then: ValueError
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))

        # When / Then
        with pytest.raises(ValueError, match="창"):
            rolling_correlation(aligned, 1)


class TestSummarizePeriods:
    """기간별 상관 · 수익률. 기간은 겹치는 범위로 자른다."""

    PROXY = [10.0, 11.0, 12.0, 11.5, 13.0, 14.0]
    ACTUAL = [20.0, 21.0, 21.5, 21.0, 23.0, 24.5]

    def _aligned(self) -> pd.DataFrame:
        return align_closes(_make_df(DAYS[:6], self.PROXY), _make_df(DAYS[:6], self.ACTUAL))

    def test_return_uses_previous_day_close(self) -> None:
        """
        목적: 기간 수익률의 기준은 기간 첫날의 전날 종가다

        Given: 기간 DAYS[2] – DAYS[4]
        When: summarize_periods
        Then: 수익률 = DAYS[4] 종가 ÷ DAYS[1] 종가 − 1 (%), 거래일 3, 차이 = 대용 − 실물
        """
        # When
        result = summarize_periods(self._aligned(), [Period("p", DAYS[2], DAYS[4])])

        # Then
        assert len(result) == 1
        summary = result[0]
        assert summary.trading_days == 3
        assert summary.proxy_return == pytest.approx((13.0 / 11.0 - 1.0) * 100.0, rel=REL_TOL)
        assert summary.actual_return == pytest.approx((23.0 / 21.0 - 1.0) * 100.0, rel=REL_TOL)
        assert summary.return_diff == pytest.approx(summary.proxy_return - summary.actual_return, rel=REL_TOL)

    def test_daily_corr_within_period(self) -> None:
        """
        목적: 기간 상관은 기간 안 날짜의 수익률(첫날은 전날 대비)로 잰다

        Given: 기간 DAYS[2] – DAYS[5]
        When: summarize_periods
        Then: DAYS[2] – DAYS[5] 의 일간 수익률 4개로 잰 상관
        """
        # When
        result = summarize_periods(self._aligned(), [Period("p", DAYS[2], DAYS[5])])

        # Then
        expected = _corr(_returns(self.PROXY)[1:], _returns(self.ACTUAL)[1:])
        assert result[0].daily_corr == pytest.approx(expected, rel=REL_TOL)

    def test_period_clipped_to_overlap_and_first_close_base(self) -> None:
        """
        목적: 겹치는 범위 밖은 자르고, 전날이 없으면 첫날 종가를 기준으로 한다

        Given: 기간 2023-12-25 – DAYS[3] (겹치는 기간은 DAYS[0] 부터)
        When: summarize_periods
        Then: 실제 시작 DAYS[0], 끝 DAYS[3], 수익률 = DAYS[3] ÷ DAYS[0] − 1
        """
        # When
        result = summarize_periods(self._aligned(), [Period("p", date(2023, 12, 25), DAYS[3])])

        # Then
        summary = result[0]
        assert summary.start == DAYS[0]
        assert summary.end == DAYS[3]
        assert summary.name == "p"
        assert summary.proxy_return == pytest.approx((11.5 / 10.0 - 1.0) * 100.0, rel=REL_TOL)

    def test_periods_with_fewer_than_two_days_are_dropped(self) -> None:
        """
        목적: 자른 범위의 거래일이 2개 미만인 기간은 결과에서 뺀다

        Given: 거래일 하나(DAYS[5] – 2024-02-01)와 겹치지 않는 기간(2025년), 정상 기간 하나
        When: summarize_periods
        Then: 정상 기간만 남는다
        """
        # Given
        periods = [
            Period("하루", DAYS[5], date(2024, 2, 1)),
            Period("없음", date(2025, 1, 1), date(2025, 2, 1)),
            Period("정상", DAYS[0], DAYS[5]),
        ]

        # When
        result = summarize_periods(self._aligned(), periods)

        # Then
        assert [summary.name for summary in result] == ["정상"]

    def test_period_start_after_end_raises(self) -> None:
        """
        목적: 시작이 끝보다 늦은 기간은 잘못 만든 입력이므로 예외

        Given: 시작 DAYS[4], 끝 DAYS[2]
        When: summarize_periods
        Then: ValueError
        """
        # When / Then
        with pytest.raises(ValueError, match="시작"):
            summarize_periods(self._aligned(), [Period("p", DAYS[4], DAYS[2])])


class TestCalendarYearPeriods:
    """연도 기간 목록."""

    def test_years_with_partial_first_and_last(self) -> None:
        """
        목적: 첫 해 · 마지막 해는 주어진 시작 · 끝으로 자른 부분 연도다

        Given: 2019-06-15 – 2021-03-01
        When: calendar_year_periods
        Then: 2019(06-15 – 12-31) · 2020(전체) · 2021(01-01 – 03-01)
        """
        # When
        result = calendar_year_periods(date(2019, 6, 15), date(2021, 3, 1))

        # Then
        assert result == [
            Period("2019", date(2019, 6, 15), date(2019, 12, 31)),
            Period("2020", date(2020, 1, 1), date(2020, 12, 31)),
            Period("2021", date(2021, 1, 1), date(2021, 3, 1)),
        ]

    def test_start_after_end_raises(self) -> None:
        """
        목적: 시작이 끝보다 늦으면 예외

        Given: 2021-01-01 – 2020-01-01
        When: calendar_year_periods
        Then: ValueError
        """
        # When / Then
        with pytest.raises(ValueError, match="시작"):
            calendar_year_periods(date(2021, 1, 1), date(2020, 1, 1))


class TestSummaryRecords:
    """결과 표 한 행 — 표시용 열 이름과 반올림 전 값."""

    def test_pair_record_carries_summary_and_differences(self) -> None:
        """
        목적: 전체 비교 행은 요약 값을 그대로 담고, 차이는 대용 − 실물이다

        Given: 8거래일 대용 · 실물의 summarize_pair 결과
        When: pair_summary_record
        Then: 시작일 · 일간 상관 · 최저 날짜가 요약과 같고, CAGR · MDD 차이가 대용 − 실물
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))
        summary = summarize_pair(aligned, rolling_window=3)

        # When
        record = pair_summary_record(summary)

        # Then
        assert record[DISPLAY_START] == summary.start
        assert record[DISPLAY_DAILY_CORR] == summary.daily_corr
        assert record[DISPLAY_ROLLING_MIN_DATE] == summary.rolling_corr_min_date
        assert record[DISPLAY_CAGR_DIFF] == pytest.approx(summary.proxy_cagr - summary.actual_cagr, rel=REL_TOL)
        assert record[DISPLAY_MDD_DIFF] == pytest.approx(summary.proxy_mdd - summary.actual_mdd, rel=REL_TOL)

    def test_period_records_keep_order_and_differences(self) -> None:
        """
        목적: 기간별 행은 입력 순서대로이고 수익률 차이는 대용 − 실물이다

        Given: 기간 두 개의 summarize_periods 결과
        When: period_summary_records
        Then: 기간 이름 순서가 같고 수익률 차이가 대용 − 실물
        """
        # Given
        aligned = align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))
        summaries = summarize_periods(
            aligned, [Period("앞", MONTH_DAYS[0], MONTH_DAYS[3]), Period("뒤", MONTH_DAYS[4], MONTH_DAYS[7])]
        )

        # When
        records = period_summary_records(summaries)

        # Then
        assert [record[DISPLAY_PERIOD] for record in records] == ["앞", "뒤"]
        for record, summary in zip(records, summaries, strict=True):
            assert record[DISPLAY_RETURN_DIFF] == pytest.approx(
                summary.proxy_return - summary.actual_return, rel=REL_TOL
            )


class TestRoundForDisplay:
    """결과 표 반올림."""

    def test_ratio_and_percent_columns_use_their_digits(self) -> None:
        """
        목적: 비율 열은 ROUND_RATIO, % 열은 ROUND_PERCENT 자리로 반올림하고 다른 열은 그대로 둔다

        Given: 일간 상관(비율) · CAGR 차(%) · 글자 열이 있는 표
        When: round_for_display
        Then: 각 자릿수로 반올림되고 글자 열은 그대로
        """
        # Given
        df = pd.DataFrame({"대상": ["QQQ"], DISPLAY_DAILY_CORR: [0.987654321], DISPLAY_CAGR_DIFF: [1.23456]})

        # When
        result = round_for_display(df)

        # Then
        assert result[DISPLAY_DAILY_CORR].iloc[0] == pytest.approx(round(0.987654321, ROUND_RATIO), abs=1e-12)
        assert result[DISPLAY_CAGR_DIFF].iloc[0] == pytest.approx(round(1.23456, ROUND_PERCENT), abs=1e-12)
        assert result["대상"].iloc[0] == "QQQ"


class TestAlignedInputValidation:
    """비교 함수는 align_closes 가 만든 표만 받는다 — 날짜가 어긋나면 전날 종가 · 월 묶음이 조용히 틀린다."""

    @staticmethod
    def _aligned() -> pd.DataFrame:
        return align_closes(_make_df(MONTH_DAYS, MONTH_PROXY), _make_df(MONTH_DAYS, MONTH_ACTUAL))

    @staticmethod
    def _call(name: str, aligned: pd.DataFrame) -> None:
        if name == "summarize_pair":
            summarize_pair(aligned)
        elif name == "summarize_periods":
            summarize_periods(aligned, [Period("p", MONTH_DAYS[0], MONTH_DAYS[-1])])
        else:
            rolling_correlation(aligned, 2)

    @pytest.mark.parametrize("name", ["summarize_pair", "summarize_periods", "rolling_correlation"])
    def test_unsorted_dates_raise(self, name: str) -> None:
        """
        목적: 날짜가 오름차순이 아닌 표는 거부한다

        Given: 두 행을 맞바꾼 비교 표
        When: 비교 함수
        Then: ValueError
        """
        # Given
        aligned = self._aligned()
        swapped = aligned.iloc[[0, 2, 1, 3, 4, 5, 6, 7]].reset_index(drop=True)

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            self._call(name, swapped)

    @pytest.mark.parametrize("name", ["summarize_pair", "summarize_periods", "rolling_correlation"])
    def test_wrong_columns_raise(self, name: str) -> None:
        """
        목적: align_closes 의 열이 아닌 표는 거부한다

        Given: 실물 열 이름이 다른 표
        When: 비교 함수
        Then: ValueError
        """
        # Given
        renamed = self._aligned().rename(columns={COL_ACTUAL: "other"})

        # When / Then
        with pytest.raises(ValueError, match="align_closes"):
            self._call(name, renamed)


class TestCountUnmatchedDays:
    """비교에서 빠진 날 — align_closes 가 견주는 기간(실물 첫날 ~ 두 시세 끝 중 이른 날) 안에서 한쪽에만 있는 날"""

    def test_counts_days_on_one_side_within_window(self) -> None:
        """
        목적: 겹치는 기간 안에서 대용에만 · 실물에만 있는 날을 센다 — 실물 첫날 앞 · 이른 끝날 뒤의 날은 세지 않는다

        Given: 대용 DAYS[0] ~ DAYS[7] 에서 DAYS[2] 빠짐, 실물 DAYS[1] ~ DAYS[6] 에서 DAYS[4] 빠짐
        When: count_unmatched_days
        Then: 대용에만 1 (DAYS[4]), 실물에만 1 (DAYS[2]) — DAYS[0] (실물 첫날 앞) · DAYS[7] (실물 끝 뒤) 는 세지 않음
        """
        # Given
        proxy_days = [d for i, d in enumerate(DAYS) if i != 2]
        actual_days = [d for i, d in enumerate(DAYS[1:7], start=1) if i != 4]
        proxy = _make_df(proxy_days, [100.0 + i for i in range(len(proxy_days))])
        actual = _make_df(actual_days, [50.0 + i for i in range(len(actual_days))])

        # When
        unmatched = count_unmatched_days(proxy, actual)

        # Then
        assert (unmatched.proxy_only, unmatched.actual_only) == (1, 1)

    def test_same_calendar_counts_zero(self) -> None:
        """
        목적: 달력이 같으면 0 · 0 이다 (QQQ · SPY 대용의 경계 — 대용이 실물보다 먼저 시작해도 앞의 날은 세지 않는다)

        Given: 대용 DAYS 전부, 실물 DAYS[3:]
        When: count_unmatched_days
        Then: 0 · 0
        """
        # Given
        proxy = _make_df(DAYS, [100.0 + i for i in range(len(DAYS))])
        actual = _make_df(DAYS[3:], [50.0 + i for i in range(len(DAYS) - 3)])

        # When
        unmatched = count_unmatched_days(proxy, actual)

        # Then
        assert (unmatched.proxy_only, unmatched.actual_only) == (0, 0)

    def test_window_ends_at_earlier_end(self) -> None:
        """
        목적: 비교 기간의 끝은 두 시세의 끝 중 이른 날이다 — 대용이 먼저 끝나면 그 뒤 실물 날은 「실물에만」으로 세지 않는다
              (금 사슬의 Perth 달러 ↔ GC=F 처럼 대용이 2015 에 끝나고 실물은 그 뒤로 이어지는 경우)

        Given: 대용 DAYS[0] ~ DAYS[4], 실물 DAYS[1] ~ DAYS[7] 에서 DAYS[3] 빠짐
        When: count_unmatched_days
        Then: 대용에만 1 (DAYS[3]), 실물에만 0 — DAYS[5] ~ DAYS[7] 은 대용 끝 뒤라 세지 않음
        """
        # Given
        proxy = _make_df(DAYS[:5], [100.0 + i for i in range(5)])
        actual_days = [d for i, d in enumerate(DAYS[1:], start=1) if i != 3]
        actual = _make_df(actual_days, [50.0 + i for i in range(len(actual_days))])

        # When
        unmatched = count_unmatched_days(proxy, actual)

        # Then
        assert (unmatched.proxy_only, unmatched.actual_only) == (1, 0)

    def test_window_includes_first_and_last_day(self) -> None:
        """
        목적: 비교 기간의 첫날(실물 첫날) · 끝날(이른 끝날)도 센다 — 다시 받은 시세의 끝날이 한쪽에만 있으면 그날이 빠진 날이다

        Given: 대용 DAYS[1] ~ DAYS[5] (실물 첫날 DAYS[0] 없음), 실물 DAYS[0] ~ DAYS[7] 에서 DAYS[5] (대용 끝날) 빠짐
        When: count_unmatched_days
        Then: 대용에만 1 (끝날 DAYS[5]), 실물에만 1 (첫날 DAYS[0])
        """
        # Given
        proxy = _make_df(DAYS[1:6], [100.0 + i for i in range(5)])
        actual_days = [d for i, d in enumerate(DAYS) if i != 5]
        actual = _make_df(actual_days, [50.0 + i for i in range(len(actual_days))])

        # When
        unmatched = count_unmatched_days(proxy, actual)

        # Then
        assert (unmatched.proxy_only, unmatched.actual_only) == (1, 1)
