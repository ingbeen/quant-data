"""
products 모듈 테스트 — 가공(합성 · 검증 표) 대상 표의 연결

이 파일은 무엇을 검증하나요?
1. 1배 대용 합성 대상 표가 상품마다 정해진 대용 · 실물 · 저장 경로를 잇는가?
2. 검증 ④ 대상 표가 레버리지 상품 표의 기초를 모두 덮는가?
3. 국내 수정주가가 표의 국내 ETF 마다 원본가 · 분배 기록을 읽어 `_adjusted` 로 나오고, 야후 분배 대조가 그 파일에 붙는가?

왜 중요한가요?
대용 · 실물 · 저장 경로가 어긋나면 다른 상품의 시세로 이은 합성이 에러 없이 저장된다. 계산 자체는 옮긴 함수들의
테스트와, 첫 판에서 quant 합성과 값이 같은지의 대조가 지킨다.
"""

from datetime import date
from pathlib import Path

import pandas as pd

from quant_data.catalog import Dataset, Kind, Method, kr_adjusted_path
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
    SERIES_DIR,
)
from quant_data.leveraged.constants import LEVERAGED_SYNTHETIC_TARGETS
from quant_data.prices import PriceBasis, price_path, save_prices
from quant_data.products import ASSUMPTION_TARGETS, PROXY_TARGETS, build_kr_products
from quant_data.series import save_series


class TestProxyTargets:
    """1배 대용 합성 대상 표"""

    def test_proxy_actual_output_by_name(self) -> None:
        """
        목적: QQQ ← 나스닥100 지수(원본가 — 배당이 빠진 가격지수), SPY ← VFINX, TLT ← VUSTX 이고, 실물은 수정주가,
              저장은 그 상품의 합성 파일이다 (C-3)

        Given: 1배 대용 합성 대상 표
        When: 이름별 (대용, 실물, 저장) 파일 이름을 모은다
        Then: 정해진 이름
        """
        # When
        files = {name: (proxy.name, actual.name, output.name) for name, proxy, actual, output in PROXY_TARGETS}

        # Then
        assert files == {
            "QQQ": ("^NDX_raw.csv", "QQQ_adjusted.csv", "QQQ_synthetic.csv"),
            "SPY": ("VFINX_adjusted.csv", "SPY_adjusted.csv", "SPY_synthetic.csv"),
            "TLT": ("VUSTX_adjusted.csv", "TLT_adjusted.csv", "TLT_synthetic.csv"),
        }


class TestAssumptionTargets:
    """검증 ④ 대상 표"""

    def test_covers_every_leveraged_underlying(self) -> None:
        """
        목적: 레버리지 상품 표의 기초가 모두 검증 ④ 대상 표에 있다 — 빠지면 가공이 멈춘다(빠진 채 만들지 않는다)

        Given: 두 표
        When: 기초 경로를 모은다
        Then: 상품 표의 기초 ⊆ ④ 대상 표의 기초
        """
        # When
        leveraged_bases = {underlying for _, underlying, _, _, _ in LEVERAGED_SYNTHETIC_TARGETS}
        assumption_bases = {underlying for underlying, _, _ in ASSUMPTION_TARGETS}

        # Then
        assert leveraged_bases <= assumption_bases


class TestKrProducts:
    """국내 수정주가 가공 — 표의 국내 ETF 마다"""

    def test_reads_raw_and_dividends_and_returns_adjusted_with_notes(self, tmp_path: Path) -> None:
        """
        목적: 국내 ETF 마다 원본가 · 야후 분배 기록을 (이번 표 → 없으면 파일 순서로) 읽어 `_adjusted` 를 만들고,
              야후 분배 대조의 어긋남을 그 파일에 붙인다 — 이번 갱신이 받지 않은 고정 자료도 파일로 다시 만든다

        Given: 파일에만 있는 069500 원본가(둘째 날 기준가 9,900 — 100원, 야후 기록 없음)와 빈 분배 기록
        When: build_kr_products(이번 표 없음)
        Then: 069500_adjusted 첫 종가 = 10,000 × 9,900 ÷ 10,000, 마지막 종가 = 원본가, 어긋남 한 줄
        """
        # Given
        days = [date(2024, 7, 22), date(2024, 7, 23), date(2024, 7, 24)]
        raw = pd.DataFrame(
            {
                COL_DATE: days,
                COL_OPEN: [10000, 10050, 10100],
                COL_HIGH: [10000, 10050, 10100],
                COL_LOW: [10000, 10050, 10100],
                COL_CLOSE: [10000, 10050, 10100],
                COL_VOLUME: [1, 1, 1],
                COL_BASE_PRICE: [10000, 9900, 10050],
                COL_CHANGE_RATE: [0.0, round((10050 / 9900 - 1) * 100, 2), round((10100 / 10050 - 1) * 100, 2)],
            }
        )
        raw_path = price_path("069500", PriceBasis.RAW)
        dividends_path = SERIES_DIR / "069500_yahoo_dividends.csv"
        save_prices(raw, tmp_path / raw_path)
        save_series(pd.DataFrame({COL_DATE: [], COL_VALUE: []}), tmp_path / dividends_path, decimals=6)
        dataset = Dataset(name="069500", kind=Kind.KRX_ETF, method=Method.FIXED, files=(raw_path, dividends_path))

        # When
        prices, notes = build_kr_products(tmp_path, {}, (dataset,))

        # Then
        adjusted = prices[kr_adjusted_path("069500")]
        assert adjusted[COL_CLOSE].tolist()[0] == 10000 * 9900 / 10000
        assert adjusted[COL_CLOSE].tolist()[-1] == 10100
        assert len(notes[kr_adjusted_path("069500")]) == 1
