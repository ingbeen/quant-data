"""
prices 모듈 테스트 — 시세 파일의 이름 · 읽기 · 검사 · 저장

이 파일은 무엇을 검증하나요?
1. 시세 파일 이름이 가격 기준(원본가 · 수정주가 · 합성)을 말하는가? (결정 Q10 · Q33)
2. CSV 를 읽을 때 날짜를 파싱 · 정렬하고, 필수 열 누락 · 중복 날짜 · 가격의 결측 · 0 · 음수면 멈추는가?
3. 저장이 가격 반올림(6자리) → 검사 → 저장 순서를 지키고, 검사에 걸리면 파일을 쓰지 않는가?
4. 하루 급등락으로는 검사 · 저장이 멈추지 않는가? (결정 Q26 — 신규 일자의 판정이 맡는다)

왜 중요한가요?
같은 이름이 저장소마다 다른 가격 기준을 뜻하면, 원본가를 수정주가로 읽어도 에러가 나지 않는다.
보간 없이 멈추는 검사가 없으면 결측 · 중복이 사용처의 모든 계산에 조용히 섞인다.
"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, PRICES_DIR
from quant_data.prices import (
    PriceBasis,
    load_prices,
    parse_price_file_name,
    price_path,
    save_prices,
    validate_price_series,
)


def _make_valid_df(rows: int = 5) -> pd.DataFrame:
    """정상 시세 — 2023-01-02 부터 하루씩, 가격은 1씩 오른다."""
    base_date = date(2023, 1, 2)
    dates = [base_date + timedelta(days=i) for i in range(rows)]
    return pd.DataFrame(
        {
            COL_DATE: dates,
            COL_OPEN: [100.0 + i for i in range(rows)],
            COL_HIGH: [105.0 + i for i in range(rows)],
            COL_LOW: [99.0 + i for i in range(rows)],
            COL_CLOSE: [103.0 + i for i in range(rows)],
            COL_VOLUME: [1000000 + i * 100000 for i in range(rows)],
        }
    )


class TestPricePath:
    """시세 파일 이름 — `{티커}_{가격 기준}.csv` (결정 Q10 · Q33)"""

    @pytest.mark.parametrize(
        ("basis", "name"),
        [
            (PriceBasis.RAW, "QQQ_raw.csv"),
            (PriceBasis.ADJUSTED, "QQQ_adjusted.csv"),
            (PriceBasis.SYNTHETIC, "QQQ_synthetic.csv"),
        ],
    )
    def test_name_states_price_basis(self, basis: PriceBasis, name: str) -> None:
        """
        목적: 파일 이름에 가격 기준을 넣고 `_max` 는 넣지 않는다 — 옛 이름(`QQQ_max.csv` 는 quant 에서 수정주가,
              verify-lab 에서 원본가)을 읽는 코드는 「파일 없음」으로 바로 드러난다

        Given: 티커 QQQ, 가격 기준
        When: price_path
        Then: 시세 폴더 아래 `QQQ_{기준}.csv`
        """
        # When
        path = price_path("QQQ", basis)

        # Then
        assert path == PRICES_DIR / name

    def test_prices_dir_is_storage_prices(self) -> None:
        """
        목적: 시세 폴더는 저장소 루트 기준 `storage/prices` 다 — 내보내기 · 매니페스트가 이 상대 경로로 파일을 가리킨다

        Given: 시세 폴더 상수
        When: 비교
        Then: Path("storage/prices")
        """
        # Then
        assert PRICES_DIR == Path("storage/prices")

    @pytest.mark.parametrize(
        ("ticker", "basis", "name"),
        [("^NDX", PriceBasis.RAW, "^NDX_raw.csv"), ("GC=F", PriceBasis.ADJUSTED, "GC=F_adjusted.csv")],
    )
    def test_special_characters_kept(self, ticker: str, basis: PriceBasis, name: str) -> None:
        """
        목적: 티커의 특수 문자는 파일 이름에 그대로 쓴다 — 바꾸면 티커와 파일을 오갈 규칙이 하나 더 생긴다

        Given: ^NDX · GC=F
        When: price_path
        Then: 특수 문자가 그대로인 이름
        """
        # When
        path = price_path(ticker, basis)

        # Then
        assert path.name == name

    def test_directory_argument(self, tmp_path: Path) -> None:
        """
        목적: 시세 폴더를 인자로 받는다 — 갱신 · 테스트가 저장소 밖 임시 폴더에 쓸 때 실경로를 건드리지 않는다

        Given: 임시 폴더
        When: price_path(..., prices_dir=임시 폴더)
        Then: 그 폴더 아래 같은 이름
        """
        # When
        path = price_path("SPY", PriceBasis.ADJUSTED, prices_dir=tmp_path)

        # Then
        assert path == tmp_path / "SPY_adjusted.csv"

    @pytest.mark.parametrize(
        ("name", "ticker", "basis"),
        [
            ("QQQ_synthetic.csv", "QQQ", PriceBasis.SYNTHETIC),
            ("^NDX_raw.csv", "^NDX", PriceBasis.RAW),
            ("GC=F_adjusted.csv", "GC=F", PriceBasis.ADJUSTED),
        ],
    )
    def test_parse_name_round_trips(self, name: str, ticker: str, basis: PriceBasis) -> None:
        """
        목적: 파일 이름에서 티커와 가격 기준을 되읽는다 — 매니페스트가 합성 파일의 종목을 이름으로 적는다

        Given: 시세 파일 이름
        When: parse_price_file_name
        Then: (티커, 가격 기준), price_path 로 다시 만들면 같은 이름
        """
        # When
        parsed = parse_price_file_name(name)

        # Then
        assert parsed == (ticker, basis)
        assert price_path(*parsed).name == name

    @pytest.mark.parametrize("name", ["QQQ_max.csv", "QQQ.csv", "_adjusted.csv", "QQQ_adjusted.txt"])
    def test_parse_name_outside_convention_raises(self, name: str) -> None:
        """
        목적: 이름 규칙(`{티커}_{raw|adjusted|synthetic}.csv`)에 맞지 않으면 멈춘다 — 옛 이름(`_max`)이 섞여 들어와도
              종목 · 기준을 지어내지 않는다

        Given: 옛 이름 · 기준 없는 이름 · 티커 없는 이름 · 확장자가 다른 이름
        When: parse_price_file_name
        Then: ValueError (「이름 규칙」)
        """
        # When & Then
        with pytest.raises(ValueError, match="이름 규칙"):
            parse_price_file_name(name)


class TestLoadPrices:
    """시세 CSV 읽기"""

    def test_normal_load(self, tmp_path: Path, sample_stock_df: pd.DataFrame) -> None:
        """
        목적: 올바른 CSV 를 읽으면 필수 열이 모두 있고 날짜가 datetime.date 로 오름차순이다

        Given: 올바른 스키마의 CSV 파일
        When: load_prices
        Then: 3행, 필수 열 모두, Date 는 date 타입, 오름차순
        """
        # Given
        csv_path = tmp_path / "AAPL_adjusted.csv"
        sample_stock_df.to_csv(csv_path, index=False)

        # When
        df = load_prices(csv_path)

        # Then
        assert len(df) == 3
        for col in ["Date", "Open", "High", "Low", "Close", "Volume"]:
            assert col in df.columns
        assert all(isinstance(d, date) for d in df["Date"])
        assert df["Date"].tolist() == sorted(df["Date"].tolist())

    def test_file_not_found(self, tmp_path: Path) -> None:
        """
        목적: 파일이 없으면 명확한 에러로 멈춘다

        Given: 존재하지 않는 파일 경로
        When: load_prices
        Then: FileNotFoundError (「찾을 수 없습니다」)
        """
        # When & Then
        with pytest.raises(FileNotFoundError, match="찾을 수 없습니다"):
            load_prices(tmp_path / "no_such_file.csv")

    def test_missing_required_columns(self, tmp_path: Path) -> None:
        """
        목적: 필수 열이 없으면 누락 열 이름과 함께 멈춘다

        Given: Close 열이 없는 CSV
        When: load_prices
        Then: ValueError (「필수 컬럼」 · 「Close」)
        """
        # Given
        incomplete_df = pd.DataFrame(
            {"Date": [date(2023, 1, 2)], "Open": [100.0], "High": [105.0], "Low": [99.0], "Volume": [1000000]}
        )
        csv_path = tmp_path / "incomplete.csv"
        incomplete_df.to_csv(csv_path, index=False)

        # When & Then
        with pytest.raises(ValueError, match="필수 컬럼.*Close"):
            load_prices(csv_path)

    def test_duplicate_dates_raise(self, tmp_path: Path) -> None:
        """
        목적: 같은 날짜가 두 번 나오면 고르지 않고 멈춘다 — 어느 행이 맞는지 알 수 없다

        Given: 2023-01-02 가 두 행(값이 다름)인 CSV
        When: load_prices
        Then: ValueError (「중복 날짜」와 그 날짜)
        """
        # Given
        dup_df = pd.DataFrame(
            {
                "Date": [date(2023, 1, 2), date(2023, 1, 2), date(2023, 1, 3)],
                "Open": [100.0, 999.0, 102.0],
                "High": [105.0, 999.0, 107.0],
                "Low": [99.0, 999.0, 101.0],
                "Close": [103.0, 999.0, 105.0],
                "Volume": [1000000, 9999999, 1200000],
            }
        )
        csv_path = tmp_path / "duplicate.csv"
        dup_df.to_csv(csv_path, index=False)

        # When & Then
        with pytest.raises(ValueError, match=r"중복 날짜.*2023, 1, 2"):
            load_prices(csv_path)

    @pytest.mark.parametrize(
        "col,bad_value,pattern",
        [("Close", np.nan, "결측치 발견"), ("Open", 0.0, "0 값 발견"), ("Low", -1.0, "음수 값 발견")],
        ids=["close_nan", "open_zero", "low_negative"],
    )
    def test_invalid_price_raises(
        self, tmp_path: Path, sample_stock_df: pd.DataFrame, col: str, bad_value: float, pattern: str
    ) -> None:
        """
        목적: 가격 열에 결측 · 0 · 음수가 있으면 읽을 때 멈춘다 — 메우지 않는다(보간 금지)

        Given: 가운데 행의 가격 한 칸만 잘못된 CSV
        When: load_prices
        Then: ValueError (어느 검사에 걸렸는지와 열 이름)
        """
        # Given
        bad_df = sample_stock_df.copy()
        bad_df.loc[1, col] = bad_value
        csv_path = tmp_path / "bad.csv"
        bad_df.to_csv(csv_path, index=False)

        # When & Then
        with pytest.raises(ValueError, match=f"{pattern} - 컬럼: {col}"):
            load_prices(csv_path)

    def test_zero_volume_allowed(self, tmp_path: Path, sample_stock_df: pd.DataFrame) -> None:
        """
        목적: 거래량 0 은 받는다 — 대용 · 합성 시세는 거래량이 0 이다

        Given: 거래량이 모두 0 인 CSV
        When: load_prices
        Then: 예외 없이 그대로 읽힌다
        """
        # Given
        zero_volume_df = sample_stock_df.copy()
        zero_volume_df["Volume"] = 0
        csv_path = tmp_path / "zero_volume.csv"
        zero_volume_df.to_csv(csv_path, index=False)

        # When
        df = load_prices(csv_path)

        # Then
        assert (df["Volume"] == 0).all()

    def test_date_sorting(self, tmp_path: Path) -> None:
        """
        목적: 날짜가 섞인 파일도 오름차순으로 읽는다

        Given: 날짜가 역순인 CSV
        When: load_prices
        Then: 오름차순
        """
        # Given
        reversed_df = pd.DataFrame(
            {
                "Date": [date(2023, 1, 4), date(2023, 1, 2), date(2023, 1, 3)],
                "Open": [102.0, 100.0, 101.0],
                "High": [107.0, 105.0, 106.0],
                "Low": [101.0, 99.0, 100.0],
                "Close": [105.0, 103.0, 104.0],
                "Volume": [1200000, 1000000, 1100000],
            }
        )
        csv_path = tmp_path / "reversed.csv"
        reversed_df.to_csv(csv_path, index=False)

        # When
        df = load_prices(csv_path)

        # Then
        assert df["Date"].tolist() == [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)]


class TestValidatePriceSeries:
    """시세 표 검사 — 중복 날짜 · 가격의 결측 · 0 · 음수 (지우거나 메우지 않는다)"""

    def test_valid_data_passes(self) -> None:
        """
        목적: 정상 시세는 통과한다

        Given: 결측 · 0 · 음수 · 중복 없는 시세
        When: validate_price_series
        Then: 예외 없음
        """
        # When & Then
        validate_price_series(_make_valid_df())

    @pytest.mark.parametrize(
        ("row", "col", "bad_value", "pattern"),
        [
            (1, COL_OPEN, np.nan, "결측치 발견"),
            (2, COL_CLOSE, 0.0, "0 값 발견"),
            (0, COL_HIGH, -1.0, "음수 값 발견"),
        ],
        ids=["null", "zero", "negative"],
    )
    def test_bad_price_detected(self, row: int, col: str, bad_value: float, pattern: str) -> None:
        """
        목적: 가격 한 칸이 결측 · 0 · 음수면 멈춘다

        Given: 한 칸만 잘못된 시세
        When: validate_price_series
        Then: ValueError (검사 이름)
        """
        # Given
        df = _make_valid_df()
        df.loc[row, col] = bad_value

        # When & Then
        with pytest.raises(ValueError, match=pattern):
            validate_price_series(df)

    def test_duplicate_dates_detected(self) -> None:
        """
        목적: 같은 날짜가 두 번 있으면 저장 전에 멈춘다 — 저장하면 그 파일을 읽는 모든 실행이 멈춘다

        Given: 둘째 행의 날짜를 첫 행과 같게 바꾼 시세
        When: validate_price_series
        Then: ValueError (「중복 날짜 발견」)
        """
        # Given
        df = _make_valid_df()
        df.loc[1, COL_DATE] = df.loc[0, COL_DATE]

        # When & Then
        with pytest.raises(ValueError, match="중복 날짜 발견"):
            validate_price_series(df)

    def test_extreme_daily_change_is_not_checked(self) -> None:
        """
        목적: 하루 급등락으로는 멈추지 않는다 — 급등락은 신규 일자의 벤치마크 대조가 맡고, 걸리면 허용 목록으로 넘긴다.
              저장 단계에서 ValueError 로 막으면 「멈춤 → 확인 → 다시 실행」 경로를 타지 못한다(결정 Q26)

        Given: 종가가 하루에 약 94% 오르는 시세 (103 → 200)
        When: validate_price_series
        Then: 예외 없음
        """
        # Given
        df = _make_valid_df()
        df.loc[1, COL_CLOSE] = 200.0

        # When & Then
        validate_price_series(df)

    def test_single_row_passes(self) -> None:
        """
        목적: 한 행짜리 시세도 검사를 통과한다 (경계)

        Given: 1행 시세
        When: validate_price_series
        Then: 예외 없음
        """
        # When & Then
        validate_price_series(_make_valid_df(rows=1))


class TestSavePrices:
    """시세 저장 — 받은 시세 · 합성 · 국내 수정주가가 같은 함수로 저장한다"""

    def test_rounds_prices_and_saves(self, tmp_path: Path) -> None:
        """
        목적: 가격 열을 6자리로 반올림해 저장하고 원본은 바꾸지 않는다 (결정 Q6 — 전역 4자리 규칙의 예외)

        Given: 소수점이 긴 가격의 정상 시세
        When: save_prices (상위 폴더가 없는 경로)
        Then: 폴더를 만들어 저장하고, 저장된 가격은 6자리 · 원본 DataFrame 은 그대로
        """
        # Given
        df = _make_valid_df(rows=2)
        df.loc[0, COL_OPEN] = 100.1234567
        path = tmp_path / "sub" / "TEST_adjusted.csv"

        # When
        save_prices(df, path)

        # Then
        saved = pd.read_csv(path)
        assert saved[COL_OPEN].iloc[0] == pytest.approx(100.123457, abs=1e-9)
        assert df.loc[0, COL_OPEN] == 100.1234567

    def test_missing_price_is_not_saved(self, tmp_path: Path) -> None:
        """
        목적: 가격 결측이 있으면 저장하지 않고 멈춘다

        Given: 종가 하나가 결측인 시세
        When: save_prices
        Then: ValueError, 파일이 생기지 않음
        """
        # Given
        df = _make_valid_df()
        df.loc[2, COL_CLOSE] = np.nan
        path = tmp_path / "TEST_adjusted.csv"

        # When & Then
        with pytest.raises(ValueError, match="결측치 발견"):
            save_prices(df, path)
        assert not path.exists()

    def test_price_spike_is_saved(self, tmp_path: Path) -> None:
        """
        목적: 하루 급등락이 있어도 저장한다 — 3배 합성은 하루 50% 를 넘는 날이 정상이고(UPRO 합성 1987-10-19 −61.47%),
              실물의 급등락은 저장 전 판정이 멈춰 사람이 보게 한다(결정 Q26)

        Given: 하루 약 94% 오르는 시세
        When: save_prices
        Then: 저장된다
        """
        # Given
        df = _make_valid_df()
        df.loc[1, COL_CLOSE] = 200.0
        path = tmp_path / "TEST_adjusted.csv"

        # When
        save_prices(df, path)

        # Then
        assert pd.read_csv(path)[COL_CLOSE].iloc[1] == 200.0
