"""
레버리지 합성의 월별 데이터(금리 · 운용비율) 테스트

이 파일은 무엇을 검증하나요?
1. 월별 데이터(FFR · Expense Ratio) 파일이 정확히 로드되는가?
2. 파일이 없을 때 명확한 에러를 내는가?
3. FFR/Expense 딕셔너리 생성 및 조회가 정확한가?
4. 월별 데이터 중복/갭 · 상한을 넘는 값(% 로 적은 값) 검증이 작동하는가?
5. 운용비율 딕셔너리 확장이 정확한가? (기초 시세의 첫 달부터 고정값 채우기)
6. FRED 월별 금리를 읽어 비율로 바꾸고, 받기는 파일을 쓰지 않는가? (결정 Q17)
7. 다시 받은 금리는 지난 달이 그대로일 때만 새 달을 붙이는가? (결정 Q36 · 판정 원칙)

왜 중요한가요?
TQQQ 시뮬레이션의 비용 계산은 FFR · 운용비율 데이터에 의존합니다.
잘못된 데이터는 잘못된 비용 계산과 합성 시세를 초래합니다.
"""

import math
from datetime import date

import pandas as pd
import pytest

from quant_data.leveraged import monthly_data
from quant_data.leveraged.constants import (
    COL_EXPENSE_DATE,
    COL_EXPENSE_VALUE,
    COL_FFR_DATE,
    COL_FFR_VALUE,
    DEFAULT_PRE_LISTING_EXPENSE_RATIO,
)
from quant_data.leveraged.monthly_data import (
    MAX_EXPENSE_VALUE,
    MAX_FFR_VALUE,
    _create_monthly_data_dict,
    _lookup_monthly_data,
    build_extended_expense_dict,
    create_expense_dict,
    create_ffr_dict,
    fetch_ffr_monthly,
    judge_monthly_append,
    load_monthly_data,
    lookup_ffr,
    parse_fred_ffr_csv,
    save_monthly_data,
)
from quant_data.revision import RevisionKind


class TestLoadMonthlyData:
    """월별 데이터(연방기금금리 · 운용비율) 파일 로딩 테스트"""

    def test_normal_load(self, tmp_path, sample_ffr_df):
        """
        월별 데이터 정상 로딩 테스트

        데이터 신뢰성: TQQQ 시뮬레이션의 비용 계산에 필수적인 데이터입니다.

        Given: DATE, VALUE 컬럼이 있는 CSV
        When: load_monthly_data 호출
        Then: DATE · VALUE 컬럼이 그대로 유지되고 행 수가 같다 (DATE 는 yyyy-mm 문자열 그대로)
        """
        # Given
        csv_path = tmp_path / "ffr.csv"
        sample_ffr_df.to_csv(csv_path, index=False)

        # When
        df = load_monthly_data(csv_path)

        # Then: 원본 CSV 스키마 회귀 탐지를 위해 리터럴 유지
        assert "VALUE" in df.columns, "VALUE 컬럼이 유지되어야 합니다"
        assert "DATE" in df.columns, "DATE 컬럼이 유지되어야 합니다"
        assert len(df) == 3
        assert df["DATE"].tolist() == sample_ffr_df["DATE"].tolist()

    def test_file_not_found(self, tmp_path):
        """
        월별 데이터 파일 부재 테스트

        Given: 존재하지 않는 파일
        When: load_monthly_data 호출
        Then: FileNotFoundError
        """
        # Given
        non_existent = tmp_path / "no_monthly.csv"

        # When & Then
        with pytest.raises(FileNotFoundError):
            load_monthly_data(non_existent)


class TestCreateFfrDict:
    """FFR 딕셔너리 생성 함수 테스트"""

    def test_create_ffr_dict_normal(self):
        """
        정상적인 FFR 딕셔너리 생성 테스트

        Given: 정상적인 FFR DataFrame (중복 없음)
        When: create_ffr_dict 호출
        Then: {"YYYY-MM": ffr_value} 딕셔너리 반환
        """
        # Given
        ffr_df = pd.DataFrame({COL_FFR_DATE: ["2023-01", "2023-02", "2023-03"], COL_FFR_VALUE: [0.045, 0.046, 0.047]})

        # When
        result = create_ffr_dict(ffr_df)

        # Then
        assert isinstance(result, dict)
        assert result == {"2023-01": 0.045, "2023-02": 0.046, "2023-03": 0.047}

    def test_create_ffr_dict_empty(self):
        """
        빈 DataFrame 입력 시 예외 발생 테스트

        Given: 빈 FFR DataFrame
        When: create_ffr_dict 호출
        Then: ValueError 발생
        """
        # Given
        ffr_df = pd.DataFrame({COL_FFR_DATE: [], COL_FFR_VALUE: []})

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터가 비어있습니다"):
            create_ffr_dict(ffr_df)

    def test_create_ffr_dict_duplicate_month(self):
        """
        중복 월 발견 시 즉시 예외 발생 테스트 (중대 에러)

        Given: 중복 월이 포함된 FFR DataFrame
        When: create_ffr_dict 호출
        Then: ValueError 발생 (데이터 무결성 보장)
        """
        # Given
        ffr_df = pd.DataFrame(
            {
                COL_FFR_DATE: ["2023-01", "2023-02", "2023-02", "2023-03"],
                COL_FFR_VALUE: [0.045, 0.046, 0.0465, 0.047],
            }
        )

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터 무결성 오류.*2023-02.*중복"):
            create_ffr_dict(ffr_df)


class TestLookupFfr:
    """FFR 조회 함수 테스트"""

    def test_lookup_ffr_exact_match(self):
        """
        정확한 월 매칭 테스트

        Given: FFR 딕셔너리와 딕셔너리에 존재하는 월의 날짜
        When: lookup_ffr 호출
        Then: 해당 월의 FFR 값 반환
        """
        # Given
        ffr_dict = {"2023-01": 4.5, "2023-02": 4.6, "2023-03": 4.7}
        date_value = date(2023, 2, 15)

        # When
        result = lookup_ffr(date_value, ffr_dict)

        # Then
        assert result == 4.6

    def test_lookup_ffr_fallback(self):
        """
        이전 월 폴백 테스트

        Given: FFR 딕셔너리와 딕셔너리에 없는 월의 날짜 (단, 이전 월은 존재)
        When: lookup_ffr 호출
        Then: 가장 가까운 이전 월의 FFR 값 반환
        """
        # Given
        ffr_dict = {"2023-01": 4.5, "2023-02": 4.6}
        date_value = date(2023, 3, 15)  # 2023-03은 없음

        # When
        result = lookup_ffr(date_value, ffr_dict)

        # Then
        assert result == 4.6  # 2023-02의 값

    def test_lookup_ffr_no_previous_month(self):
        """
        이전 월도 없는 경우 예외 발생 테스트

        Given: FFR 딕셔너리와 딕셔너리보다 이른 날짜
        When: lookup_ffr 호출
        Then: ValueError 발생
        """
        # Given
        ffr_dict = {"2023-02": 4.6, "2023-03": 4.7}
        date_value = date(2023, 1, 15)  # 2023-01은 없고 이전 월도 없음

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터 부족.*2023-01.*이전의 FFR 데이터가 존재하지 않습니다"):
            lookup_ffr(date_value, ffr_dict)

    def test_lookup_ffr_months_diff_exceeded(self):
        """
        월 차이 초과 시 예외 발생 테스트

        Given: FFR 딕셔너리와 MAX_FFR_MONTHS_DIFF(2) 초과한 날짜
        When: lookup_ffr 호출
        Then: ValueError 발생
        """
        # Given
        ffr_dict = {"2023-01": 4.5, "2023-02": 4.6}
        date_value = date(2023, 5, 15)  # 2023-05, 가장 가까운 이전 월은 2023-02 (3개월 차이 > MAX=2)

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터 부족.*2023-05.*최대 2개월 이내의 데이터만 사용 가능"):
            lookup_ffr(date_value, ffr_dict)


class TestGenericMonthlyDataDict:
    """제네릭 월별 데이터 딕셔너리 생성/조회 테스트"""

    def test_create_monthly_data_dict_basic(self):
        """
        제네릭 딕셔너리 생성 기본 테스트

        Given: 월별 데이터 DataFrame
        When: _create_monthly_data_dict 호출
        Then: {월: 값} 딕셔너리 반환
        """
        # Given (0~1 비율)
        df = pd.DataFrame({COL_EXPENSE_DATE: ["2023-01", "2023-02"], COL_EXPENSE_VALUE: [0.0095, 0.0088]})

        # When: 제네릭 함수 호출
        result_dict = _create_monthly_data_dict(df, COL_EXPENSE_DATE, COL_EXPENSE_VALUE, "Expense", MAX_EXPENSE_VALUE)

        # Then
        assert result_dict == {"2023-01": 0.0095, "2023-02": 0.0088}

    def test_create_monthly_data_dict_duplicates(self):
        """
        중복 월 검증 테스트

        Given: 중복 월이 있는 DataFrame
        When: _create_monthly_data_dict 호출
        Then: ValueError 발생 (data_type 포함한 명확한 메시지)
        """
        # Given: 2023-01이 중복 (0~1 비율)
        df = pd.DataFrame(
            {COL_EXPENSE_DATE: ["2023-01", "2023-01", "2023-02"], COL_EXPENSE_VALUE: [0.0095, 0.0096, 0.0088]}
        )

        # When & Then
        with pytest.raises(ValueError, match="Expense.*2023-01.*중복"):
            _create_monthly_data_dict(df, COL_EXPENSE_DATE, COL_EXPENSE_VALUE, "Expense", MAX_EXPENSE_VALUE)

    @pytest.mark.parametrize(
        "bad_value",
        [math.nan, math.inf, MAX_FFR_VALUE, 3.63],
        ids=["nan", "inf", "upper_bound", "percent_unit"],
    )
    def test_create_ffr_dict_rejects_invalid_value(self, bad_value):
        """
        목적: 금리가 빈 칸 · inf · 상한 이상이면 멈춤을 검증 — 손으로 고치는 파일이라 % 로 적은 값(3.63)이나 빈 칸이
              들어올 수 있고, 그대로 쓰면 시뮬 종가가 0 이하 · NaN 이 된다

        Given: 2023-02 값만 잘못된 금리 DataFrame
        When: create_ffr_dict 호출
        Then: ValueError (data_type · 월 포함)
        """
        # Given
        df = pd.DataFrame({COL_FFR_DATE: ["2023-01", "2023-02"], COL_FFR_VALUE: [0.045, bad_value]})

        # When & Then
        with pytest.raises(ValueError, match="FFR 데이터 오류: 월 2023-02"):
            create_ffr_dict(df)

    @pytest.mark.parametrize(
        "bad_value",
        [MAX_EXPENSE_VALUE, 0.84],
        ids=["upper_bound", "prospectus_percent"],
    )
    def test_create_expense_dict_rejects_percent_unit(self, bad_value):
        """
        목적: 운용비율이 상한 이상이면 멈춤을 검증 — 설명서는 「Net 0.84」처럼 % 로 적어, 그대로 옮기면 1 미만이라도
              비용이 백 배가 된다

        Given: 2023-02 값만 % 표기인 운용비율 DataFrame
        When: create_expense_dict 호출
        Then: ValueError (data_type · 월 포함)
        """
        # Given
        df = pd.DataFrame({COL_EXPENSE_DATE: ["2023-01", "2023-02"], COL_EXPENSE_VALUE: [0.0088, bad_value]})

        # When & Then
        with pytest.raises(ValueError, match="Expense 데이터 오류: 월 2023-02"):
            create_expense_dict(df)

    @pytest.mark.parametrize("bad_key", ["2026-3", "2026-13"], ids=["missing_zero", "no_such_month"])
    @pytest.mark.parametrize(
        ("create_dict", "date_col", "value_col", "value"),
        [
            (create_ffr_dict, COL_FFR_DATE, COL_FFR_VALUE, 0.045),
            (create_expense_dict, COL_EXPENSE_DATE, COL_EXPENSE_VALUE, 0.0088),
        ],
        ids=["ffr", "expense"],
    )
    def test_create_dict_rejects_malformed_month_key(self, create_dict, date_col, value_col, value, bad_key):
        """
        목적: 월 키가 yyyy-mm 이 아니면 멈춤을 검증 — 조회는 「2026-03」 으로 찾고 없으면 문자열로 이전 달을 고르는데,
              「2026-3」 은 「2026-03」 ~ 「2026-09」 보다 크게 비교되어 그 값이 쓰이지 않고 직전 값이 조용히 쓰인다

        Given: 마지막 줄의 월 키만 모양이 틀린 금리 · 운용비율 DataFrame
        When: create_ffr_dict · create_expense_dict 호출
        Then: ValueError (그 키 포함)
        """
        # Given
        df = pd.DataFrame({date_col: ["2026-02", bad_key], value_col: [value, value]})

        # When & Then
        with pytest.raises(ValueError, match=f"월 키 '{bad_key}'"):
            create_dict(df)

    def test_realistic_values_accepted(self):
        """
        목적: 실제로 나올 수 있는 값은 받음을 검증 — 음수 금리(하한을 두지 않는 계약, 대체 시세의 금리 누적도 그대로 쓴다) ·
              1980년대 초 수준의 금리(0.19) · 레버리지 ETF 로 높은 편인 운용비율(0.02). 상한을 너무 낮추면 여기서 실패한다

        Given: 그 값이 든 금리 · 운용비율 DataFrame
        When: create_ffr_dict · create_expense_dict 호출
        Then: 값 그대로 딕셔너리에 들어간다
        """
        # Given
        ffr_df = pd.DataFrame({COL_FFR_DATE: ["2023-01", "2023-02"], COL_FFR_VALUE: [-0.0005, 0.19]})
        expense_df = pd.DataFrame({COL_EXPENSE_DATE: ["2023-01"], COL_EXPENSE_VALUE: [0.02]})

        # When
        ffr_dict = create_ffr_dict(ffr_df)
        expense_dict = create_expense_dict(expense_df)

        # Then
        assert ffr_dict == {"2023-01": -0.0005, "2023-02": 0.19}
        assert expense_dict == {"2023-01": 0.02}

    def test_lookup_monthly_data_with_gap(self):
        """
        월 차이 검증 테스트

        Given: 월별 데이터 딕셔너리와 갭이 큰 날짜
        When: _lookup_monthly_data 호출
        Then: max_months_diff 초과 시 ValueError 발생
        """
        # Given
        data_dict = {"2023-01": 0.0095}
        date_value = date(2024, 2, 15)  # 2024-02, 2023-01부터 13개월 차이

        # When & Then: max_months_diff=12 초과
        with pytest.raises(ValueError, match="Expense.*데이터 부족.*2024-02.*최대 12개월"):
            _lookup_monthly_data(date_value, data_dict, max_months_diff=12, data_type="Expense")

    def test_lookup_monthly_data_within_gap(self):
        """
        월 차이 허용 범위 내 조회 테스트

        Given: 월별 데이터 딕셔너리와 허용 범위 내 날짜
        When: _lookup_monthly_data 호출
        Then: 가장 가까운 이전 월의 값 반환
        """
        # Given
        data_dict = {"2023-01": 0.0095, "2023-02": 0.0088}
        date_value = date(2023, 12, 15)  # 2023-12, 2023-02부터 10개월 차이 (12개월 이내)

        # When
        result = _lookup_monthly_data(date_value, data_dict, max_months_diff=12, data_type="Expense")

        # Then: 2023-02 값 사용
        assert result == pytest.approx(0.0088)


class TestBuildExtendedExpenseDict:
    """운용비율 딕셔너리 확장 테스트 — 기초 시세의 첫 달부터 파일 첫 달 전까지 상장 전 고정값"""

    @staticmethod
    def _expense_df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                COL_EXPENSE_DATE: ["2010-02", "2010-03", "2010-04"],
                COL_EXPENSE_VALUE: [0.0095, 0.0093, 0.0091],
            }
        )

    def test_extends_from_first_month(self):
        """
        목적: 시작 달부터 파일 첫 달 직전까지 상장 전 고정값을 채운다 — 1985년부터 도는 합성이 첫날에 멈추지 않는다

        Given: 2010-02 부터인 운용비율, 시작 달 1985-10
        When: build_extended_expense_dict 호출
        Then: 1985-10 · 2005-06 · 2010-01 은 고정값, 그 앞 달(1985-09)은 없다
        """
        # When
        result = build_extended_expense_dict(self._expense_df(), "1985-10")

        # Then
        assert result["1985-10"] == pytest.approx(DEFAULT_PRE_LISTING_EXPENSE_RATIO)
        assert result["2005-06"] == pytest.approx(DEFAULT_PRE_LISTING_EXPENSE_RATIO)
        assert result["2010-01"] == pytest.approx(DEFAULT_PRE_LISTING_EXPENSE_RATIO)
        assert "1985-09" not in result

    def test_original_values_preserved(self):
        """
        목적: 확장해도 파일의 값은 그대로다

        Given: 2010-02 부터인 운용비율
        When: 시작 달 1999-01 로 build_extended_expense_dict 호출
        Then: 파일 석 달의 값이 그대로
        """
        # When
        result = build_extended_expense_dict(self._expense_df(), "1999-01")

        # Then
        assert result["2010-02"] == pytest.approx(0.0095)
        assert result["2010-03"] == pytest.approx(0.0093)
        assert result["2010-04"] == pytest.approx(0.0091)

    def test_extension_count(self):
        """
        목적: 채우는 달 수를 고정한다

        Given: 2010-02 부터인 운용비율 3개월
        When: 시작 달 1999-01 로 build_extended_expense_dict 호출
        Then: 1999-01 ~ 2010-01 = 133개월 + 원본 3개월 = 136개
        """
        # When
        result = build_extended_expense_dict(self._expense_df(), "1999-01")

        # Then
        assert len(result) == 136

    @pytest.mark.parametrize("first_month", ["2010-02", "2010-03"])
    def test_no_extension_when_first_month_not_before_file(self, first_month: str):
        """
        목적: 시작 달이 파일 첫 달과 같거나 뒤면 늘리지 않는다 (경계)

        Given: 2010-02 부터인 운용비율, 시작 달 2010-02 · 2010-03
        When: build_extended_expense_dict 호출
        Then: 원본 3개월 그대로
        """
        # When
        result = build_extended_expense_dict(self._expense_df(), first_month)

        # Then
        assert sorted(result) == ["2010-02", "2010-03", "2010-04"]

    @pytest.mark.parametrize("first_month", ["1985-13", "198510", "1985-1", ""])
    def test_rejects_bad_first_month(self, first_month: str):
        """
        목적: 시작 달이 YYYY-MM 이 아니면 멈춘다 — 문자열 비교로 달을 세므로 모양이 다르면 조용히 틀린다

        Given: 잘못된 모양의 시작 달
        When: build_extended_expense_dict 호출
        Then: ValueError
        """
        # When & Then
        with pytest.raises(ValueError, match="YYYY-MM"):
            build_extended_expense_dict(self._expense_df(), first_month)


FRED_HEADER = "observation_date,FEDFUNDS"


class TestParseFredFfrCsv:
    """FRED 월별 연방기금금리 CSV 읽기 — % 를 비율로, 날짜를 yyyy-mm 으로"""

    def test_percent_to_ratio_and_month_key(self):
        """
        목적: % 값을 비율로 바꾸고 날짜를 yyyy-mm 으로 바꾼다 — 기존 금리 파일과 같은 형식

        Given: FRED 이어진 두 달 (0.80% · 4.63%)
        When: parse_fred_ffr_csv
        Then: DATE ["1954-07", "1954-08"], VALUE [0.008, 0.0463]
        """
        # Given
        text = f"{FRED_HEADER}\n1954-07-01,0.80\n1954-08-01,4.63\n"

        # When
        result = parse_fred_ffr_csv(text)

        # Then
        assert list(result.columns) == [COL_FFR_DATE, COL_FFR_VALUE]
        assert result[COL_FFR_DATE].tolist() == ["1954-07", "1954-08"]
        assert result[COL_FFR_VALUE].tolist() == [0.008, 0.0463]

    def test_rejects_unexpected_header(self):
        """
        목적: 헤더가 다르면 멈춘다 — FRED 는 날짜 열 이름을 바꾼 적이 있다(DATE → observation_date)

        Given: 날짜 열 이름이 DATE 인 CSV
        When: parse_fred_ffr_csv
        Then: ValueError
        """
        # Given
        text = "DATE,FEDFUNDS\n1999-01-01,4.63\n"

        # When & Then
        with pytest.raises(ValueError, match="헤더"):
            parse_fred_ffr_csv(text)

    @pytest.mark.parametrize("value", [".", ""])
    def test_rejects_missing_value(self, value: str):
        """
        목적: 값이 빈 칸 · 「.」(FRED 의 결측 표기)이면 멈춘다 — 메우지 않는다

        Given: 값이 비어 있는 달
        When: parse_fred_ffr_csv
        Then: ValueError
        """
        # Given
        text = f"{FRED_HEADER}\n1999-01-01,4.63\n1999-02-01,{value}\n"

        # When & Then
        with pytest.raises(ValueError, match="1999-02"):
            parse_fred_ffr_csv(text)

    def test_rejects_non_month_start_date(self):
        """
        목적: 월별 값의 날짜는 그달 1일이다 — 다른 날이면 일별 · 주별 시리즈를 잘못 받은 것이라 멈춘다

        Given: 1999-01-15
        When: parse_fred_ffr_csv
        Then: ValueError
        """
        # Given
        text = f"{FRED_HEADER}\n1999-01-15,4.63\n"

        # When & Then
        with pytest.raises(ValueError, match="1999-01-15"):
            parse_fred_ffr_csv(text)

    def test_rejects_missing_month(self):
        """
        목적: 달이 빠지면 멈춘다 — 빠진 달은 조회가 이전 달 값으로 조용히 메워 틀린 비용이 합성에 들어간다

        Given: 1999-01 다음이 1999-03
        When: parse_fred_ffr_csv
        Then: ValueError (빠진 자리를 알린다)
        """
        # Given
        text = f"{FRED_HEADER}\n1999-01-01,4.63\n1999-03-01,4.81\n"

        # When & Then
        with pytest.raises(ValueError, match="이어지지"):
            parse_fred_ffr_csv(text)

    def test_rejects_no_rows(self):
        """
        목적: 값이 하나도 없으면 멈춘다 (경계)

        Given: 헤더뿐인 CSV
        When: parse_fred_ffr_csv
        Then: ValueError
        """
        # When & Then
        with pytest.raises(ValueError, match="비어"):
            parse_fred_ffr_csv(f"{FRED_HEADER}\n")


class _FakeResponse:
    """urlopen 이 돌려주는 응답 대역 — with 문과 read 만 쓴다."""

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class TestFetchFfrMonthly:
    """FRED 금리 받기 — 읽고 검사한 표를 돌려주고 파일은 쓰지 않는다 (결정 Q17)"""

    def test_returns_checked_table_without_writing(self, tmp_path, monkeypatch):
        """
        목적: 받은 금리를 금리 파일 형식으로 돌려주고 아무 파일도 쓰지 않는다 — 쓰기는 모든 판정이 끝난 뒤 갱신이 한다

        Given: FRED 두 달 (4.63% · 5.20%), 빈 실행 위치
        When: fetch_ffr_monthly
        Then: DATE ["1999-01", "1999-02"] · VALUE [0.0463, 0.052], 실행 위치에 파일 없음
        """
        # Given
        body = f"{FRED_HEADER}\n1999-01-01,4.63\n1999-02-01,5.20\n"
        monkeypatch.setattr(monthly_data, "urlopen", lambda url, timeout: _FakeResponse(body))
        monkeypatch.chdir(tmp_path)

        # When
        result = fetch_ffr_monthly()

        # Then
        assert result[COL_FFR_DATE].tolist() == ["1999-01", "1999-02"]
        assert result[COL_FFR_VALUE].tolist() == [0.0463, 0.052]
        assert list(tmp_path.iterdir()) == []

    def test_invalid_value_raises(self, monkeypatch):
        """
        목적: 검사(상한)에 걸리는 값을 받으면 멈춘다 — 판정 전에 % 그대로인 값을 막는다

        Given: 상한(MAX_FFR_VALUE) 이상인 값을 주는 FRED
        When: fetch_ffr_monthly
        Then: ValueError
        """
        # Given
        body = f"{FRED_HEADER}\n1999-01-01,{MAX_FFR_VALUE * 100 + 1}\n"
        monkeypatch.setattr(monthly_data, "urlopen", lambda url, timeout: _FakeResponse(body))

        # When & Then
        with pytest.raises(ValueError):
            fetch_ffr_monthly()


class TestSaveMonthlyData:
    """월별 파일 저장 — 기존 금리 파일과 같은 글자"""

    def test_writes_crlf_in_existing_format(self, tmp_path):
        """
        목적: 기존 금리 파일과 같은 글자로 쓴다 — 줄 끝 CRLF, 값은 0.0463 · 0.052 모양. 같은 값이면 git diff 에 새 달만 보인다

        Given: 두 달 (0.0463 · 0.052)
        When: save_monthly_data
        Then: 파일 바이트가 b"DATE,VALUE\\r\\n1999-01,0.0463\\r\\n1999-02,0.052\\r\\n"
        """
        # Given
        df = pd.DataFrame({COL_FFR_DATE: ["1999-01", "1999-02"], COL_FFR_VALUE: [0.0463, 0.052]})
        path = tmp_path / "ffr.csv"

        # When
        save_monthly_data(df, path)

        # Then
        assert path.read_bytes() == b"DATE,VALUE\r\n1999-01,0.0463\r\n1999-02,0.052\r\n"

    def test_written_file_round_trips(self, tmp_path):
        """
        목적: 쓴 파일을 load_monthly_data · create_ffr_dict 로 다시 읽으면 같은 값이다

        Given: 두 달
        When: save_monthly_data 뒤 다시 읽는다
        Then: {"1999-01": 0.0463, "1999-02": 0.052}
        """
        # Given
        df = pd.DataFrame({COL_FFR_DATE: ["1999-01", "1999-02"], COL_FFR_VALUE: [0.0463, 0.052]})
        path = tmp_path / "ffr.csv"

        # When
        save_monthly_data(df, path)

        # Then
        assert create_ffr_dict(load_monthly_data(path)) == {"1999-01": 0.0463, "1999-02": 0.052}


def _monthly(months: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({COL_FFR_DATE: months, COL_FFR_VALUE: values})


class TestJudgeMonthlyAppend:
    """월별 금리 덧붙이기 판정 — 지난 달이 그대로면 새 달만 붙이고, 바뀌거나 빠지면 비정상 (결정 Q36 · 판정 원칙)"""

    def test_new_file(self):
        """
        목적: 기존 파일이 없으면 받은 표 그대로 새 파일이다

        Given: 기존 없음, 응답 두 달
        When: judge_monthly_append
        Then: NEW, 저장할 표 = 응답
        """
        # Given
        response = _monthly(["1999-01", "1999-02"], [0.0463, 0.0476])

        # When
        revision = judge_monthly_append(None, response)

        # Then
        assert revision.kind is RevisionKind.NEW
        pd.testing.assert_frame_equal(revision.values, response)

    def test_same_past_appends_new_months(self):
        """
        목적: 지난 달 값이 같으면 기존 행은 그대로 두고 기존 마지막 달 뒤의 새 달만 붙인다

        Given: 기존 1999-01 · 1999-02, 응답 1999-01 ~ 1999-04 (앞 두 달 값 같음)
        When: judge_monthly_append
        Then: NOISE, 저장할 표 = 기존 두 달 + 1999-03 · 1999-04
        """
        # Given
        existing = _monthly(["1999-01", "1999-02"], [0.0463, 0.0476])
        response = _monthly(["1999-01", "1999-02", "1999-03", "1999-04"], [0.0463, 0.0476, 0.0481, 0.0474])

        # When
        revision = judge_monthly_append(existing, response)

        # Then
        assert revision.kind is RevisionKind.NOISE
        pd.testing.assert_frame_equal(revision.values, response)

    def test_changed_past_value_is_abnormal(self):
        """
        목적: 지난 달 값이 바뀌면 비정상 — 「데이터가 바뀌면 오류」(판정 원칙). 진단 줄에 그 달과 두 값을 적는다

        Given: 기존 1999-01 = 0.0463, 응답 1999-01 = 0.0470
        When: judge_monthly_append
        Then: ABNORMAL, 진단 줄에 「1999-01」 · 「0.0463」 · 「0.047」
        """
        # Given
        existing = _monthly(["1999-01", "1999-02"], [0.0463, 0.0476])
        response = _monthly(["1999-01", "1999-02", "1999-03"], [0.0470, 0.0476, 0.0481])

        # When
        revision = judge_monthly_append(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("1999-01" in line and "0.0463" in line and "0.047" in line for line in revision.issues)

    def test_truncated_response_is_abnormal(self):
        """
        목적: 응답이 기존 달을 다 덮지 못하면(잘린 응답) 비정상 — 앞 기간이 지워지면 1985년부터 도는 합성이 멈춘다

        Given: 기존 1999-01 ~ 1999-03, 1999-02 부터만 주는 응답
        When: judge_monthly_append
        Then: ABNORMAL, 진단 줄에 「1999-01」 · 「응답에 없음」
        """
        # Given
        existing = _monthly(["1999-01", "1999-02", "1999-03"], [0.0463, 0.0476, 0.0481])
        response = _monthly(["1999-02", "1999-03", "1999-04"], [0.0476, 0.0481, 0.0474])

        # When
        revision = judge_monthly_append(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("1999-01" in line and "응답에 없음" in line for line in revision.issues)

    @pytest.mark.parametrize(
        ("received", "expected_kind"),
        [(0.0463 + 0.4e-6, RevisionKind.NOISE), (0.0463 + 0.6e-6, RevisionKind.ABNORMAL)],
    )
    def test_rounding_half_unit_boundary(self, received, expected_kind):
        """
        목적: 저장 자릿수(ROUND_MONTHLY_RATE = 6)의 반 단위까지는 같은 값으로 본다 (경계) — 파일 값은 반올림돼 있다

        Given: 기존 0.0463, 응답 0.0463 + 0.4e-6 또는 + 0.6e-6
        When: judge_monthly_append
        Then: 0.4e-6 → NOISE, 0.6e-6 → ABNORMAL
        """
        # Given
        existing = _monthly(["1999-01"], [0.0463])
        response = _monthly(["1999-01", "1999-02"], [received, 0.0476])

        # When
        revision = judge_monthly_append(existing, response)

        # Then
        assert revision.kind is expected_kind
