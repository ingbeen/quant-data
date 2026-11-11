"""Bitstamp 비트코인 일봉 받기 — verify-lab `bitstamp_collector` 에서 옮김

공개 REST 엔드포인트(`/api/v2/ohlc/btcusd/`, 인증키 없음)에서 BTC/USD 일봉을 첫 거래일부터 받는다. 파일은 쓰지 않는다 —
판정 · 쓰기는 update 가 한다.

실측한 함정 넷 (verify-lab 2026-09-29)
1. 시작 시각을 첫 거래일(2011-08-18 00:00 UTC)보다 앞에 두면 에러 없이 빈 응답이 온다 → 시작을 그 시각에 고정하고
   첫 페이지가 비면 멈춘다
2. 봉의 날짜는 UTC 하루다 → 끝나지 않은 봉은 뺀다(crypto_days)
3. 거래가 없던 날도 행이 온다 — 네 값이 전일 종가, 거래량 0. 받은 그대로 둔다
4. 시작이 마지막 봉보다 뒤면 빈 목록이 아니라 가장 최근 봉을 다시 준다 → 페이지 순회는 「시작 이후의 새 봉 없음」에서 멈춘다
"""

import json
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from typing import Any, Final

import pandas as pd

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, REQUIRED_COLUMNS
from quant_data.logger import get_logger
from quant_data.sources.crypto_days import exclude_unfinished_days, require_complete_range

logger = get_logger(__name__)

BITSTAMP_OHLC_URL: Final = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
DAY_SECONDS: Final = 86_400
PAGE_LIMIT = 1_000  # 요청 한 번에 받는 봉 수 — Bitstamp 가 허용하는 최대값
FIRST_TRADE_TIMESTAMP: Final = 1_313_625_600  # 2011-08-18 00:00 UTC (함정 1)
FIRST_TRADE_DATE: Final[date] = datetime.fromtimestamp(FIRST_TRADE_TIMESTAMP, tz=UTC).date()
_USER_AGENT: Final = "quant-data"
_TIMEOUT_SECONDS: Final = 60
_FIELD_TO_COLUMN: Final = {"open": COL_OPEN, "high": COL_HIGH, "low": COL_LOW, "close": COL_CLOSE, "volume": COL_VOLUME}


def request_ohlc_page(start: int) -> list[dict[str, Any]]:
    """
    start(UTC 유닉스 초)부터 일봉 한 페이지 — 값은 서버가 준 문자열 그대로.

    Raises:
        ValueError: HTTP 오류 · 연결 실패 · 응답 모양이 다를 때
    """
    url = f"{BITSTAMP_OHLC_URL}?step={DAY_SECONDS}&limit={PAGE_LIMIT}&start={start}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise ValueError(f"Bitstamp 응답이 HTTP 오류입니다 ({error.code}) - 시작 시각: {start}") from None
    except urllib.error.URLError as error:
        raise ValueError(f"Bitstamp 에 연결하지 못했습니다: {error.reason} - 시작 시각: {start}") from None
    try:
        ohlc = json.loads(body)["data"]["ohlc"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError(f"Bitstamp 응답 모양이 예상과 다릅니다 (data.ohlc 없음) - 시작 시각: {start}, 앞부분: {body[:200]}") from None
    if not isinstance(ohlc, list):
        raise ValueError(f"Bitstamp 응답의 data.ohlc 가 목록이 아닙니다 - 시작 시각: {start}")
    return ohlc  # pyright: ignore[reportUnknownVariableType] — 서버가 준 JSON 그대로


def parse_ohlc_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    봉 목록 → 시세 표(날짜 + OHLCV 실수), 날짜 오름차순 · 같은 봉은 하나만.

    Raises:
        ValueError: 봉이 없음 · 키가 없음 · 봉 시각이 UTC 자정이 아님 (봉의 하루가 바뀌면 Coin Metrics 와 조용히 어긋난다)
    """
    if not rows:
        raise ValueError("Bitstamp 봉 목록이 비어 있습니다")
    frame = pd.DataFrame(rows)
    missing = {"timestamp", *_FIELD_TO_COLUMN} - set(frame.columns)
    if missing:
        raise ValueError(f"Bitstamp 봉에 필요한 키가 없습니다: {sorted(missing)}")
    timestamps = frame["timestamp"].astype("int64")
    off_midnight = timestamps % DAY_SECONDS != 0
    if off_midnight.any():
        raise ValueError(f"UTC 자정이 아닌 봉 시각이 있습니다 - 건수: {int(off_midnight.sum())}, 예시: {timestamps[off_midnight].head().tolist()}")
    frame = frame.assign(timestamp=timestamps).drop_duplicates(subset="timestamp", keep="first")
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    parsed = pd.DataFrame({COL_DATE: [datetime.fromtimestamp(int(ts), tz=UTC).date() for ts in frame["timestamp"]]})
    for field, column in _FIELD_TO_COLUMN.items():
        parsed[column] = frame[field].astype(float)
    return parsed[REQUIRED_COLUMNS]


def fetch_ohlc_history() -> pd.DataFrame:
    """
    첫 거래일부터 페이지를 이어 받는다 — 페이지마다 마지막 봉 다음 날부터 다시 묻고, 시작 이후의 새 봉이 없을 때 멈춘다
    (덜 찬 페이지에서 멈추지 않는다 · 빈 페이지를 기다리지 않는다 — 함정 4).

    Raises:
        ValueError: 첫 페이지가 빔 · timestamp 를 읽을 수 없음 · 요청 · 해석에서 걸림
    """
    rows: list[dict[str, Any]] = []
    start = FIRST_TRADE_TIMESTAMP
    while True:
        page = request_ohlc_page(start)
        try:
            fresh = [row for row in page if int(row["timestamp"]) >= start]
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Bitstamp 봉에 읽을 수 있는 timestamp 가 없습니다 - 시작 시각: {start}") from None
        if not fresh:
            if not rows:
                raise ValueError(f"Bitstamp 첫 페이지가 빈 응답입니다 — 시작 시각이 첫 거래일보다 앞이면 에러 없이 빈 응답이 옵니다 (시작 시각: {start})")
            break
        rows.extend(fresh)
        start = max(int(row["timestamp"]) for row in fresh) + DAY_SECONDS
    return parse_ohlc_rows(rows)


def fetch_bitstamp_history(now: datetime) -> pd.DataFrame:
    """
    전 기간 일봉 — 끝나지 않은 UTC 날을 빼고, 첫 거래일 · 끝(공개 지연 0) · 사이의 빈틈을 본다.

    Args:
        now: 받기 전에 잰 지금 시각 (시간대 필수)

    Raises:
        ValueError: 받기 · 해석에서 걸림, 이력이 잘렸거나 빈틈이 있음, now 에 시간대가 없음
    """
    frame = exclude_unfinished_days(fetch_ohlc_history(), now)
    require_complete_range(frame[COL_DATE], first_day=FIRST_TRADE_DATE, now=now, publication_lag_days=0)
    logger.debug(f"Bitstamp BTCUSD: {len(frame):,}행 받음 ({frame[COL_DATE].iloc[0]} ~ {frame[COL_DATE].iloc[-1]})")
    return frame
