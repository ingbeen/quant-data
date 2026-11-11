"""시세 파일 — 이름(가격 기준) · 읽기 · 검사 · 저장

시세 파일 이름은 `{티커}_{가격 기준}.csv` 다(결정 Q10 · Q33). 같은 이름이 저장소마다 다른 기준을 뜻하면 원본가를
수정주가로 읽어도 에러가 나지 않아, 기준을 이름에 넣고 옛 이름(`_max`)은 받지 않는다.
검사는 중복 날짜 · 가격의 결측 · 0 · 음수뿐이고 지우거나 메우지 않는다. 하루 급등락은 여기서 보지 않는다 —
새로 붙는 날의 판정(new_days)이 멈추고 사람이 확인한다(결정 Q26).
"""

import re
from enum import Enum
from pathlib import Path
from typing import Final

import pandas as pd

from quant_data.constants import COL_DATE, PRICE_COLUMNS, PRICES_DIR, REQUIRED_COLUMNS, ROUND_INPUT_PRICE
from quant_data.logger import get_logger

logger = get_logger(__name__)


class PriceBasis(Enum):
    """가격 기준 — 파일 이름의 끝."""

    RAW = "raw"  # 원본가 (야후 원시 가격 · KRX 원본가 · 배당이 빠진 가격지수)
    ADJUSTED = "adjusted"  # 수정주가 (야후 C-1 · 국내 C-2)
    SYNTHETIC = "synthetic"  # 합성 (상장 전 대용 · 시뮬레이션 + 상장 뒤 실물 수정주가)


_FILE_SUFFIX: Final = ".csv"
_FILE_NAME_PATTERN: Final = re.compile(rf"(.+)_({'|'.join(basis.value for basis in PriceBasis)})\.csv")


def price_path(ticker: str, basis: PriceBasis, prices_dir: Path = PRICES_DIR) -> Path:
    """시세 파일 경로 `{prices_dir}/{티커}_{기준}.csv` — 티커의 특수 문자(^ · =)는 그대로 쓴다."""
    return prices_dir / f"{ticker}_{basis.value}{_FILE_SUFFIX}"


def parse_price_file_name(name: str) -> tuple[str, PriceBasis]:
    """
    시세 파일 이름에서 (티커, 가격 기준)을 되읽는다.

    Raises:
        ValueError: `{티커}_{raw|adjusted|synthetic}.csv` 가 아닐 때
    """
    match = _FILE_NAME_PATTERN.fullmatch(name)
    if match is None:
        bases = " · ".join(basis.value for basis in PriceBasis)
        raise ValueError(f"시세 파일 이름 규칙(티커_기준.csv, 기준은 {bases})에 맞지 않습니다: {name}")
    return match.group(1), PriceBasis(match.group(2))


def load_prices(path: Path) -> pd.DataFrame:
    """
    시세 CSV 를 읽는다 — 날짜를 date 로 파싱해 오름차순으로 두고, 검사(validate_price_series)에 걸리면 멈춘다.

    필수 열 밖의 열(국내 원본가의 공식 등락률 등)은 그대로 둔다.

    Raises:
        FileNotFoundError: 파일이 없을 때
        ValueError: 필수 열이 없을 때, validate_price_series 와 같은 경우
    """
    if not path.exists():
        raise FileNotFoundError(f"시세 파일을 찾을 수 없습니다: {path}")

    df = pd.read_csv(path, parse_dates=[COL_DATE])
    missing_columns = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_columns:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {sorted(missing_columns)} ({path})")

    df[COL_DATE] = pd.to_datetime(df[COL_DATE]).dt.date
    df = df.sort_values(COL_DATE).reset_index(drop=True)
    validate_price_series(df)
    logger.debug(f"시세 읽음: {path} ({len(df):,}행, {df[COL_DATE].min()} ~ {df[COL_DATE].max()})")
    return df


def validate_price_series(df: pd.DataFrame) -> None:
    """시세 표에 중복 날짜나 가격 열의 결측 · 0 · 음수가 있으면 ValueError — 지우거나 메우지 않는다.

    거래량은 보지 않는다(대용 · 합성 시세는 거래량이 0 이다). 하루 급등락도 보지 않는다(결정 Q26).

    Raises:
        ValueError: 중복 날짜(날짜 포함) · 결측 · 0 · 음수(열 · 인덱스 · 날짜 포함)가 있을 때
    """
    duplicate_dates = df.loc[df.duplicated(subset=[COL_DATE]), COL_DATE].unique().tolist()
    if duplicate_dates:
        ellipsis = "..." if len(duplicate_dates) > 5 else ""
        raise ValueError(f"중복 날짜 발견 - {len(duplicate_dates)}개, 날짜: {duplicate_dates[:5]}{ellipsis}")

    for label, bad in (
        ("결측치 발견", lambda values: values.isna()),
        ("0 값 발견", lambda values: values == 0),
        ("음수 값 발견", lambda values: values < 0),
    ):
        for col in PRICE_COLUMNS:
            mask = bad(df[col])
            if mask.any():
                indices = df.index[mask].tolist()
                dates = df[COL_DATE][mask].tolist()
                ellipsis = "..." if len(indices) > 5 else ""
                raise ValueError(f"{label} - 컬럼: {col}, 인덱스: {indices[:5]}{ellipsis}, 날짜: {dates[:5]}{ellipsis}")


def round_prices(df: pd.DataFrame) -> pd.DataFrame:
    """가격 열을 시세 파일 자릿수(ROUND_INPUT_PRICE)로 반올림한 복사본 — 저장한 뒤 다시 읽은 표와 같은 값이다."""
    rounded = df.copy()
    rounded[PRICE_COLUMNS] = rounded[PRICE_COLUMNS].round(ROUND_INPUT_PRICE)
    return rounded


def save_prices(df: pd.DataFrame, path: Path) -> None:
    """
    시세 표를 가격 반올림 → 검사 → 저장 순서로 저장한다. 검사에 걸리면 파일을 쓰지 않는다.

    Args:
        df: 저장할 시세 (원본은 바꾸지 않는다)
        path: 저장 경로 (상위 폴더가 없으면 만든다)

    Raises:
        ValueError: validate_price_series 와 같은 경우
    """
    rounded = round_prices(df)
    validate_price_series(rounded)
    path.parent.mkdir(parents=True, exist_ok=True)
    rounded.to_csv(path, index=False)
    logger.debug(f"저장: {path} ({len(rounded):,}행, {rounded[COL_DATE].min()} ~ {rounded[COL_DATE].max()})")
