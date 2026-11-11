"""야후 받기 — 한 응답에서 원본가 · 수정주가(C-1) · 배당 · 분할 기록, 받을 마지막 날

`auto_adjust=False` 로 받아 수정 가격을 yfinance 와 같은 식으로 직접 만든다 — 배당 · 분할 기록과 원시 종가를 같은
응답에서 얻어야 다시 받은 시세의 변화를 기록과 맞춰 볼 수 있다. 결과를 좌우하는 인자는 기본값에 맡기지 않는다:
auto_adjust 의 기본값은 True 라 빠뜨리면 수정주가가 원본가 자리에 조용히 들어가고, raise_errors 가 어긋나면
조회 실패가 빈 결과로 돌아온다. 파일은 쓰지 않는다 — 판정 · 쓰기는 update 가 한다.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yfinance as yf

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, REQUIRED_COLUMNS
from quant_data.logger import get_logger
from quant_data.revision import PriceEvents

logger = get_logger(__name__)

YFINANCE_VERSION: Final = yf.__version__
# history(auto_adjust=False) 의 열
COL_ADJ_CLOSE: Final = "Adj Close"
COL_DIVIDENDS: Final = "Dividends"
COL_STOCK_SPLITS: Final = "Stock Splits"

# 받을 마지막 날의 기본 — 한국 날짜 D 의 0시에도 뉴욕 D−1 장이 열려 있을 수 있음 → 시각을 따지지 않고 늘 마감된 D−2 까지
EXCLUDED_RECENT_DAYS: Final = 2
NEW_YORK_TIMEZONE: Final = "America/New_York"
# 받는 종목 모두의 그날 봉이 끝나는 시각 — 주식은 16:00 마감, 금 선물(GC=F)은 17:00 마감 뒤 18:00 에 다음 거래 시작
NEW_YORK_DAY_END: Final = time(18, 0)


@dataclass(frozen=True)
class YahooResponse:
    """한 번의 응답 — 기준일로 자르기 전 전체. raw 는 원시 가격, adjusted 는 C-1, 둘 다 REQUIRED_COLUMNS."""

    raw: pd.DataFrame
    adjusted: pd.DataFrame
    events: PriceEvents


def resolve_cutoff_date(end_date: date | None, now: datetime) -> date:
    """
    받을 마지막 날.

    Args:
        end_date: 받을 마지막 날(포함). None 이면 오늘에서 EXCLUDED_RECENT_DAYS 를 뺀 날
        now: 지금 시각 (시간대 포함 — 그 시간대의 날짜를 오늘로 본다)

    Returns:
        end_date 가 있으면 그날과, 뉴욕에서 그날 봉이 다 끝난 마지막 날(NEW_YORK_DAY_END) 중 이른 날

    Raises:
        ValueError: now 에 시간대가 없을 때, end_date 가 오늘보다 뒤일 때
        ZoneInfoNotFoundError: end_date 가 있는데 뉴욕 시간대 자료가 없을 때
    """
    if now.tzinfo is None:
        raise ValueError("지금 시각에 시간대가 없습니다 — 뉴욕에서 그날 봉이 끝났는지 가를 수 없습니다")
    today = now.date()
    if end_date is None:
        return today - timedelta(days=EXCLUDED_RECENT_DAYS)
    if end_date > today:
        raise ValueError(f"받을 마지막 날 {end_date} 가 오늘({today})보다 뒤입니다 — 오늘이나 그 이전 날짜를 주세요")

    new_york_now = now.astimezone(_new_york_zone())
    closed = new_york_now.date() if new_york_now.time() >= NEW_YORK_DAY_END else new_york_now.date() - timedelta(days=1)
    if closed < end_date:
        logger.debug(f"뉴욕에서 그날 봉이 끝나기({NEW_YORK_DAY_END:%H:%M}) 전인 날은 빼고 {closed} 까지 받습니다 (요청 {end_date})")
    return min(end_date, closed)


def _new_york_zone() -> ZoneInfo:
    try:
        return ZoneInfo(NEW_YORK_TIMEZONE)
    except ZoneInfoNotFoundError:
        raise ZoneInfoNotFoundError(
            f"뉴욕 시간대 자료({NEW_YORK_TIMEZONE})가 없습니다 — 운영체제의 tzdata 를 설치하거나 " f"`poetry add tzdata` 로 넣은 뒤 다시 실행하세요"
        ) from None


def adjust_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance auto_adjust 와 같은 수정 가격(C-1) — 시가 · 고가 · 저가 × (수정 종가 ÷ 원시 종가), 종가 = 수정 종가, 거래량 그대로.

    Args:
        raw: history(auto_adjust=False) 를 날짜 열로 편 표 (COL_DATE · 원시 가격 · COL_ADJ_CLOSE · COL_VOLUME)

    Returns:
        REQUIRED_COLUMNS 표
    """
    ratio = (raw[COL_ADJ_CLOSE] / raw[COL_CLOSE]).to_numpy()
    adjusted = pd.DataFrame(
        {
            COL_DATE: raw[COL_DATE],
            COL_OPEN: raw[COL_OPEN] * ratio,
            COL_HIGH: raw[COL_HIGH] * ratio,
            COL_LOW: raw[COL_LOW] * ratio,
            COL_CLOSE: raw[COL_ADJ_CLOSE],
            COL_VOLUME: raw[COL_VOLUME],
        }
    )
    return adjusted[REQUIRED_COLUMNS]


def fetch_yahoo(ticker: str) -> YahooResponse:
    """
    전체 기간의 원시 시세 · 수정 종가 · 배당 · 분할을 한 번에 받는다. 기준일로 자르지 않는다 — 기존 끝날을 아는
    update 가 자른다.

    Raises:
        ValueError: 데이터가 없을 때, 응답에 수정 종가 · 배당 · 분할 열이 없을 때
    """
    history = yf.Ticker(ticker).history(period="max", auto_adjust=False, raise_errors=True)
    if history.empty:
        raise ValueError(f"데이터를 찾을 수 없습니다: {ticker}")
    missing = [col for col in (COL_ADJ_CLOSE, COL_DIVIDENDS, COL_STOCK_SPLITS) if col not in history.columns]
    if missing:
        raise ValueError(f"{ticker} 응답에 {missing} 열이 없습니다 — 기존 시세와 견줄 수 없습니다")

    flat = history.reset_index()
    flat[COL_DATE] = pd.to_datetime(flat[COL_DATE]).dt.date
    events = PriceEvents(
        dividends=flat.loc[flat[COL_DIVIDENDS] > 0].set_index(COL_DATE)[COL_DIVIDENDS],
        splits=flat.loc[flat[COL_STOCK_SPLITS] > 0].set_index(COL_DATE)[COL_STOCK_SPLITS],
        raw_close=flat.set_index(COL_DATE)[COL_CLOSE],
    )
    logger.debug(f"{ticker}: {len(flat):,}행 받음 ({flat[COL_DATE].iloc[0]} ~ {flat[COL_DATE].iloc[-1]})")
    return YahooResponse(raw=flat[REQUIRED_COLUMNS].copy(), adjusted=adjust_prices(flat), events=events)
