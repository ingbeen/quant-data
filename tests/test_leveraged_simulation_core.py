"""TQQQ 시뮬레이션 코어 테스트

simulate() 함수의 핵심 계약, 입력 검증, 오버나이트 오픈 동작을 검증한다.
"""

from datetime import date

import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN
from quant_data.leveraged.simulation import (
    simulate,
)


def _with_high_low(df: pd.DataFrame) -> pd.DataFrame:
    """고가 · 저가를 보지 않는 테스트의 기초 자산 — 고가 · 저가를 시가 · 종가 안에 둔다."""
    body = df[[COL_OPEN, COL_CLOSE]]
    return df.assign(**{COL_HIGH: body.max(axis=1), COL_LOW: body.min(axis=1)})


class TestSimulate:
    """TQQQ 시뮬레이션 테스트"""

    def test_normal_simulation(self):
        """
        정상적인 시뮬레이션 테스트

        데이터 신뢰성: 시뮬레이션 결과가 NaN 없이 생성되어야 합니다.

        Given:
          - QQQ 일일 수익률 데이터
          - FFR 데이터
          - leverage=3, expense_ratio=0.0095, funding_spread=0.006
        When: simulate 호출
        Then:
          - 모든 날짜에 Simulated_Close 생성
          - NaN 없음
          - initial_price 반영
          - 날짜 오름차순 정렬
        """
        # Given: 간단한 QQQ 데이터
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, i + 2) for i in range(5)],
                COL_OPEN: [100.0, 100.5, 99.5, 101.5, 102.5],
                COL_CLOSE: [100.0, 101.0, 99.0, 102.0, 103.0],
            }  # 1/2 ~ 1/6
        )

        ffr_dict = {"2023-01": 0.045}
        expense_dict = {"2023-01": 0.0095}  # 0.95%

        leverage = 3.0
        initial_price = 30.0  # TQQQ 초기 가격
        funding_spread = {"2023-01": 0.006}  # 0.6%

        # When
        simulated_df = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=leverage,
            initial_price=initial_price,
            ffr_dict=ffr_dict,
            expense_dict=expense_dict,
            funding_spread=funding_spread,
        )

        # Then: 기본 검증
        assert len(simulated_df) == 5, "입력과 같은 행 수"
        assert COL_CLOSE in simulated_df.columns, "Close 컬럼 존재"

        # NaN 없음
        assert not simulated_df[COL_CLOSE].isna().any(), "시뮬레이션 결과에 NaN이 있으면 안 됩니다"

        # 첫 가격이 initial_price 근처인지 확인 (첫날은 initial_price 유지)
        first_price = simulated_df.iloc[0][COL_CLOSE]
        assert first_price == pytest.approx(initial_price, abs=1.0), f"첫 가격은 initial_price({initial_price}) 근처여야 합니다"

        # 날짜 정렬 확인
        dates = simulated_df[COL_DATE].tolist()
        assert dates == sorted(dates), "날짜가 정렬되어야 합니다"

        # 가격은 양수
        assert (simulated_df[COL_CLOSE] > 0).all(), "모든 가격은 양수여야 합니다"

    def test_leverage_effect(self):
        """
        레버리지 효과 테스트

        데이터 신뢰성: 레버리지 배수만큼 수익률이 확대되는지 확인

        Given: QQQ가 1% 상승
        When: leverage=3으로 시뮬레이션
        Then: TQQQ는 약 3% 상승 (비용 최소화, spread > 0 제약으로 1e-9 사용)
        """
        # Given: QQQ 1% 상승
        underlying_df = pd.DataFrame(
            {COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)], COL_OPEN: [100.0, 100.5], COL_CLOSE: [100.0, 101.0]}
        )  # +1%

        # When: leverage=3, FFR · expense 0, 최소 spread (1e-9, spread > 0 제약 충족)
        # 비용 영향 최소화: 1e-9 * 2 / 252 ≈ 7.9e-12 (무시 가능)
        simulated_df = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.0},
            expense_dict={"2023-01": 0.0},
            funding_spread={"2023-01": 1e-9},  # 최소 양수 (spread > 0 제약)
        )

        # Then: QQQ +1% -> TQQQ +3% (비용 영향 무시 가능)
        # 30.0 * 1.03 = 30.9
        final_price = simulated_df.iloc[1][COL_CLOSE]
        expected_price = 30.0 * 1.03

        assert final_price == pytest.approx(
            expected_price, abs=0.01
        ), f"레버리지 3배: 30.0 * 1.03 = {expected_price:.2f}, 실제: {final_price:.2f}"

    def test_high_low_relationship(self):
        """
        목적: 고가는 시가 · 종가 이상, 저가는 시가 · 종가 이하라는 시세 불변조건을 검증한다

        Given: 비용이 있는 QQQ 데이터
        When: simulate 호출
        Then: 모든 행에서 High >= max(Open, Close), Low <= min(Open, Close)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)],
                COL_OPEN: [100.0, 100.5, 99.5, 101.5],
                COL_CLOSE: [100.0, 101.0, 99.0, 102.0],
            }
        )

        # When
        result = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        body = result[[COL_OPEN, COL_CLOSE]]
        assert (result[COL_HIGH] >= body.max(axis=1)).all()
        assert (result[COL_LOW] <= body.min(axis=1)).all()

    def test_start_on_month_end_day(self):
        """
        목적: 시작일이 그 달의 29 – 31일이어도 시뮬레이션이 돈다 — 기간의 달을 날짜 하나씩 늘려 세면
              다음 달에 그 날짜가 없어 멈춘다(2020-01-31 → 2월 31일)

        Given: 2020-01-31 에 시작하는 기초 자산과 그 기간의 월별 값
        When: simulate 호출
        Then: 입력과 같은 행 수가 나온다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2020, 1, 31), date(2020, 2, 3), date(2020, 3, 2)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_CLOSE: [100.0, 101.0, 102.0],
            }
        )
        months = ["2020-01", "2020-02", "2020-03"]

        # When
        result = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={month: 0.0155 for month in months},
            expense_dict={month: 0.0095 for month in months},
            funding_spread={month: 0.006 for month in months},
        )

        # Then
        assert len(result) == 3


class TestSimulateValidation:
    """simulate 함수 파라미터 검증 테스트"""

    @pytest.mark.parametrize(
        "param_name,invalid_value,error_pattern",
        [
            ("leverage", 0.0, "leverage는 양수여야 합니다"),
            ("leverage", -3.0, "leverage는 양수여야 합니다"),
            ("initial_price", 0.0, "initial_price는 양수여야 합니다"),
            ("initial_price", -100.0, "initial_price는 양수여야 합니다"),
        ],
        ids=["leverage_zero", "leverage_negative", "initial_price_zero", "initial_price_negative"],
    )
    def test_invalid_numeric_params_raise(self, param_name, invalid_value, error_pattern):
        """
        숫자 파라미터가 유효하지 않을 때 예외 발생 테스트

        Given: leverage <= 0 또는 initial_price <= 0 (parametrize로 여러 케이스 테스트)
        When: simulate 호출
        Then: ValueError 발생

        Args:
            param_name: 테스트할 파라미터 이름 ("leverage" 또는 "initial_price")
            invalid_value: 잘못된 값
            error_pattern: 예상 에러 메시지 패턴
        """
        # Given
        underlying_df = pd.DataFrame(
            {COL_DATE: [date(2023, 1, 1), date(2023, 1, 2)], COL_OPEN: [100.0, 104.0], COL_CLOSE: [100.0, 105.0]}
        )

        # 파라미터 구성 (param_name에 따라 다른 값 사용)
        if param_name == "leverage":
            leverage = invalid_value
            initial_price = 100.0
        else:  # initial_price
            leverage = 3.0
            initial_price = invalid_value

        # When & Then
        with pytest.raises(ValueError, match=error_pattern):
            simulate(
                underlying_df=_with_high_low(underlying_df),
                leverage=leverage,
                initial_price=initial_price,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.005},
            )

    def test_missing_required_columns_raises(self):
        """
        필수 컬럼 누락 시 예외 발생 테스트

        Given: Date 또는 Close 컬럼이 없는 DataFrame
        When: simulate 호출
        Then: ValueError 발생
        """
        # Given: Close 컬럼 누락
        underlying_df_no_close = pd.DataFrame({COL_DATE: [date(2023, 1, 1), date(2023, 1, 2)]})

        # When & Then
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다"):
            simulate(
                underlying_df=underlying_df_no_close,
                leverage=3.0,
                initial_price=100.0,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.005},
            )

    def test_empty_dataframe_raises(self):
        """
        빈 DataFrame일 때 예외 발생 테스트

        Given: 빈 underlying_df
        When: simulate 호출
        Then: ValueError 발생
        """
        # Given: 빈 DataFrame
        underlying_df = pd.DataFrame(columns=[COL_DATE, COL_OPEN, COL_CLOSE])

        # When & Then
        with pytest.raises(ValueError, match="underlying_df가 비어있습니다"):
            simulate(
                underlying_df=_with_high_low(underlying_df),
                leverage=3.0,
                initial_price=100.0,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.005},
            )

    def test_nan_underlying_return_raises(self):
        """
        목적: 기초 자산 수익률이 NaN 이면 첫 가격으로 되돌리지 않고 멈춤을 검증 — 시세 로더가 결측 가격을 막으므로
              닿으면 내부 불변조건 위반이다

        Given: 첫날 종가가 결측인 underlying_df (둘째 날 수익률이 NaN)
        When: simulate 호출
        Then: RuntimeError (「내부 불변조건 위반」)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_CLOSE: [float("nan"), 101.0, 102.0],
            }
        )

        # When & Then
        with pytest.raises(RuntimeError, match="내부 불변조건 위반"):
            simulate(
                underlying_df=_with_high_low(underlying_df),
                leverage=3.0,
                initial_price=100.0,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.005},
            )

    def test_ffr_gap_beyond_limit_raises(self):
        """
        목적: 시뮬레이션 기간에 금리가 허용 개월 수(MAX_FFR_MONTHS_DIFF)를 넘게 비면 멈춤을 검증 —
              날마다 비용을 계산할 때 그 달 금리를 조회하므로, 미리 기간 전체를 검사하지 않아도 빈 달에서 멈춘다

        Given: 2023-01 · 2023-02 금리만 있고 2023-05 거래일이 있는 기초 자산 (2023-02 와 3개월 차이)
        When: simulate 호출
        Then: ValueError (「FFR 데이터 부족」, 빈 달 2023-05)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 3), date(2023, 2, 1), date(2023, 5, 1)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_CLOSE: [100.0, 101.0, 102.0],
            }
        )
        months = ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"]

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터 부족.*2023-05"):
            simulate(
                underlying_df=_with_high_low(underlying_df),
                leverage=3.0,
                initial_price=100.0,
                ffr_dict={"2023-01": 0.045, "2023-02": 0.046},
                expense_dict={month: 0.0095 for month in months},
                funding_spread={month: 0.005 for month in months},
            )


class TestSimulateHighLow:
    """simulate() 의 고가 · 저가 계산 테스트

    펀드의 장중 노출은 전날 종가에 고정되므로 장중 가치는 기초 자산에 선형이다.

    수식: X(t) = 레버리지_Close(t-1) × (1 + (기초_X(t)/기초_Close(t-1) - 1) × leverage), X 는 High · Low
    """

    def test_high_low_scale_underlying_intraday_range(self):
        """
        목적: 고가 · 저가가 기초 자산의 장중 고가 · 저가를 배율로 키운 값임을 손계산으로 고정한다 —
              시가 · 종가에서 만든 근사값이면 장중 꼬리가 사라진다

        Given: 시가 · 종가 밖으로 장중 범위가 나간 기초 자산, 배율 2, 비용 거의 0
        When: simulate 호출
        Then: 둘째 · 셋째 날 고가 · 저가가 전날 시뮬 종가 기준 식과 일치한다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_HIGH: [100.0, 103.0, 104.0],
                COL_LOW: [100.0, 99.0, 100.0],
                COL_CLOSE: [100.0, 102.0, 101.0],
            }
        )

        # When
        result = simulate(
            underlying_df=underlying_df,
            leverage=2.0,
            initial_price=50.0,
            ffr_dict={"2023-01": 0.0},
            expense_dict={"2023-01": 0.0},
            funding_spread={"2023-01": 1e-9},
        )

        # Then: 둘째 날 — 50 × (1 + 3% × 2), 50 × (1 - 1% × 2)
        assert result.iloc[1][COL_HIGH] == pytest.approx(53.0, abs=1e-6)
        assert result.iloc[1][COL_LOW] == pytest.approx(49.0, abs=1e-6)
        # 셋째 날 — 전날 시뮬 종가 52 × (1 ± 2/102 × 2)
        assert result.iloc[2][COL_HIGH] == pytest.approx(54.039216, abs=1e-6)
        assert result.iloc[2][COL_LOW] == pytest.approx(49.960784, abs=1e-6)

    def test_low_moved_to_close_when_underlying_closes_at_its_low(self):
        """
        목적: 일일 비용은 종가에서만 빠지므로 기초 자산이 저가에 마감한 날 식의 저가가 종가보다 높다 —
              저가를 종가로 맞춰 시세 불변조건을 지킴을 검증한다

        Given: 둘째 날 저가 = 종가인 기초 자산, 비용 있음
        When: simulate 호출
        Then: 둘째 날 저가는 식의 값(29.1)이 아니라 그보다 낮은 종가다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_OPEN: [100.0, 101.0],
                COL_HIGH: [100.0, 103.0],
                COL_LOW: [100.0, 99.0],
                COL_CLOSE: [100.0, 99.0],
            }
        )

        # When
        result = simulate(
            underlying_df=underlying_df,
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        assert result.iloc[1][COL_CLOSE] < 29.1
        assert result.iloc[1][COL_LOW] == result.iloc[1][COL_CLOSE]

    def test_formula_inside_body_is_moved_to_open_close(self):
        """
        목적: 식의 고가 · 저가가 시가 · 종가 안쪽이어도 시세 불변조건을 지킴을 검증 — 비용이 음수인 달
              (음수 금리를 그대로 쓴다)이나 기초 자산의 고가 · 저가 오입력에서 생긴다

        Given: 기초 고가가 시가 · 종가보다 낮고 저가가 시가 · 종가보다 높은 날 두 개 (종가가 위인 날과 시가가 위인 날)
        When: simulate 호출
        Then: 고가는 시가 · 종가 중 큰 값, 저가는 작은 값이다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, 104.0],
                COL_HIGH: [100.0, 100.5, 102.0],
                COL_LOW: [100.0, 102.0, 103.0],
                COL_CLOSE: [100.0, 103.0, 100.0],
            }
        )

        # When
        result = simulate(
            underlying_df=underlying_df,
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.0},
            expense_dict={"2023-01": 0.0},
            funding_spread={"2023-01": 1e-9},
        )

        # Then: 둘째 날은 종가가 위, 셋째 날은 시가가 위
        day2, day3 = result.iloc[1], result.iloc[2]
        assert day2[COL_CLOSE] > day2[COL_OPEN]
        assert day2[COL_HIGH] == pytest.approx(day2[COL_CLOSE], abs=1e-9)
        assert day2[COL_LOW] == pytest.approx(day2[COL_OPEN], abs=1e-9)
        assert day3[COL_OPEN] > day3[COL_CLOSE]
        assert day3[COL_HIGH] == pytest.approx(day3[COL_OPEN], abs=1e-9)
        assert day3[COL_LOW] == pytest.approx(day3[COL_CLOSE], abs=1e-9)

    @pytest.mark.parametrize(
        "underlying_low,leverage",
        [(1.0, 3.0), (50.0, 2.0)],
        ids=["negative", "exactly_zero"],
    )
    def test_non_positive_low_raises(self, underlying_low, leverage):
        """
        목적: 시뮬 저가가 0 이하이면 멈춤을 검증 — 기초 자산 저가의 오입력은 양수라 시세 검사를 지나고,
              일별 비교 CSV 는 저장 전 검사가 없어 음수 가격이 에러 없이 나간다

        Given: 둘째 날 저가가 크게 낮은 기초 자산 (식의 저가가 음수인 경우, 정확히 0 인 경우)
        When: simulate 호출
        Then: ValueError (「시뮬레이션 가격이 0 이하」)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_OPEN: [100.0, 100.0],
                COL_HIGH: [100.0, 101.0],
                COL_LOW: [100.0, underlying_low],
                COL_CLOSE: [100.0, 100.0],
            }
        )

        # When & Then
        with pytest.raises(ValueError, match="시뮬레이션 가격이 0 이하"):
            simulate(
                underlying_df=underlying_df,
                leverage=leverage,
                initial_price=30.0,
                ffr_dict={"2023-01": 0.0},
                expense_dict={"2023-01": 0.0},
                funding_spread={"2023-01": 1e-9},
            )

    def test_first_day_high_low_equal_initial_price(self):
        """
        목적: 첫날은 전날 종가가 없어 고가 · 저가가 시작 가격임을 검증한다 (시가 · 종가와 같은 규칙)

        Given: 첫날 장중 범위가 넓은 기초 자산, initial_price=30.0
        When: simulate 호출
        Then: 첫날 시가 · 고가 · 저가 · 종가가 모두 30.0 이다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_OPEN: [100.0, 101.0],
                COL_HIGH: [110.0, 103.0],
                COL_LOW: [90.0, 99.0],
                COL_CLOSE: [100.0, 102.0],
            }
        )

        # When
        result = simulate(
            underlying_df=underlying_df,
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        first = result.iloc[0]
        assert [first[COL_OPEN], first[COL_HIGH], first[COL_LOW], first[COL_CLOSE]] == [30.0, 30.0, 30.0, 30.0]

    @pytest.mark.parametrize("col", [COL_HIGH, COL_LOW])
    def test_missing_high_low_after_first_day_is_not_filled(self, col):
        """
        목적: 첫날이 아닌 날의 고가 · 저가 결측을 시가 · 종가로 메우지 않음을 검증 — 메우면 에러 없이
              가짜 값이 저장된다. 결측은 저장 전 시세 검사가 멈춘다

        Given: 셋째 날 기초 자산의 고가 또는 저가가 결측
        When: simulate 호출
        Then: 셋째 날 그 열이 결측으로 남는다
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_HIGH: [100.0, 103.0, 104.0],
                COL_LOW: [100.0, 99.0, 100.0],
                COL_CLOSE: [100.0, 102.0, 101.0],
            }
        )
        underlying_df.loc[2, col] = float("nan")

        # When
        result = simulate(
            underlying_df=underlying_df,
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        assert pd.isna(result.iloc[2][col])

    @pytest.mark.parametrize("col", [COL_HIGH, COL_LOW])
    def test_high_low_required_columns(self, col):
        """
        목적: 고가 · 저가 열이 없으면 시가 · 종가로 대신하지 않고 멈춤을 검증한다

        Given: 고가 또는 저가 열이 없는 기초 자산
        When: simulate 호출
        Then: ValueError (필수 컬럼 누락)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_OPEN: [100.0, 101.0],
                COL_HIGH: [100.0, 103.0],
                COL_LOW: [100.0, 99.0],
                COL_CLOSE: [100.0, 102.0],
            }
        ).drop(columns=[col])

        # When & Then
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다"):
            simulate(
                underlying_df=underlying_df,
                leverage=3.0,
                initial_price=30.0,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.006},
            )

    def test_high_low_do_not_change_open_close(self):
        """
        목적: 기초 자산의 고가 · 저가는 시가 · 종가 계산에 쓰이지 않음을 고정한다 — 매매 계산은 시가 · 종가만
              읽으므로, 이 계약이 깨지면 백테스트 성과까지 바뀐다

        Given: 시가 · 종가는 같고 장중 범위만 다른 두 기초 자산
        When: 각각 simulate 호출
        Then: 시뮬 시가 · 종가가 값까지 같다
        """
        # Given
        narrow = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, 102.0],
                COL_HIGH: [100.0, 102.0, 102.0],
                COL_LOW: [100.0, 101.0, 101.0],
                COL_CLOSE: [100.0, 102.0, 101.0],
            }
        )
        wide = narrow.assign(**{COL_HIGH: [110.0, 120.0, 130.0], COL_LOW: [90.0, 80.0, 70.0]})
        monthly = {
            "ffr_dict": {"2023-01": 0.045},
            "expense_dict": {"2023-01": 0.0095},
            "funding_spread": {"2023-01": 0.006},
        }

        # When
        narrow_result = simulate(underlying_df=narrow, leverage=3.0, initial_price=30.0, **monthly)
        wide_result = simulate(underlying_df=wide, leverage=3.0, initial_price=30.0, **monthly)

        # Then
        pd.testing.assert_frame_equal(
            narrow_result[[COL_OPEN, COL_CLOSE]], wide_result[[COL_OPEN, COL_CLOSE]], check_exact=True
        )


class TestSimulateOvernightOpen:
    """simulate() 함수의 오버나이트 갭 기반 Open 가격 계산 테스트

    레버리지 ETF의 시가(Open)는 기초 자산의 오버나이트 갭(전일 종가 → 당일 시가)을
    레버리지 배율로 확대하여 계산해야 한다.

    수식: TQQQ_Open(t) = TQQQ_Close(t-1) × (1 + (QQQ_Open(t)/QQQ_Close(t-1) - 1) × leverage)
    """

    def test_open_reflects_overnight_gap(self):
        """
        오버나이트 갭이 레버리지 배율로 Open에 반영되는지 확인한다.

        Given:
          - QQQ 3일 데이터, day2의 Open(102.0)이 day1의 Close(100.0)와 다름 (+2%)
          - leverage=3.0, 비용 최소화 (FFR=0, expense=0, spread=1e-9)
        When: simulate() 호출
        Then:
          - TQQQ_Open(day2) ≈ TQQQ_Close(day1) × (1 + 0.02 × 3.0) = TQQQ_Close(day1) × 1.06
          - TQQQ_Open(day3)도 동일 수식으로 계산됨
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 102.0, 104.0],  # day2: +2% gap, day3: 갭 있음
                COL_CLOSE: [100.0, 105.0, 103.0],
            }
        )

        # When
        result = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.0},
            expense_dict={"2023-01": 0.0},
            funding_spread={"2023-01": 1e-9},
        )

        # Then: day2 Open 검증
        # QQQ 오버나이트 수익률 = 102.0 / 100.0 - 1 = 0.02
        # TQQQ_Open(day2) = TQQQ_Close(day1) × (1 + 0.02 × 3.0) = 30.0 × 1.06 = 31.8
        tqqq_close_day1 = result.iloc[0][COL_CLOSE]
        expected_open_day2 = tqqq_close_day1 * (1 + (102.0 / 100.0 - 1) * 3.0)
        actual_open_day2 = result.iloc[1][COL_OPEN]

        assert actual_open_day2 == pytest.approx(
            expected_open_day2, abs=0.01
        ), f"day2 Open: expected={expected_open_day2:.4f}, actual={actual_open_day2:.4f}"

        # Then: day3 Open 검증
        # QQQ 오버나이트 수익률 = 104.0 / 105.0 - 1 ≈ -0.00952
        # TQQQ_Open(day3) = TQQQ_Close(day2) × (1 + (-0.00952) × 3.0)
        tqqq_close_day2 = result.iloc[1][COL_CLOSE]
        overnight_return_day3 = 104.0 / 105.0 - 1
        expected_open_day3 = tqqq_close_day2 * (1 + overnight_return_day3 * 3.0)
        actual_open_day3 = result.iloc[2][COL_OPEN]

        assert actual_open_day3 == pytest.approx(
            expected_open_day3, abs=0.01
        ), f"day3 Open: expected={expected_open_day3:.4f}, actual={actual_open_day3:.4f}"

    def test_first_day_open_equals_initial_price(self):
        """
        첫날 Open은 initial_price여야 한다.

        Given: Open 컬럼 포함된 underlying 데이터, initial_price=30.0
        When: simulate() 호출
        Then: 첫날 Open = 30.0 (initial_price)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_OPEN: [100.0, 101.5],
                COL_CLOSE: [100.0, 101.0],
            }
        )

        # When
        result = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        assert result.iloc[0][COL_OPEN] == pytest.approx(30.0, abs=0.01), "첫날 Open은 initial_price여야 합니다"

    def test_missing_open_after_first_day_is_not_filled(self):
        """
        목적: 첫날이 아닌 날의 시가 결측을 시작 가격으로 메우지 않음을 검증 — 메우면 그날 시가가
              에러 없이 첫 가격으로 바뀐다. 결측은 저장 전 시세 검사가 멈춘다

        Given: 셋째 날 기초 자산 시가가 결측인 데이터
        When: simulate() 호출
        Then: 셋째 날 Open 이 결측으로 남는다 (첫날 Open 은 initial_price)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
                COL_OPEN: [100.0, 101.0, float("nan")],
                COL_CLOSE: [100.0, 101.0, 102.0],
            }
        )

        # When
        result = simulate(
            underlying_df=_with_high_low(underlying_df),
            leverage=3.0,
            initial_price=30.0,
            ffr_dict={"2023-01": 0.045},
            expense_dict={"2023-01": 0.0095},
            funding_spread={"2023-01": 0.006},
        )

        # Then
        assert result.iloc[0][COL_OPEN] == 30.0
        assert pd.isna(result.iloc[2][COL_OPEN])

    def test_open_required_column(self):
        """
        Open 컬럼이 누락되면 ValueError가 발생해야 한다.

        Given: Date + Close만 있는 underlying_df (Open 없음)
        When: simulate() 호출
        Then: ValueError (필수 컬럼 누락)
        """
        # Given
        underlying_df = pd.DataFrame(
            {
                COL_DATE: [date(2023, 1, 2), date(2023, 1, 3)],
                COL_CLOSE: [100.0, 101.0],
            }
        )

        # When & Then
        with pytest.raises(ValueError, match="필수 컬럼이 누락되었습니다"):
            simulate(
                underlying_df=underlying_df,
                leverage=3.0,
                initial_price=30.0,
                ffr_dict={"2023-01": 0.045},
                expense_dict={"2023-01": 0.0095},
                funding_spread={"2023-01": 0.006},
            )
