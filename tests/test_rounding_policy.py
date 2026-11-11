"""시세 파일의 가격 자릿수 정책 테스트

받은 시세 · 합성 · 국내 수정주가를 저장할 때 가격은 소수점 6자리다(결정 Q6). 전역 규칙의 4자리 상한과 다른 이유는
이 파일들이 사용처 백테스트의 «계산 입력»이라는 점이다 — 자릿수를 바꾸면 quant 의 CAGR · MDD 가 전부 미세하게 달라져
기록된 결과가 재현되지 않는다. 자릿수는 `ROUND_INPUT_PRICE` 하나로 관리하고 저장 지점에 숫자를 직접 적지 않는다.
"""

from quant_data.constants import ROUND_INPUT_PRICE


class TestInputPriceDecimals:
    """시세 파일 가격 자릿수를 고정"""

    def test_input_price_decimals_is_six(self) -> None:
        """
        목적: 시세 파일의 가격 자릿수가 6자리임을 고정한다 — quant 의 지금 입력 파일과 같은 자리라야 옮긴 뒤
              결과 수치 필드 차이가 0 이다(시세_받기_판정.md 6.8)

        Given: 시세 저장 자릿수 상수
        When: 비교
        Then: 6
        """
        # Then
        assert ROUND_INPUT_PRICE == 6
