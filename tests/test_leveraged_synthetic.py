"""레버리지 합성 테스트

비용 입력(금리 · 운용비율 · 상한 건 가산금리)과 상품 하나의 합성(시뮬레이션 → 이어 붙이기 → 이음매 뒤 실물 검사),
상품 표 전체의 합성(상품마다 자기 기초 · 자기 저장 경로, 시뮬레이션은 상장일까지만)을 검증한다.

왜 중요한가요?
합성 TQQQ · QLD 는 전략이 매매 시세로 읽는다. 상한이 1999년 뒤 달에 걸리면 기존 합성의 1999년 이후 값이 바뀌고,
상품 표 → 저장 경로 연결이 어긋나면 2배 시세가 3배 파일을 에러 없이 덮는다. 기초가 섞이면 S&P 500 상품이
나스닥 100 으로 에러 없이 만들어진다. 시뮬레이션을 상장일에서 멈춰도 값이 같아야 상장 뒤 금리 · 운용비율 없이
만들 수 있다(결정 Q20).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_data.constants import (
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    TRADING_DAYS_PER_YEAR,
)
from quant_data.leveraged.constants import (
    COL_EXPENSE_DATE,
    COL_EXPENSE_VALUE,
    COL_FFR_DATE,
    COL_FFR_VALUE,
    DEFAULT_PRE_LISTING_EXPENSE_RATIO,
    DEFAULT_SOFTPLUS_A,
    DEFAULT_SOFTPLUS_B,
    SPREAD_CAP,
)
from quant_data.leveraged.simulation import build_monthly_spread_map
from quant_data.leveraged.synthetic import (
    build_cost_inputs,
    build_leveraged_synthetic,
    build_leveraged_synthetics,
    month_of,
    simulate_leveraged,
)
from quant_data.prices import load_prices
from quant_data.synthetic.proxy_series import splice_proxy

# 상한 마지막 달(1998-12)을 걸치는 거래일 — 이음매는 1999-01-05
DAYS = [
    date(1998, 12, 28),
    date(1998, 12, 29),
    date(1998, 12, 30),
    date(1998, 12, 31),
    date(1999, 1, 4),
    date(1999, 1, 5),
    date(1999, 1, 6),
    date(1999, 1, 7),
]
SEAM_INDEX = 5
HIGH_RATE = 0.08  # 비율 (0.08 = 8%) — softplus 가산금리가 상한을 넘는 금리

# 첫 달(1998-11)이 DAYS(1998-12)보다 이른 두 번째 기초 — 이음매는 같은 1999-01-05
EARLY_DAYS = [date(1998, 11, 27), date(1998, 11, 30), *DAYS]


def _price_df(dates: list[date], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            COL_DATE: dates,
            COL_OPEN: [c * 0.995 for c in closes],
            COL_HIGH: [c * 1.01 for c in closes],
            COL_LOW: [c * 0.98 for c in closes],
            COL_CLOSE: closes,
            COL_VOLUME: [1000] * len(closes),
        }
    )


def _underlying() -> pd.DataFrame:
    # 둘째 날 +20% — 3배 합성은 하루 +60% 가 된다
    return _price_df(DAYS, [100.0, 120.0, 118.0, 121.0, 123.0, 120.0, 124.0, 125.0])


def _actual(closes: list[float]) -> pd.DataFrame:
    return _price_df(DAYS[SEAM_INDEX:], closes)


def _ffr_df() -> pd.DataFrame:
    return pd.DataFrame({COL_FFR_DATE: ["1998-12", "1999-01"], COL_FFR_VALUE: [HIGH_RATE, HIGH_RATE]})


def _expense_df() -> pd.DataFrame:
    return pd.DataFrame({COL_EXPENSE_DATE: ["2010-02"], COL_EXPENSE_VALUE: [0.0095]})


def _returns(closes: pd.Series) -> pd.Series:
    return closes / closes.shift(1) - 1.0


class TestBuildCostInputs:
    """합성 비용 입력 — 금리 · 운용비율(시작 달부터) · 가산금리(1998-12 까지 상한)"""

    def test_spread_capped_only_through_1998(self):
        """
        목적: 가산금리 상한은 1998-12 까지의 달에만 걸린다 — 1999-01 부터는 모형 값 그대로 (결정 4)

        Given: 1998-12 · 1999-01 금리 8% (모형 가산금리가 상한을 넘는다)
        When: build_cost_inputs
        Then: 1998-12 = 상한, 1999-01 = 모형 값
        """
        # Given
        model = build_monthly_spread_map(_ffr_df(), DEFAULT_SOFTPLUS_A, DEFAULT_SOFTPLUS_B)
        assert model["1998-12"] > SPREAD_CAP

        # When
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12")

        # Then
        assert costs.spread["1998-12"] == SPREAD_CAP
        assert costs.spread["1999-01"] == model["1999-01"]

    def test_no_cap_option(self):
        """
        목적: 상한 없는 판(검증 ④)은 모든 달이 모형 값이다

        Given: 같은 금리
        When: build_cost_inputs(spread_cap=None)
        Then: 두 달 모두 모형 값
        """
        # Given
        model = build_monthly_spread_map(_ffr_df(), DEFAULT_SOFTPLUS_A, DEFAULT_SOFTPLUS_B)

        # When
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12", spread_cap=None)

        # Then
        assert costs.spread == model

    def test_expense_from_first_month(self):
        """
        목적: 운용비율은 기초 시세의 첫 달부터 상장 전 고정값으로 덮인다

        Given: 2010-02 부터인 운용비율, 첫 달 1998-12
        When: build_cost_inputs
        Then: 1998-12 고정값, 1998-11 없음, 금리는 파일 그대로
        """
        # When
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12")

        # Then
        assert costs.expense["1998-12"] == DEFAULT_PRE_LISTING_EXPENSE_RATIO
        assert "1998-11" not in costs.expense
        assert costs.ffr == {"1998-12": HIGH_RATE, "1999-01": HIGH_RATE}


class TestBuildLeveragedSynthetic:
    """상품 하나의 합성 — 이음매 앞 시뮬레이션, 이음매부터 실물, 이음매 뒤 검사"""

    def test_rows_from_seam_equal_actual(self):
        """
        목적: 이음매 날부터는 실물 행 그대로다

        Given: 기초 8일, 실물은 이음매(1999-01-05)부터 3일
        When: simulate_leveraged → build_leveraged_synthetic
        Then: 이음매 뒤 행 = 실물 행
        """
        # Given
        actual = _actual([50.0, 52.0, 51.0])
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12")

        # When
        result = build_leveraged_synthetic(simulate_leveraged(_underlying(), 3.0, costs), actual)

        # Then
        from_seam = result[result[COL_DATE] >= DAYS[SEAM_INDEX]].reset_index(drop=True)
        pd.testing.assert_frame_equal(from_seam, actual.reset_index(drop=True))

    def test_pre_seam_return_is_leverage_minus_cost(self):
        """
        목적: 이음매 앞 하루 수익률 = 배율 × 기초 수익률 − 그날 비용이고, 비용의 가산금리는 1998-12 에 상한, 1999-01 에 모형 값이다

        Given: 금리 8%, 운용비율 0.95%(상장 전 고정값), 배율 3
        When: simulate_leveraged → build_leveraged_synthetic
        Then: 이음매 앞 넷째 날까지 하루 수익률이 손계산과 같다
        """
        # Given
        leverage = 3.0
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12")
        underlying = _underlying()

        # When
        result = build_leveraged_synthetic(simulate_leveraged(underlying, leverage, costs), _actual([50.0, 52.0, 51.0]))

        # Then
        result_returns = _returns(result[COL_CLOSE])
        underlying_returns = _returns(underlying[COL_CLOSE])
        for i in range(1, SEAM_INDEX):
            month = f"{DAYS[i].year:04d}-{DAYS[i].month:02d}"
            daily_cost = (
                (HIGH_RATE + costs.spread[month]) * (leverage - 1) + DEFAULT_PRE_LISTING_EXPENSE_RATIO
            ) / TRADING_DAYS_PER_YEAR
            expected = underlying_returns.iloc[i] * leverage - daily_cost
            assert result_returns.iloc[i] == pytest.approx(expected, abs=1e-12)

    def test_stops_when_rows_from_seam_differ(self, monkeypatch: pytest.MonkeyPatch):
        """
        목적: 이어 붙인 결과의 이음매 뒤 행이 실물과 다르면 저장하기 전에 멈춘다 (불변 조건 ⑥)

        Given: 이음매 날 시가를 종가로 덮어쓴 결과를 돌려주는 splice_proxy
        When: build_leveraged_synthetic
        Then: RuntimeError (내부 불변조건 위반)
        """

        # Given
        def splice_overwriting_seam_open(proxy_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
            spliced = splice_proxy(proxy_df, actual_df)
            seam_mask = spliced[COL_DATE] == actual_df[COL_DATE].iloc[0]
            spliced.loc[seam_mask, COL_OPEN] = spliced.loc[seam_mask, COL_CLOSE]
            return spliced

        monkeypatch.setattr("quant_data.leveraged.synthetic.splice_proxy", splice_overwriting_seam_open)
        costs = build_cost_inputs(_ffr_df(), _expense_df(), "1998-12")
        simulated = simulate_leveraged(_underlying(), 2.0, costs)

        # When / Then
        with pytest.raises(RuntimeError, match="내부 불변조건 위반"):
            build_leveraged_synthetic(simulated, _actual([50.0, 52.0, 51.0]))


class TestBuildLeveragedSynthetics:
    """상품 표 전체의 합성 — 상품마다 자기 기초를 상장일까지 자기 배율로 굴려 자기 실물에 이어 자기 경로로 돌려준다.

    파일은 쓰지 않는다 — 쓰기는 모든 받기 · 판정 · 가공이 끝난 뒤 갱신이 한꺼번에 한다(결정 Q17).
    """

    @staticmethod
    def _ffr_df() -> pd.DataFrame:
        # 두 기초의 첫 달(1998-11 · 1998-12)부터 덮음
        return pd.DataFrame({COL_FFR_DATE: ["1998-11", "1998-12", "1999-01"], COL_FFR_VALUE: [HIGH_RATE] * 3})

    @staticmethod
    def _targets(tmp_path: Path) -> tuple[tuple[str, Path, Path, float, Path], ...]:
        # 기초 둘의 하루 수익률 · 첫 달이 다름 → 다른 줄의 기초를 쓰면 수익률 · 첫날이 어긋남
        base_a = tmp_path / "A_synthetic.csv"
        base_b = tmp_path / "B_synthetic.csv"
        _underlying().to_csv(base_a, index=False)
        _price_df(EARLY_DAYS, [80.0, 82.0, 79.0, 85.0, 84.0, 86.0, 87.0, 85.0, 88.0, 90.0]).to_csv(base_b, index=False)
        actual_a = tmp_path / "AAA_adjusted.csv"
        actual_b = tmp_path / "BBB_adjusted.csv"
        _actual([50.0, 52.0, 51.0]).to_csv(actual_a, index=False)
        _actual([20.0, 21.0, 20.5]).to_csv(actual_b, index=False)
        return (
            ("AAA", base_a, actual_a, 3.0, tmp_path / "out" / "AAA_synthetic.csv"),
            ("BBB", base_b, actual_b, 2.0, tmp_path / "out" / "BBB_synthetic.csv"),
        )

    def test_each_product_built_from_own_underlying_with_own_leverage(self, tmp_path: Path):
        """
        목적: 상품 표 → 기초 · 저장 경로 연결을 고정한다 — 다른 줄의 기초를 쓰거나 저장 대상 · 배율 · 실물을 섞으면 실패한다

        Given: 상품 둘 (3배 · 2배, 기초와 실물이 다름), 금리 8% · 운용비율은 상장 전 고정값
        When: build_leveraged_synthetics
        Then: 상품마다 저장 경로가 그 줄의 합성 파일이고, 이음매 앞 하루 수익률 = 자기 배율 × 자기 기초 수익률 − 그날 비용,
              이음매 뒤 종가 = 자기 실물 종가
        """
        # Given
        targets = self._targets(tmp_path)
        model_spread = build_monthly_spread_map(self._ffr_df(), DEFAULT_SOFTPLUS_A, DEFAULT_SOFTPLUS_B)

        # When
        runs = build_leveraged_synthetics(self._ffr_df(), _expense_df(), load_prices, targets)

        # Then
        assert [run.output_path for run in runs] == [targets[0][4], targets[1][4]]
        for run, (_, underlying_path, actual_path, leverage, _) in zip(runs, targets, strict=True):
            underlying = load_prices(underlying_path)
            built = run.synthetic
            underlying_returns = _returns(underlying[COL_CLOSE])
            built_returns = _returns(built[COL_CLOSE])
            seam = underlying[COL_DATE].tolist().index(DAYS[SEAM_INDEX])
            for i in range(1, seam):
                month = month_of(underlying[COL_DATE].iloc[i])
                # 상한은 1998-12 까지의 달에만
                spread = SPREAD_CAP if month <= "1998-12" else model_spread[month]
                daily_cost = (
                    (HIGH_RATE + spread) * (leverage - 1) + DEFAULT_PRE_LISTING_EXPENSE_RATIO
                ) / TRADING_DAYS_PER_YEAR
                assert built_returns.iloc[i] == pytest.approx(
                    leverage * underlying_returns.iloc[i] - daily_cost, abs=1e-12
                )
            from_seam = built[built[COL_DATE] >= DAYS[SEAM_INDEX]][COL_CLOSE].tolist()
            assert from_seam == load_prices(actual_path)[COL_CLOSE].tolist()

    def test_does_not_write_files(self, tmp_path: Path):
        """
        목적: 합성은 파일을 쓰지 않는다 — 쓰면 뒤에 받기 · 판정이 멈춰도 합성 파일만 바뀐 판이 남는다(결정 Q17)

        Given: 상품 둘의 합성 파일 경로(없는 폴더 out/)
        When: build_leveraged_synthetics
        Then: out/ 폴더가 생기지 않는다
        """
        # Given
        targets = self._targets(tmp_path)

        # When
        build_leveraged_synthetics(self._ffr_df(), _expense_df(), load_prices, targets)

        # Then
        assert not (tmp_path / "out").exists()

    def test_costs_cover_each_underlying_from_its_first_month(self, tmp_path: Path):
        """
        목적: 비용 입력은 기초마다 그 기초의 첫 달부터 덮는다 (경계) — 한 기초의 첫 달(1998-12)로만 만들면
              더 이른 기초(1998-11)가 운용비율이 없어 첫날에서 멈춘다

        Given: 첫 달이 다르고 둘 다 운용비율 파일(2010-02 부터)보다 앞인 기초 둘
        When: build_leveraged_synthetics
        Then: 두 합성 모두 만들어지고, 각 합성의 첫날이 자기 기초의 첫날이다
        """
        # Given
        targets = self._targets(tmp_path)

        # When
        runs = build_leveraged_synthetics(self._ffr_df(), _expense_df(), load_prices, targets)

        # Then
        assert [run.synthetic[COL_DATE].iloc[0] for run in runs] == [DAYS[0], EARLY_DAYS[0]]

    def test_returns_runs_in_target_order(self, tmp_path: Path):
        """
        목적: 검증 ④ 에 넘길 상품별 기초 · 시뮬레이션 · 실물을 표 순서대로 돌려준다 — 검증은 상품을 이 기초로
              묶으므로 다른 줄의 기초가 실리면 다른 기초로 잰 판이 에러 없이 나간다

        Given: 상품 둘
        When: build_leveraged_synthetics
        Then: 이름 · 배율이 표 순서, 기초는 그 줄의 경로와 그 파일의 시세, 시뮬레이션은 자기 기초의 첫날 ~ 이음매(실물 첫날),
              실물은 그 상품의 실물
        """
        # Given
        targets = self._targets(tmp_path)

        # When
        runs = build_leveraged_synthetics(self._ffr_df(), _expense_df(), load_prices, targets)

        # Then
        assert [(run.name, run.leverage) for run in runs] == [("AAA", 3.0), ("BBB", 2.0)]
        assert [run.underlying_path for run in runs] == [targets[0][1], targets[1][1]]
        assert runs[1].underlying[COL_DATE].tolist() == EARLY_DAYS
        assert runs[0].simulated[COL_DATE].tolist() == DAYS[: SEAM_INDEX + 1]
        assert runs[1].simulated[COL_DATE].tolist() == EARLY_DAYS[: EARLY_DAYS.index(DAYS[SEAM_INDEX]) + 1]
        assert runs[1].actual[COL_CLOSE].tolist() == [20.0, 21.0, 20.5]


class TestSimulationStopsAtListing:
    """시뮬레이션은 상장일(이음매)까지만 — 상장 뒤 구간은 실물 행이라 시뮬레이션이 합성 값에 들어가지 않는다(결정 Q20)"""

    # 이음매(1999-01-05) 뒤로 넉 달 더 이어지는 기초 — 상장 뒤 달(1999-02 ~ 1999-05)의 금리는 주지 않는다
    LONG_DAYS = [*DAYS, date(1999, 2, 1), date(1999, 3, 1), date(1999, 4, 1), date(1999, 5, 3)]
    LONG_CLOSES = [100.0, 120.0, 118.0, 121.0, 123.0, 120.0, 124.0, 125.0, 127.0, 126.0, 129.0, 131.0]

    def _targets(self, tmp_path: Path) -> tuple[tuple[str, Path, Path, float, Path], ...]:
        base = tmp_path / "A_synthetic.csv"
        _price_df(self.LONG_DAYS, self.LONG_CLOSES).to_csv(base, index=False)
        actual = tmp_path / "AAA_adjusted.csv"
        _price_df(self.LONG_DAYS[SEAM_INDEX:], [50.0, 52.0, 51.0, 53.0, 54.0, 52.0, 55.0]).to_csv(actual, index=False)
        return (("AAA", base, actual, 3.0, tmp_path / "AAA_synthetic.csv"),)

    def test_builds_without_rates_after_listing(self, tmp_path: Path):
        """
        목적: 상장 뒤 달의 금리가 없어도 합성을 만든다 — 기초 전 기간을 굴리면 1999-04 부터 금리 조회가
              「이전 달 허용 개월 수(2) 초과」로 멈춘다. 상장일에서 멈추므로 금리 · 운용비율이 상장 뒤까지 있을 필요가 없다

        Given: 이음매 뒤 넉 달 더 이어지는 기초, 금리는 1998-12 · 1999-01 만
        When: build_leveraged_synthetics
        Then: 멈추지 않고, 시뮬레이션의 마지막 날이 이음매(실물 첫날)다
        """
        # Given
        targets = self._targets(tmp_path)

        # When
        runs = build_leveraged_synthetics(_ffr_df(), _expense_df(), load_prices, targets)

        # Then
        assert runs[0].simulated[COL_DATE].iloc[-1] == DAYS[SEAM_INDEX]

    def test_values_equal_full_period_simulation(self, tmp_path: Path):
        """
        목적: 상장일까지만 굴린 합성이 전 기간을 굴린 합성과 값이 정확히 같다 — 시뮬레이션은 그날까지의 기초만 보고,
              이음매 비율은 이음매 날 값으로 정해진다. 다르면 옮긴 합성이 quant 의 합성과 어긋난다(시세_받기_판정.md 6.8)

        Given: 위 기초 · 실물, 상장 뒤 달까지 덮는 금리(전 기간 시뮬레이션이 돌 수 있게)
        When: build_leveraged_synthetics 의 합성 ↔ 전 기간 simulate_leveraged → build_leveraged_synthetic
        Then: 두 표가 같다 (허용오차 없이)
        """
        # Given
        targets = self._targets(tmp_path)
        months = ["1998-12", "1999-01", "1999-02", "1999-03", "1999-04", "1999-05"]
        ffr_df = pd.DataFrame({COL_FFR_DATE: months, COL_FFR_VALUE: [HIGH_RATE] * len(months)})
        _, base, actual, leverage, _ = targets[0]
        costs = build_cost_inputs(ffr_df, _expense_df(), "1998-12")
        full = build_leveraged_synthetic(simulate_leveraged(load_prices(base), leverage, costs), load_prices(actual))

        # When
        runs = build_leveraged_synthetics(ffr_df, _expense_df(), load_prices, targets)

        # Then
        pd.testing.assert_frame_equal(runs[0].synthetic, full)
