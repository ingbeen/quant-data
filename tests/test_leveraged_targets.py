"""레버리지 합성 상품 표 테스트

레버리지 합성 상품 표(이름 · 기초 시세 · 실물 시세 · 배율 · 합성 파일)의 계약을 검증한다.
"""

from quant_data.leveraged.constants import LEVERAGED_SYNTHETIC_TARGETS


class TestLeveragedSyntheticTargets:
    """레버리지 합성 상품 표의 계약 테스트 — 한 줄에 상품 하나의 모든 연결이 있다"""

    def test_leverage_by_product(self):
        """
        목적: 상품별 배율을 숫자로 고정한다 — 배율이 틀리면 합성 시세가 에러 없이 다른 배수로 만들어진다

        Given: 레버리지 합성 상품 표
        When: 이름별 배율을 모은다
        Then: TQQQ · UPRO 3배, QLD · SSO 2배
        """
        # When
        leverage_by_name = {name: leverage for name, _, _, leverage, _ in LEVERAGED_SYNTHETIC_TARGETS}

        # Then
        assert leverage_by_name == {"TQQQ": 3.0, "QLD": 2.0, "SSO": 2.0, "UPRO": 3.0}

    def test_underlying_file_by_product(self):
        """
        목적: 상품별 기초 시세를 고정한다 — 기초가 바뀌면 나스닥 100 상품이 S&P 500 으로(또는 반대로) 에러 없이 만들어진다

        Given: 레버리지 합성 상품 표
        When: 이름별 기초 시세 파일 이름을 모은다
        Then: TQQQ · QLD 는 QQQ 합성, SSO · UPRO 는 SPY 합성
        """
        # When
        files_by_name = {name: underlying.name for name, underlying, _, _, _ in LEVERAGED_SYNTHETIC_TARGETS}

        # Then
        assert files_by_name == {
            "TQQQ": "QQQ_synthetic.csv",
            "QLD": "QQQ_synthetic.csv",
            "SSO": "SPY_synthetic.csv",
            "UPRO": "SPY_synthetic.csv",
        }

    def test_actual_file_by_product(self):
        """
        목적: 상품별 실물 시세를 고정한다 — 실물이 바뀌면 다른 상품의 실물에 이어 붙인 합성이 에러 없이 나간다.
              실물은 수정주가 파일이다 — 합성의 이음매 뒤 행이 실물 행 그대로라 원본가를 이으면 배당이 빠진 합성이 된다

        Given: 레버리지 합성 상품 표
        When: 이름별 실물 시세 파일 이름을 모은다
        Then: 상품마다 자기 수정주가 파일이다
        """
        # When
        files_by_name = {name: actual.name for name, _, actual, _, _ in LEVERAGED_SYNTHETIC_TARGETS}

        # Then
        assert files_by_name == {
            "TQQQ": "TQQQ_adjusted.csv",
            "QLD": "QLD_adjusted.csv",
            "SSO": "SSO_adjusted.csv",
            "UPRO": "UPRO_adjusted.csv",
        }

    def test_synthetic_file_by_product(self):
        """
        목적: 상품마다 자기 합성 파일에 저장됨을 고정한다 — 경로가 겹치면 전략이 읽는 TQQQ 합성이
              2배 시세로 에러 없이 덮인다. 합성은 이 표를 도는 src 함수가 만든다(test_leveraged_synthetic)

        Given: 레버리지 합성 상품 표
        When: 이름별 합성 파일 이름을 모은다
        Then: 상품마다 자기 파일
        """
        # When
        files_by_name = {name: output.name for name, _, _, _, output in LEVERAGED_SYNTHETIC_TARGETS}

        # Then
        assert files_by_name == {
            "TQQQ": "TQQQ_synthetic.csv",
            "QLD": "QLD_synthetic.csv",
            "SSO": "SSO_synthetic.csv",
            "UPRO": "UPRO_synthetic.csv",
        }
