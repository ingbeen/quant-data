"""
sources.krx 모듈 테스트 — KRX 받기의 정규화 · 자격증명 · 표준출력 거르기 (네트워크 없이)

이 파일은 무엇을 검증하나요?
1. KRX 화면 조회(ETF 개별종목 시세 추이)의 행을 시세 표로 바꿀 때 대비에 등락 구분의 부호를 붙여 기준가 = 종가 − 대비를
   내고, 가격을 부호 있는 정수로 두는가? (`uint32` 차분 언더플로 — verify-lab 실측)
2. 모르는 등락 구분 · 빠진 열은 멈추는가?
3. 자격증명은 저장소 루트의 .env 에서만 읽고, 값이 비면 멈추는가?
4. pykrx 가 표준출력에 찍는 줄 중 계정 아이디가 든 줄을 빼는가?

왜 중요한가요?
대비의 부호가 틀리면 기준가가 틀려 국내 수정주가 전 구간이 에러 없이 틀린다. 아이디가 실행 로그에 남으면
공개 저장소의 문서 · 커밋으로 옮겨질 수 있다.
"""

from datetime import date
from pathlib import Path

import pytest

from quant_data.constants import (
    COL_BASE_PRICE,
    COL_CHANGE_RATE,
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LISTED_SHARES,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
)
from quant_data.sources.krx import (
    ENV_KRX_ID,
    ENV_KRX_PW,
    filtered_pykrx_output,
    load_krx_credentials,
    normalize_etf_records,
)


def _record(day: str, close: str, sign_code: str, change: str, rate: str) -> dict[str, str]:
    """KRX 가 주는 모양의 하루치 행 — 값이 쉼표 붙은 문자열로 오고, 대비는 부호 없는 크기다."""
    return {
        "TRD_DD": day,
        "TDD_CLSPRC": close,
        "FLUC_TP_CD": sign_code,
        "CMPPREVDD_PRC": change,
        "FLUC_RT": rate,
        "TDD_OPNPRC": close,
        "TDD_HGPRC": close,
        "TDD_LWPRC": close,
        "ACC_TRDVOL": "1,000",
        "LIST_SHRS": "159,800,000",
    }


class TestNormalizeEtfRecords:
    """KRX 행 → 시세 표"""

    @pytest.mark.parametrize(
        ("sign_code", "expected_base"),
        [("1", 32035), ("4", 32035), ("2", 32455), ("5", 32455), ("3", 32245)],
        ids=["up", "upper_limit", "down", "lower_limit", "flat"],
    )
    def test_base_price_uses_signed_change(self, sign_code: str, expected_base: int) -> None:
        """
        목적: 기준가 = 종가 − 부호 붙은 대비 — 등락 구분 1 · 4 는 +, 2 · 5 는 −, 3 은 0

        Given: 종가 32,245 · 대비 210, 등락 구분 sign_code
        When: normalize_etf_records
        Then: 기준가 expected_base
        """
        # When
        frame = normalize_etf_records([_record("2022/07/28", "32,245", sign_code, "210", "0.66")])

        # Then
        assert frame[COL_BASE_PRICE].tolist() == [expected_base]

    def test_columns_types_and_order(self) -> None:
        """
        목적: 열 이름 · 정수 가격 · 실수 등락률 · 날짜 오름차순을 고정한다 — KRX 는 최근 날부터 준다

        Given: 07-29 · 07-28 두 행 (최근이 먼저)
        When: normalize_etf_records
        Then: 날짜 오름차순, 가격 · 기준가 · 거래량 · 상장좌수는 int64, 등락률은 실수
        """
        # When
        frame = normalize_etf_records(
            [
                _record("2022/07/29", "32,385", "1", "140", "0.43"),
                _record("2022/07/28", "32,245", "1", "210", "0.66"),
            ]
        )

        # Then
        assert frame[COL_DATE].tolist() == [date(2022, 7, 28), date(2022, 7, 29)]
        for col in (COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOLUME, COL_BASE_PRICE, COL_LISTED_SHARES):
            assert str(frame[col].dtype) == "int64", col
        assert frame[COL_CHANGE_RATE].tolist() == pytest.approx([0.66, 0.43], abs=1e-12)

    def test_unknown_sign_code_raises(self) -> None:
        """
        목적: 모르는 등락 구분이면 멈춘다 — 부호를 추측하면 기준가가 조용히 틀린다

        Given: 등락 구분 "9"
        When: normalize_etf_records
        Then: ValueError (「등락 구분」)
        """
        with pytest.raises(ValueError, match="등락 구분"):
            normalize_etf_records([_record("2022/07/28", "32,245", "9", "210", "0.66")])

    def test_missing_column_raises(self) -> None:
        """
        목적: 응답에 필요한 열이 없으면 멈춘다 — pykrx · KRX 가 열을 바꾸면 여기서 드러난다

        Given: 대비 열이 없는 행
        When: normalize_etf_records
        Then: ValueError (「CMPPREVDD_PRC」)
        """
        # Given
        record = _record("2022/07/28", "32,245", "1", "210", "0.66")
        del record["CMPPREVDD_PRC"]

        # When & Then
        with pytest.raises(ValueError, match="CMPPREVDD_PRC"):
            normalize_etf_records([record])


class TestCredentials:
    """KRX 자격증명 — 저장소 루트 .env"""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """
        목적: .env 가 없으면 멈추고 무엇을 해야 하는지 알린다

        Given: 없는 경로
        When: load_krx_credentials
        Then: ValueError (「.env」)
        """
        with pytest.raises(ValueError, match=r"\.env"):
            load_krx_credentials(tmp_path / ".env")

    def test_empty_value_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        목적: 키가 비면 멈춘다 — 빈 계정으로 로그인하면 KRX 가 빈 응답을 줘 원인이 흐려진다. 메시지에 값은 넣지 않는다

        Given: KRX_ID 만 채운 .env (셸 환경 변수는 비움)
        When: load_krx_credentials
        Then: ValueError, 메시지에 KRX_PW 가 있고 KRX_ID 의 값은 없다
        """
        # Given
        monkeypatch.delenv(ENV_KRX_ID, raising=False)
        monkeypatch.delenv(ENV_KRX_PW, raising=False)
        path = tmp_path / ".env"
        path.write_text(f"{ENV_KRX_ID}=someone\n{ENV_KRX_PW}=\n", encoding="utf-8")

        # When & Then
        with pytest.raises(ValueError, match=ENV_KRX_PW) as error:
            load_krx_credentials(path)
        assert "someone" not in str(error.value)


class TestFilteredPykrxOutput:
    """pykrx 표준출력 — 계정 아이디가 든 줄을 뺀다"""

    def test_account_lines_are_dropped(self) -> None:
        """
        목적: 아이디가 든 줄만 빼고 나머지는 남긴다 — 로그인 실패 같은 안내는 원인을 가리는 데 필요하다

        Given: 「KRX 로그인 성공: someone」 · 빈 줄 · 「경고: 세션 만료」
        When: filtered_pykrx_output(계정 someone)
        Then: [「경고: 세션 만료」]
        """
        # Given
        text = "KRX 로그인 성공: someone\n\n경고: 세션 만료\n"

        # When & Then
        assert filtered_pykrx_output(text, "someone") == ["경고: 세션 만료"]

    def test_empty_account_drops_nothing_but_blank_lines(self) -> None:
        """
        목적: 계정이 비어 있으면(자격증명을 아직 안 올림) 빈 줄만 뺀다 (경계) — 빈 문자열은 모든 줄에 들어 있어
              그대로 쓰면 모든 줄이 빠진다

        Given: 두 줄
        When: filtered_pykrx_output(계정 "")
        Then: 두 줄 그대로
        """
        assert filtered_pykrx_output("가\n나\n", "") == ["가", "나"]
