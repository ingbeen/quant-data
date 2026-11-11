"""
products 모듈 테스트 — 가공(합성 · 검증 표) 대상 표의 연결

이 파일은 무엇을 검증하나요?
1. 1배 대용 합성 대상 표가 상품마다 정해진 대용 · 실물 · 저장 경로를 잇는가?
2. 검증 ④ 대상 표가 레버리지 상품 표의 기초를 모두 덮는가?

왜 중요한가요?
대용 · 실물 · 저장 경로가 어긋나면 다른 상품의 시세로 이은 합성이 에러 없이 저장된다. 계산 자체는 옮긴 함수들의
테스트와, 첫 판에서 quant 합성과 값이 같은지의 대조가 지킨다.
"""

from quant_data.leveraged.constants import LEVERAGED_SYNTHETIC_TARGETS
from quant_data.products import ASSUMPTION_TARGETS, PROXY_TARGETS


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
