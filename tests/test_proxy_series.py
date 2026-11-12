"""대용 시계열 테스트

실물 ETF 상장 전 구간을 대용 시세로 채우는 함수의 계약을 검증한다.
이음매(실물 첫 거래일)에서의 비율 접합과 입력 검증을 다룬다.

왜 중요한가요?
합성 TQQQ · QLD 시세는 상장 전 시뮬레이션을 이 접합으로 실물에 잇는다. 이음매 뒤 구간이 실물과 한 행이라도 다르거나,
이음매 앞 구간의 수익률이 대용과 어긋나면 그 시세로 도는 백테스트의 성과가 조용히 틀린다.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from quant_data.constants import (
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    REQUIRED_COLUMNS,
)
from quant_data.synthetic.proxy_series import (
    build_proxy_synthetic,
    compute_seam_scale,
    deduct_annual_fee,
    rescale_to_actual,
    splice_proxy,
)

DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(6)]
REL_TOL = 1e-12


def _make_df(
    dates: list[date],
    closes: list[float],
    *,
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[int] | None = None,
) -> pd.DataFrame:
    """시세 DataFrame 을 만든다. 시가 · 고가 · 저가를 생략하면 종가에서 만든다."""
    opens = opens if opens is not None else [c * 0.99 for c in closes]
    highs = highs if highs is not None else [max(o, c) * 1.01 for o, c in zip(opens, closes, strict=True)]
    lows = lows if lows is not None else [min(o, c) * 0.98 for o, c in zip(opens, closes, strict=True)]
    volumes = volumes if volumes is not None else [1000 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            COL_DATE: dates,
            COL_OPEN: opens,
            COL_HIGH: highs,
            COL_LOW: lows,
            COL_CLOSE: closes,
            COL_VOLUME: volumes,
        }
    )


def _close_returns(df: pd.DataFrame) -> dict[date, float]:
    """날짜별 종가 수익률 (첫 행 제외)."""
    closes = df[COL_CLOSE].tolist()
    dates = df[COL_DATE].tolist()
    return {dates[i]: closes[i] / closes[i - 1] - 1.0 for i in range(1, len(dates))}


class TestComputeSeamScale:
    """이음매 스케일 = 실물 첫 거래일 종가 ÷ 그날 대용 종가."""

    def test_scale_is_ratio_of_seam_closes(self) -> None:
        """
        목적: 스케일은 이음매 날의 두 종가 비율이다

        Given: 이음매 DAYS[2] 의 대용 종가 12, 실물 종가 60
        When: compute_seam_scale
        Then: 5.0
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        scale = compute_seam_scale(proxy, actual)

        # Then
        assert scale == pytest.approx(5.0, rel=REL_TOL)


class TestRescaleToActual:
    """대용 전 구간을 실물 첫 거래일 종가에 맞춰 스케일한다."""

    def test_seam_close_matches_actual(self) -> None:
        """
        목적: 이음매(실물 첫 거래일)의 대용 종가가 실물 종가와 같아진다

        Given: 대용 종가 10 – 15, 실물은 DAYS[2] 에 종가 60 으로 시작
        When: rescale_to_actual
        Then: DAYS[2] 종가 = 60
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = rescale_to_actual(proxy, actual)

        # Then
        seam_close = float(result.loc[result[COL_DATE] == DAYS[2], COL_CLOSE].iloc[0])
        assert seam_close == pytest.approx(60.0, rel=REL_TOL)

    def test_all_price_columns_scaled_by_same_factor(self) -> None:
        """
        목적: 가격 4열이 모두 같은 배수로 바뀌어 수익률 · 봉 모양이 그대로다

        Given: 이음매 종가 비율 60 / 12 = 5
        When: rescale_to_actual
        Then: 시가 · 고가 · 저가 · 종가가 전 구간에서 원래 값 × 5
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = rescale_to_actual(proxy, actual)

        # Then
        for col in (COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE):
            assert result[col].tolist() == pytest.approx((proxy[col] * 5.0).tolist(), rel=REL_TOL)

    def test_volume_and_dates_unchanged(self) -> None:
        """
        목적: 거래량과 날짜는 스케일하지 않는다

        Given: 대용과 실물
        When: rescale_to_actual
        Then: 날짜 · 거래량이 대용 그대로
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = rescale_to_actual(proxy, actual)

        # Then
        assert result[COL_DATE].tolist() == proxy[COL_DATE].tolist()
        assert result[COL_VOLUME].tolist() == proxy[COL_VOLUME].tolist()

    def test_seam_missing_in_proxy_raises(self) -> None:
        """
        목적: 이음매 날짜가 대용에 없으면 스케일 기준이 없으므로 예외

        Given: 실물 첫 거래일이 대용 날짜에 없음
        When: rescale_to_actual
        Then: ValueError
        """
        # Given
        proxy = _make_df([DAYS[0], DAYS[1], DAYS[3]], [10.0, 11.0, 13.0])
        actual = _make_df(DAYS[2:4], [60.0, 66.0])

        # When / Then
        with pytest.raises(ValueError, match="이음매"):
            rescale_to_actual(proxy, actual)

    def test_inputs_not_mutated(self) -> None:
        """
        목적: 입력 DataFrame 을 바꾸지 않는다

        Given: 대용과 실물의 사본
        When: rescale_to_actual
        Then: 입력이 사본과 같다
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])
        proxy_copy, actual_copy = proxy.copy(), actual.copy()

        # When
        rescale_to_actual(proxy, actual)

        # Then
        pd.testing.assert_frame_equal(proxy, proxy_copy)
        pd.testing.assert_frame_equal(actual, actual_copy)


class TestSpliceProxy:
    """이음매 앞은 스케일한 대용, 이음매부터는 실물인 시계열을 만든다."""

    def test_rows_from_seam_equal_actual(self) -> None:
        """
        목적: 이음매부터는 실물 파일 행이 그대로 들어간다

        Given: 대용 6일, 실물은 DAYS[2] 부터
        When: splice_proxy
        Then: DAYS[2] 이후 행이 실물 행과 같다
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0], volumes=[7, 8, 9, 10])

        # When
        result = splice_proxy(proxy, actual)

        # Then
        from_seam = result[result[COL_DATE] >= DAYS[2]].reset_index(drop=True)
        pd.testing.assert_frame_equal(from_seam, actual.reset_index(drop=True))

    def test_returns_up_to_seam_equal_proxy(self) -> None:
        """
        목적: 이음매 앞 구간과 이음매 날의 종가 수익률은 대용의 수익률이다

        Given: 대용 종가 10, 11, 12.5, … 실물 이음매 종가 60
        When: splice_proxy
        Then: DAYS[1] · DAYS[2](이음매) 수익률 = 대용 수익률, DAYS[3] 부터는 실물 수익률
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.5, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = splice_proxy(proxy, actual)

        # Then
        result_returns = _close_returns(result)
        proxy_returns = _close_returns(proxy)
        actual_returns = _close_returns(actual)
        assert result_returns[DAYS[1]] == pytest.approx(proxy_returns[DAYS[1]], rel=REL_TOL)
        assert result_returns[DAYS[2]] == pytest.approx(proxy_returns[DAYS[2]], rel=REL_TOL)
        assert result_returns[DAYS[3]] == pytest.approx(actual_returns[DAYS[3]], rel=REL_TOL)

    def test_pre_seam_volume_is_zero(self) -> None:
        """
        목적: 이음매 앞 행의 거래량은 0 이다 (대용의 거래량은 실물 거래량이 아니다)

        Given: 대용 거래량이 0 이 아님
        When: splice_proxy
        Then: 이음매 앞 행 거래량 전부 0
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = splice_proxy(proxy, actual)

        # Then
        pre_seam = result[result[COL_DATE] < DAYS[2]]
        assert len(pre_seam) == 2
        assert pre_seam[COL_VOLUME].tolist() == [0, 0]

    def test_no_proxy_rows_before_seam_raises(self) -> None:
        """
        목적: 대용이 실물보다 먼저 시작하지 않으면 채울 구간이 없으므로 예외

        Given: 대용과 실물이 같은 날 시작
        When: splice_proxy
        Then: ValueError
        """
        # Given
        proxy = _make_df(DAYS[2:], [12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When / Then
        with pytest.raises(ValueError, match="이음매"):
            splice_proxy(proxy, actual)

    def test_columns_and_strictly_increasing_dates(self) -> None:
        """
        목적: 결과 열은 저장 형식(REQUIRED_COLUMNS)이고 날짜가 중복 없이 오름차순이다

        Given: 대용과 실물
        When: splice_proxy
        Then: 열 순서 = REQUIRED_COLUMNS, 날짜 = DAYS 전체(이음매 행 한 번)
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        result = splice_proxy(proxy, actual)

        # Then
        assert list(result.columns) == REQUIRED_COLUMNS
        assert result[COL_DATE].tolist() == DAYS

    def test_inputs_not_mutated(self) -> None:
        """
        목적: 입력 DataFrame 을 바꾸지 않는다

        Given: 대용과 실물의 사본
        When: splice_proxy
        Then: 입력이 사본과 같다
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])
        proxy_copy, actual_copy = proxy.copy(), actual.copy()

        # When
        splice_proxy(proxy, actual)

        # Then
        pd.testing.assert_frame_equal(proxy, proxy_copy)
        pd.testing.assert_frame_equal(actual, actual_copy)

    def test_pure_rescaled_pre_seam_equals_spliced_pre_seam(self) -> None:
        """
        목적: 전 구간 스케일 시계열의 이음매 앞 가격이 이어 붙인 시계열의 이음매 앞 가격과 같다

        Given: 같은 대용 · 실물
        When: rescale_to_actual 과 splice_proxy
        Then: 이음매 앞 가격 4열이 같다
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = _make_df(DAYS[2:], [60.0, 66.0, 61.0, 70.0])

        # When
        pure = rescale_to_actual(proxy, actual)
        spliced = splice_proxy(proxy, actual)

        # Then
        price_cols = [COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE]
        pure_pre = pure[pure[COL_DATE] < DAYS[2]][price_cols].reset_index(drop=True)
        spliced_pre = spliced[spliced[COL_DATE] < DAYS[2]][price_cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(pure_pre, spliced_pre)


class TestBuildProxySynthetic:
    """1배 대용 합성 — 이음매 앞은 시가를 그날 종가로 바꾼 대용, 이음매부터는 실물 행 그대로."""

    PROXY_CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    # 대용 시가 ≠ 종가 — 받은 시가가 남으면 잡힘
    PROXY_OPENS = [9.5, 10.4, 11.6, 12.9, 13.3, 14.8]
    ACTUAL_CLOSES = [60.0, 66.0, 61.0, 70.0]
    # 실물 시가 ≠ 종가 — 이음매 날까지 바꾸면 잡힘
    ACTUAL_OPENS = [59.0, 64.0, 63.0, 68.0]

    def _inputs(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        proxy = _make_df(DAYS, self.PROXY_CLOSES, opens=self.PROXY_OPENS)
        actual = _make_df(DAYS[2:], self.ACTUAL_CLOSES, opens=self.ACTUAL_OPENS, volumes=[7, 8, 9, 10])
        return proxy, actual

    def test_pre_seam_open_is_close(self) -> None:
        """
        목적: 이음매 앞 시가는 그날 종가다 — 진짜 시가가 없는 지수 · 펀드의 시가 칸을 쓰지 않는다

        Given: 대용 시가가 종가와 다름, 이음매 DAYS[2]
        When: build_proxy_synthetic
        Then: DAYS[0] · DAYS[1] 의 시가 = 그날 종가
        """
        # Given
        proxy, actual = self._inputs()

        # When
        result = build_proxy_synthetic(proxy, actual)

        # Then
        pre_seam = result[result[COL_DATE] < DAYS[2]]
        assert len(pre_seam) == 2
        assert pre_seam[COL_OPEN].tolist() == pre_seam[COL_CLOSE].tolist()

    def test_pre_seam_only_open_differs_from_splice(self) -> None:
        """
        목적: 이음매 앞은 시가만 바뀌고 날짜 · 고가 · 저가 · 종가 · 거래량은 이어 붙인 대용 그대로다

        Given: 같은 대용 · 실물
        When: build_proxy_synthetic 과 splice_proxy
        Then: 이음매 앞 행의 시가 밖 열이 같다
        """
        # Given
        proxy, actual = self._inputs()

        # When
        result = build_proxy_synthetic(proxy, actual)
        spliced = splice_proxy(proxy, actual)

        # Then
        other_cols = [COL_DATE, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOLUME]
        result_pre = result[result[COL_DATE] < DAYS[2]][other_cols].reset_index(drop=True)
        spliced_pre = spliced[spliced[COL_DATE] < DAYS[2]][other_cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(result_pre, spliced_pre)

    def test_rows_from_seam_equal_actual(self) -> None:
        """
        목적: 이음매 날부터는 실물 행 그대로다 — 이음매 날의 진짜 시가도 바꾸지 않는다

        Given: 실물 시가가 종가와 다름
        When: build_proxy_synthetic
        Then: DAYS[2] 이후 행 = 실물 행
        """
        # Given
        proxy, actual = self._inputs()

        # When
        result = build_proxy_synthetic(proxy, actual)

        # Then
        from_seam = result[result[COL_DATE] >= DAYS[2]].reset_index(drop=True)
        pd.testing.assert_frame_equal(from_seam, actual.reset_index(drop=True))

    def test_inputs_not_mutated(self) -> None:
        """
        목적: 입력 DataFrame 을 바꾸지 않는다

        Given: 대용과 실물의 사본
        When: build_proxy_synthetic
        Then: 입력이 사본과 같다
        """
        # Given
        proxy, actual = self._inputs()
        proxy_copy, actual_copy = proxy.copy(), actual.copy()

        # When
        build_proxy_synthetic(proxy, actual)

        # Then
        pd.testing.assert_frame_equal(proxy, proxy_copy)
        pd.testing.assert_frame_equal(actual, actual_copy)

    def test_stops_when_rows_from_seam_differ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 이어 붙인 결과의 이음매 뒤 행이 실물과 다르면 저장하기 전에 멈춘다 (불변 조건 ⑥)

        Given: 이음매 날 시가를 종가로 덮어쓴 결과를 돌려주는 splice_proxy
        When: build_proxy_synthetic
        Then: RuntimeError (내부 불변조건 위반)
        """

        # Given
        def splice_overwriting_seam_open(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
            spliced = splice_proxy(proxy_df, actual_df)
            seam_mask = spliced[COL_DATE] == actual_df[COL_DATE].iloc[0]
            spliced.loc[seam_mask, COL_OPEN] = spliced.loc[seam_mask, COL_CLOSE]
            return spliced

        monkeypatch.setattr("quant_data.synthetic.proxy_series.splice_proxy", splice_overwriting_seam_open)
        proxy, actual = self._inputs()

        # When / Then
        with pytest.raises(RuntimeError, match="내부 불변조건 위반"):
            build_proxy_synthetic(proxy, actual)


class TestDeductAnnualFee:
    """대용에서 상품의 연 보수를 뺀다 — 첫 행부터 달력일로 잰 경과 연수 t 마다 가격 × (1 − 보수)^t."""

    FEE = 0.004
    # 1,461일 = 4 × 365.25 — 경과 연수가 정확히 4. 사이 행은 달력일과 행 수가 어긋나게 둔다
    FEE_DAYS = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 1) + timedelta(days=1461)]

    def _proxy(self) -> pd.DataFrame:
        return _make_df(self.FEE_DAYS, [10.0, 11.0, 12.0], volumes=[5, 6, 7])

    def test_first_row_unchanged(self) -> None:
        """
        목적: 첫 행은 경과 연수 0 이라 그대로다

        Given: 보수 0.4%
        When: deduct_annual_fee
        Then: 첫 행 가격 넷이 원래 값
        """
        # Given
        proxy = self._proxy()

        # When
        result = deduct_annual_fee(proxy, self.FEE)

        # Then
        for col in (COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE):
            assert float(result[col].iloc[0]) == pytest.approx(float(proxy[col].iloc[0]), rel=REL_TOL)

    def test_prices_scaled_by_calendar_years(self) -> None:
        """
        목적: 경과 연수는 달력일 ÷ 365.25 다 — 4년 뒤 행의 가격 넷이 (1 − 보수)^4 배

        Given: 첫날과 1,461일 뒤 행 (사이에 하루 뒤 행 — 행 수로 세면 연수가 달라진다)
        When: deduct_annual_fee
        Then: 마지막 행 가격 넷 = 원래 × 0.996^4, 하루 뒤 행 = 원래 × 0.996^(1 ÷ 365.25)
        """
        # Given
        proxy = self._proxy()

        # When
        result = deduct_annual_fee(proxy, self.FEE)

        # Then
        for col in (COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE):
            assert float(result[col].iloc[2]) == pytest.approx(float(proxy[col].iloc[2]) * 0.996**4, rel=REL_TOL)
            assert float(result[col].iloc[1]) == pytest.approx(
                float(proxy[col].iloc[1]) * 0.996 ** (1 / 365.25), rel=REL_TOL
            )

    def test_zero_fee_keeps_prices(self) -> None:
        """
        목적: 보수 0 이면 가격이 그대로다 (경계)

        Given: 보수 0
        When: deduct_annual_fee
        Then: 결과 = 입력
        """
        # Given
        proxy = self._proxy()

        # When
        result = deduct_annual_fee(proxy, 0.0)

        # Then
        pd.testing.assert_frame_equal(result, proxy)

    def test_volume_and_dates_unchanged(self) -> None:
        """
        목적: 보수는 가격에만 걸린다

        Given: 거래량이 0 이 아닌 대용
        When: deduct_annual_fee
        Then: 날짜 · 거래량 그대로
        """
        # Given
        proxy = self._proxy()

        # When
        result = deduct_annual_fee(proxy, self.FEE)

        # Then
        assert result[COL_DATE].tolist() == proxy[COL_DATE].tolist()
        assert result[COL_VOLUME].tolist() == proxy[COL_VOLUME].tolist()

    def test_input_not_mutated(self) -> None:
        """
        목적: 입력 DataFrame 을 바꾸지 않는다

        Given: 대용의 사본
        When: deduct_annual_fee
        Then: 입력이 사본과 같다
        """
        # Given
        proxy = self._proxy()
        proxy_copy = proxy.copy()

        # When
        deduct_annual_fee(proxy, self.FEE)

        # Then
        pd.testing.assert_frame_equal(proxy, proxy_copy)

    @pytest.mark.parametrize("bad_fee", [-0.001, 1.0, 1.5])
    def test_fee_out_of_range_raises(self, bad_fee: float) -> None:
        """
        목적: 보수는 0 이상 1 미만의 비율이다 — % 그대로(0.4)나 음수는 거부한다

        Given: 범위 밖 보수
        When: deduct_annual_fee
        Then: ValueError
        """
        # Given
        proxy = self._proxy()

        # When / Then
        with pytest.raises(ValueError, match="보수"):
            deduct_annual_fee(proxy, bad_fee)

    @pytest.mark.parametrize("bad_kind", ["unsorted", "duplicated"])
    def test_rejects_bad_order(self, bad_kind: str) -> None:
        """
        목적: 날짜가 중복 없는 오름차순이어야 경과 연수가 뜻을 가진다

        Given: 정렬되지 않았거나 중복 날짜가 있는 대용
        When: deduct_annual_fee
        Then: ValueError
        """
        # Given
        dates = [DAYS[0], DAYS[2], DAYS[1]] if bad_kind == "unsorted" else [DAYS[0], DAYS[1], DAYS[1]]
        proxy = _make_df(dates, [10.0, 12.0, 11.0])

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            deduct_annual_fee(proxy, self.FEE)


class TestInputDateOrder:
    """두 함수 모두 날짜가 중복 없이 오름차순인 입력만 받는다."""

    @staticmethod
    def _unsorted() -> pd.DataFrame:
        return _make_df([DAYS[0], DAYS[2], DAYS[1], DAYS[3]], [10.0, 12.0, 11.0, 13.0])

    @staticmethod
    def _duplicated() -> pd.DataFrame:
        return _make_df([DAYS[0], DAYS[1], DAYS[1], DAYS[2]], [10.0, 11.0, 11.0, 12.0])

    @pytest.mark.parametrize("bad_kind", ["unsorted", "duplicated"])
    def test_rescale_rejects_bad_order(self, bad_kind: str) -> None:
        """
        목적: rescale_to_actual 은 날짜 순서가 틀린 대용을 거부한다

        Given: 정렬되지 않았거나 중복 날짜가 있는 대용
        When: rescale_to_actual
        Then: ValueError
        """
        # Given
        proxy = self._unsorted() if bad_kind == "unsorted" else self._duplicated()
        actual = _make_df(DAYS[2:4], [60.0, 66.0])

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            rescale_to_actual(proxy, actual)

    @pytest.mark.parametrize("bad_kind", ["unsorted", "duplicated"])
    def test_splice_rejects_bad_order_in_actual(self, bad_kind: str) -> None:
        """
        목적: splice_proxy 는 날짜 순서가 틀린 실물을 거부한다

        Given: 정렬되지 않았거나 중복 날짜가 있는 실물
        When: splice_proxy
        Then: ValueError
        """
        # Given
        proxy = _make_df(DAYS, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        actual = self._unsorted() if bad_kind == "unsorted" else self._duplicated()

        # When / Then
        with pytest.raises(ValueError, match="오름차순"):
            splice_proxy(proxy, actual)
