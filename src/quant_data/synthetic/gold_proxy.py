"""금 대용 시세 유틸리티

GLD 상장 전 구간을 채우는 금값 사슬 — Perth Mint 하루 평균 금값과 FRED 호주달러 환율을 받아 저장하고,
미국 거래일 달력에 붙여 「호주달러 × 환율 → Perth 달러 → 금 선물」로 잇는다.
고리 선택 · 날짜 규칙의 근거는 docs/research/합성_시세_연장.md 결정 6 · 6.4.
"""

import csv
import io
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final
from urllib.request import Request, urlopen

import pandas as pd

from quant_data.constants import (
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LOW,
    COL_OPEN,
    COL_VOLUME,
    FRED_DATE_COLUMN,
    REQUIRED_COLUMNS,
)
from quant_data.logger import get_logger
from quant_data.synthetic.proxy_series import require_rows_from_seam_equal_actual, splice_proxy

logger = get_logger(__name__)

# 1975 ~ 2015 에서 끝난 정적 보관 파일 — 호주달러 1975-01-02, 달러 1991-06-21 부터
PERTH_MINT_GOLD_CSV_URL: Final = (
    "https://www.perthmint.com/globalassets/assets/metal-prices---csvs/historical-metals-page/"
    "csvs-archived-data-1968-2015/historic-daily-gold-prices-1975-2015.csv"
)
FRED_AUD_USD_SERIES: Final = "DEXUSAL"  # 호주달러 1 = 달러, 뉴욕 정오
FRED_AUD_USD_CSV_URL: Final = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={FRED_AUD_USD_SERIES}"
# Perth Mint 는 파이썬 기본 UA(Python-urllib)를 403 으로 막고, FRED 는 이 UA 를 응답 없이 붙잡음 → Perth 요청에만 실음
USER_AGENT: Final = "qbt-data-downloader/1.0"
_TIMEOUT_SECONDS: Final = 60

# 저장 형식의 열
COL_SOURCE_DATE: Final = "DATE"
COL_SOURCE_VALUE: Final = "VALUE"
COL_AUD_BID: Final = "AUD_BID"
COL_AUD_ASK: Final = "AUD_ASK"
COL_USD_BID: Final = "USD_BID"
COL_USD_ASK: Final = "USD_ASK"
PERTH_COLUMNS: Final = (COL_SOURCE_DATE, COL_AUD_BID, COL_AUD_ASK, COL_USD_BID, COL_USD_ASK)
DAILY_VALUE_COLUMNS: Final = (COL_SOURCE_DATE, COL_SOURCE_VALUE)
_PRICE_PAIRS: Final = ((COL_AUD_BID, COL_AUD_ASK), (COL_USD_BID, COL_USD_ASK))

# Perth CSV 머리 다섯 줄의 첫 칸 — 다르면 형식이 바뀐 것
_PERTH_HEADER_LABELS: Final = ("Market", "Metal/Currency", "Priced In", "Price Type", "Summary")
# (통화, 가격 종류) → 저장 열 — 머리의 Metal 이 Gold, Summary 가 Average 인 열만
_PERTH_AVERAGE_COLUMNS: Final = {
    ("AUD", "Bid"): COL_AUD_BID,
    ("AUD", "Ask"): COL_AUD_ASK,
    ("USD", "Bid"): COL_USD_BID,
    ("USD", "Ask"): COL_USD_ASK,
}
_PERTH_DATE_PATTERN: Final = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2})")
# 보관 파일의 날짜는 1968 ~ 2022 → 두 자리 해 68 이상만 1900년대
_PERTH_FIRST_YEAR_OF_1900S: Final = 68
_ISO_DATE_PATTERN: Final = r"\d{4}-\d{2}-\d{2}"
_FRED_MISSING_VALUES: Final = ("", ".")


@dataclass(frozen=True)
class GoldProxy:
    """미국 거래일에 붙인 금 사슬. 고리 둘은 이어 붙이기 전 그대로(검증 ① 용), chain 이 GLD 의 대용이다."""

    aud_in_usd: pd.DataFrame
    perth_usd: pd.DataFrame
    chain: pd.DataFrame


def _parse_positive_number(text: str, where: str) -> float | None:
    """천 단위 쉼표를 지운 양수. 빈 칸은 None."""
    cleaned = text.strip().replace(",", "")
    if cleaned == "":
        return None
    try:
        value = float(cleaned)
    except ValueError:
        raise ValueError(f"{where}: 숫자가 아닙니다 ({text!r}) — 메우지 않습니다") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{where}: 0 이하이거나 유한하지 않은 값입니다 ({text!r})")
    return value


def _require_increasing_source_dates(df: pd.DataFrame, name: str) -> None:
    dates = df[COL_SOURCE_DATE]
    if not (dates.is_monotonic_increasing and dates.is_unique):
        raise ValueError(f"{name} 의 날짜가 중복 없는 오름차순이 아닙니다")


def _validate_perth_table(df: pd.DataFrame) -> None:
    """저장 형식 Perth 표의 검사 — 받을 때와 읽을 때 같이 쓴다.

    Raises:
        ValueError: 행이 없을 때, 날짜가 중복 없는 오름차순이 아닐 때, 값이 0 이하일 때, bid · ask 중 하나만 있을 때,
            값이 하나도 없는 행이 있을 때
    """
    name = "Perth Mint 금값"
    if df.empty:
        raise ValueError(f"{name} 에 값이 비어 있습니다")
    _require_increasing_source_dates(df, name)
    values = df[list(PERTH_COLUMNS[1:])]
    non_positive = df.loc[(values <= 0).any(axis=1), COL_SOURCE_DATE].tolist()
    if non_positive:
        raise ValueError(f"{name} 에 0 이하 값이 있는 날: {non_positive[:5]}")
    for bid, ask in _PRICE_PAIRS:
        half = df.loc[df[bid].isna() != df[ask].isna(), COL_SOURCE_DATE].tolist()
        if half:
            raise ValueError(f"{name} 에 {bid} · {ask} 중 하나만 있는 날: {half[:5]} — 메우지 않습니다")
    empty = df.loc[values.isna().all(axis=1), COL_SOURCE_DATE].tolist()
    if empty:
        raise ValueError(f"{name} 에 값이 하나도 없는 행: {empty[:5]}")


def _validate_daily_values(df: pd.DataFrame, name: str) -> None:
    """(날짜, 값) 표의 검사 — 받을 때와 읽을 때 같이 쓴다.

    Raises:
        ValueError: 행이 없을 때, 날짜가 중복 없는 오름차순이 아닐 때, 값이 비었거나 0 이하일 때
    """
    if df.empty:
        raise ValueError(f"{name} 에 값이 비어 있습니다")
    _require_increasing_source_dates(df, name)
    bad = df.loc[~(df[COL_SOURCE_VALUE] > 0), COL_SOURCE_DATE].tolist()
    if bad:
        raise ValueError(f"{name} 에 비었거나 0 이하인 값이 있는 날: {bad[:5]}")


def _parse_perth_date(text: str, line_no: int) -> date:
    match = _PERTH_DATE_PATTERN.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"Perth Mint 금값 {line_no}행의 날짜가 d/mm/yy 가 아닙니다: {text!r}")
    day, month, two_digit_year = (int(group) for group in match.groups())
    century = 1900 if two_digit_year >= _PERTH_FIRST_YEAR_OF_1900S else 2000
    try:
        return date(century + two_digit_year, month, day)
    except ValueError:
        raise ValueError(f"Perth Mint 금값 {line_no}행의 날짜가 없는 날입니다: {text!r}") from None


def _find_perth_average_columns(header: list[list[str]]) -> dict[str, int]:
    """머리 다섯 줄에서 Gold · Average 의 호주달러 · 달러 bid · ask 열 위치를 찾는다."""
    labels = tuple(row[0].strip() if row else "" for row in header)
    if labels != _PERTH_HEADER_LABELS:
        raise ValueError(
            f"Perth Mint 금값 CSV 의 머리 첫 칸이 {list(_PERTH_HEADER_LABELS)} 가 아닙니다: {list(labels)} — 형식이 바뀌었는지 확인하세요"
        )

    def cell(row: int, col: int) -> str:
        return header[row][col].strip() if col < len(header[row]) else ""

    found: dict[str, int] = {}
    for col in range(1, max(len(row) for row in header)):
        if cell(1, col) != "Gold" or cell(4, col) != "Average":
            continue
        target = _PERTH_AVERAGE_COLUMNS.get((cell(2, col), cell(3, col)))
        if target is None:
            continue
        if target in found:
            raise ValueError(f"Perth Mint 금값 CSV 에 {target} 열이 둘 이상입니다 — 형식이 바뀌었는지 확인하세요")
        found[target] = col
    missing = [target for target in _PERTH_AVERAGE_COLUMNS.values() if target not in found]
    if missing:
        raise ValueError(f"Perth Mint 금값 CSV 에 Gold · Average 열 {missing} 이 없습니다 — 형식이 바뀌었는지 확인하세요")
    return found


def parse_perth_mint_gold_csv(csv_text: str) -> pd.DataFrame:
    """
    Perth Mint 금값 보관 CSV 를 저장 형식으로 바꾼다 — 받은 숫자 그대로, 값이 있는 날만.

    Args:
        csv_text: 보관 CSV 본문 (머리 다섯 줄 뒤 `d/mm/yy` 날짜 줄)

    Returns:
        PERTH_COLUMNS 표 (DATE: date — 호주 날짜, 나머지: float, 그날 그 통화 값이 없으면 NaN)

    Raises:
        ValueError: 머리가 다를 때, 날짜 · 숫자가 형식에 맞지 않을 때, _validate_perth_table 과 같은 경우
    """
    rows = list(csv.reader(io.StringIO(csv_text)))
    header_size = len(_PERTH_HEADER_LABELS)
    if len(rows) < header_size:
        raise ValueError(f"Perth Mint 금값 CSV 의 머리가 {header_size}줄보다 짧습니다")
    columns = _find_perth_average_columns(rows[:header_size])

    records: list[dict[str, object]] = []
    for line_no, row in enumerate(rows[header_size:], start=header_size + 1):
        if not any(cell.strip() for cell in row):
            continue
        day = _parse_perth_date(row[0], line_no)
        values = {
            target: _parse_positive_number(row[col] if col < len(row) else "", f"Perth Mint 금값 {line_no}행 {target}")
            for target, col in columns.items()
        }
        if all(value is None for value in values.values()):
            continue
        records.append({COL_SOURCE_DATE: day, **values})

    df = pd.DataFrame(records, columns=list(PERTH_COLUMNS)).astype({col: float for col in PERTH_COLUMNS[1:]})
    _validate_perth_table(df)
    return df


def parse_fred_daily_csv(csv_text: str, series_id: str) -> pd.DataFrame:
    """
    FRED 일별 CSV 를 (날짜, 값) 표로 바꾼다. 값이 빈 · 「.」 인 날(은행 휴일)은 행이 없다 — 메우지 않는다.

    Args:
        csv_text: FRED fredgraph.csv 본문 (열 observation_date · 시리즈 이름)
        series_id: FRED 시리즈 이름 (예: DEXUSAL)

    Returns:
        DAILY_VALUE_COLUMNS 표 (DATE: date, VALUE: float)

    Raises:
        ValueError: 머리가 다를 때, 날짜가 YYYY-MM-DD 가 아닐 때, 값이 숫자가 아니거나 0 이하일 때, _validate_daily_values 와 같은 경우
    """
    raw = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    expected = (FRED_DATE_COLUMN, series_id)
    if tuple(raw.columns) != expected:
        raise ValueError(
            f"FRED {series_id} CSV 의 머리가 {list(expected)} 가 아닙니다: {list(raw.columns)} — FRED 형식이 바뀌었는지 확인하세요"
        )

    dates = raw[FRED_DATE_COLUMN].str.strip()
    bad_dates = dates[~dates.str.fullmatch(_ISO_DATE_PATTERN)].tolist()
    if bad_dates:
        raise ValueError(f"FRED {series_id} 의 날짜가 YYYY-MM-DD 가 아닙니다: {bad_dates[:5]}")
    texts = raw[series_id].str.strip()
    observed = ~texts.isin(_FRED_MISSING_VALUES)
    values = [
        _parse_positive_number(text, f"FRED {series_id} {day}")
        for day, text in zip(dates[observed], texts[observed], strict=True)
    ]

    df = pd.DataFrame(
        {
            COL_SOURCE_DATE: pd.to_datetime(dates[observed], format="%Y-%m-%d").dt.date.tolist(),
            COL_SOURCE_VALUE: pd.Series(values, dtype=float).tolist(),
        },
        columns=list(DAILY_VALUE_COLUMNS),
    ).astype({COL_SOURCE_VALUE: float})
    _validate_daily_values(df, f"FRED {series_id}")
    return df


def _read_perth_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={COL_SOURCE_DATE: str})
    if tuple(df.columns) != PERTH_COLUMNS:
        raise ValueError(f"{path} 의 열이 {list(PERTH_COLUMNS)} 가 아닙니다: {list(df.columns)}")
    df[COL_SOURCE_DATE] = pd.to_datetime(df[COL_SOURCE_DATE], format="%Y-%m-%d").dt.date
    df = df.astype({col: float for col in PERTH_COLUMNS[1:]})
    _validate_perth_table(df)
    return df


def _read_daily_values_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={COL_SOURCE_DATE: str})
    if tuple(df.columns) != DAILY_VALUE_COLUMNS:
        raise ValueError(f"{path} 의 열이 {list(DAILY_VALUE_COLUMNS)} 가 아닙니다: {list(df.columns)}")
    df[COL_SOURCE_DATE] = pd.to_datetime(df[COL_SOURCE_DATE], format="%Y-%m-%d").dt.date
    df = df.astype({COL_SOURCE_VALUE: float})
    _validate_daily_values(df, str(path))
    return df


def load_gold_proxy_sources(perth_path: Path, aud_usd_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    저장된 Perth Mint 금값 · 호주달러 환율 파일을 읽는다.

    Returns:
        (PERTH_COLUMNS 표, DAILY_VALUE_COLUMNS 표) — parse_perth_mint_gold_csv · parse_fred_daily_csv 와 같은 모양

    Raises:
        FileNotFoundError: 파일이 없을 때
        ValueError: 열이 다를 때, _validate_perth_table · _validate_daily_values 와 같은 경우
    """
    return _read_perth_file(perth_path), _read_daily_values_file(aud_usd_path)


def save_gold_proxy_sources(perth_csv_text: str, aud_usd_csv_text: str, perth_path: Path, aud_usd_path: Path) -> None:
    """
    받은 두 원본을 검사한 뒤 저장 형식으로 쓴다 — 둘 다 검사를 통과해야 쓰고, 걸리면 기존 파일은 그대로다.

    Raises:
        ValueError: parse_perth_mint_gold_csv · parse_fred_daily_csv 와 같은 경우, 받은 표가 기존 파일의 값 칸(날짜 · 열)을 다 덮지 못할 때
    """
    perth_df = parse_perth_mint_gold_csv(perth_csv_text)
    aud_usd_df = parse_fred_daily_csv(aud_usd_csv_text, FRED_AUD_USD_SERIES)

    # 잘린 응답이 앞 기간을 지우면 금 사슬의 고리가 다음 생성에서 조용히 바뀜 → 날뿐 아니라 값 칸(달러 열만 빈 응답)까지 쓰기 전에 막음
    for name, new_df, path, reader in (
        ("Perth Mint 금값", perth_df, perth_path, _read_perth_file),
        (f"FRED {FRED_AUD_USD_SERIES}", aud_usd_df, aud_usd_path, _read_daily_values_file),
    ):
        if not path.exists():
            continue
        lost = sorted(_observed_cells(reader(path)) - _observed_cells(new_df))
        if lost:
            raise ValueError(
                f"받은 {name} 이 기존 파일 {path} 의 값 {len(lost)}칸을 덮지 못합니다(예: {lost[:5]}) — " "응답이 잘렸는지 확인하세요. 기존 파일은 그대로 둡니다"
            )

    for df, path in ((perth_df, perth_path), (aud_usd_df, aud_usd_path)):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.debug(
            f"금 대용 원본 저장: {path} ({len(df):,}행, {df[COL_SOURCE_DATE].iloc[0]} ~ {df[COL_SOURCE_DATE].iloc[-1]})"
        )


def _observed_cells(df: pd.DataFrame) -> set[tuple[date, str]]:
    """값이 있는 (날짜, 열) 칸."""
    value_columns = [col for col in df.columns if col != COL_SOURCE_DATE]
    cells = df.melt(id_vars=[COL_SOURCE_DATE], value_vars=value_columns).dropna()
    return set(zip(cells[COL_SOURCE_DATE], cells["variable"], strict=True))


def _fetch_text(url: str, user_agent: str | None) -> str:
    """user_agent 가 None 이면 파이썬 기본 UA 로 받는다."""
    headers = {"User-Agent": user_agent} if user_agent is not None else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8-sig")


def download_gold_proxy_sources(perth_path: Path, aud_usd_path: Path) -> None:
    """
    Perth Mint 금값 보관 CSV 와 FRED 호주달러 환율 전체 기간을 받아 저장한다 (save_gold_proxy_sources).

    Raises:
        ValueError: save_gold_proxy_sources 와 같은 경우
        urllib.error.URLError: 받지 못했을 때
    """
    save_gold_proxy_sources(
        _fetch_text(PERTH_MINT_GOLD_CSV_URL, USER_AGENT),
        _fetch_text(FRED_AUD_USD_CSV_URL, None),
        perth_path,
        aud_usd_path,
    )


def _source_series(dates: pd.Series, values: pd.Series) -> pd.Series:
    """원본 날짜(date)로 색인한 값 — 값이 없는 날은 뺀다."""
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(pd.to_datetime(dates)))
    return series.dropna()


def _value_from_next_business_day(series: pd.Series, us_index: pd.DatetimeIndex) -> pd.Series:
    """미국 날짜 d 에 원본의 d + 1영업일 값 — 그날 값이 없으면 NaN (메우지 않는다)."""
    looked_up = series.reindex(us_index + pd.offsets.BDay(1))
    looked_up.index = us_index
    return looked_up


def _one_value_stock_frame(values: pd.Series) -> pd.DataFrame:
    """하루 한 값 시세 — 시가 · 고가 · 저가 · 종가 = 그 값, 거래량 0. 값이 없는 날은 행이 없다."""
    observed = values.dropna()
    return pd.DataFrame(
        {
            COL_DATE: pd.DatetimeIndex(observed.index).date.tolist(),
            COL_OPEN: observed.to_numpy(),
            COL_HIGH: observed.to_numpy(),
            COL_LOW: observed.to_numpy(),
            COL_CLOSE: observed.to_numpy(),
            COL_VOLUME: 0,
        },
        columns=REQUIRED_COLUMNS,
    )


def build_gold_proxy(
    perth_df: pd.DataFrame,
    aud_usd_df: pd.DataFrame,
    futures_df: pd.DataFrame,
    us_dates: Sequence[date],
) -> GoldProxy:
    """
    금 사슬을 미국 거래일에 만든다 — 호주달러 × 환율 → Perth 달러 → 금 선물.

    미국 날짜 d 에 Perth 의 호주 d + 1영업일 값을 붙이고, 호주달러 값에는 미국 d 의 환율을 곱한다(근거: 결정 6 · 연구 문서 6.4).
    이음매는 뒤 고리의 첫 미국 날짜이고 그날부터 뒤 고리 행 그대로다 — 앞 고리는 비율만 맞춘다.

    Args:
        perth_df: parse_perth_mint_gold_csv · load_gold_proxy_sources 의 Perth 표 (호주 날짜)
        aud_usd_df: 호주달러 1 = 달러 (DAILY_VALUE_COLUMNS, 미국 날짜)
        futures_df: 금 선물 시세 (load_stock_data 모양) — 미국 달력 밖 날은 빼고, 종가만 하루 한 값으로 쓴다
        us_dates: 미국 거래일 달력 (중복 없는 오름차순)

    Returns:
        GoldProxy — 값이 없는 날은 행이 없다 (메우지 않는다)

    Raises:
        ValueError: 달력이 중복 없는 오름차순이 아닐 때, 이음매 날이 앞 고리에 없을 때 · 앞 고리에 이음매 앞 행이 없을 때(splice_proxy)
        RuntimeError: 이어 붙인 결과의 이음매 뒤 행이 뒤 고리와 다를 때 (내부 불변조건 위반)
    """
    us_index = pd.DatetimeIndex(pd.to_datetime(list(us_dates)))
    if not (us_index.is_monotonic_increasing and us_index.is_unique):
        raise ValueError("미국 거래일 달력의 날짜가 중복 없는 오름차순이 아닙니다")

    perth_dates = perth_df[COL_SOURCE_DATE]
    aud_mid = _source_series(perth_dates, (perth_df[COL_AUD_BID] + perth_df[COL_AUD_ASK]) / 2)
    usd_mid = _source_series(perth_dates, (perth_df[COL_USD_BID] + perth_df[COL_USD_ASK]) / 2)
    aud_usd = _source_series(aud_usd_df[COL_SOURCE_DATE], aud_usd_df[COL_SOURCE_VALUE])

    aud_in_usd = _one_value_stock_frame(_value_from_next_business_day(aud_mid, us_index) * aud_usd.reindex(us_index))
    perth_usd = _one_value_stock_frame(_value_from_next_business_day(usd_mid, us_index))
    # 금 선물의 시가 · 고가 · 저가는 미국 주식 장의 봉이 아니고 종가가 봉 밖인 날도 있음 → 종가 하나로 (연구 문서 6.10)
    futures_close = _source_series(futures_df[COL_DATE], futures_df[COL_CLOSE])
    futures = _one_value_stock_frame(futures_close[futures_close.index.isin(us_index)])

    before_futures = splice_proxy(aud_in_usd, perth_usd)
    require_rows_from_seam_equal_actual(before_futures, perth_usd)
    chain = splice_proxy(before_futures, futures)
    require_rows_from_seam_equal_actual(chain, futures)
    logger.debug(
        f"금 사슬: 호주달러 × 환율 {aud_in_usd[COL_DATE].iloc[0]} ~, Perth 달러 {perth_usd[COL_DATE].iloc[0]} ~, "
        f"금 선물 {futures[COL_DATE].iloc[0]} ~ ({len(chain):,}행)"
    )
    return GoldProxy(aud_in_usd=aud_in_usd, perth_usd=perth_usd, chain=chain)
