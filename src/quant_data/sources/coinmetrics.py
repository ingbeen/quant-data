"""Coin Metrics 커뮤니티 API 일별 지표 받기 — verify-lab `coinmetrics_collector` 에서 옮김

인증키 없이 비트코인 일별 지표(기준가 · MVRV · 시가총액)를 첫 날(2010-07-18)부터 받는다. 기준가는 Bitstamp 일봉의 두 출처
대조 상대다. 파일은 쓰지 않는다 — 판정 · 쓰기는 update 가 한다.

실측한 함정 둘 (verify-lab 2026-09-29)
1. paging_from 을 주지 않으면 최신 행부터 와 한 페이지만 받으면 예외 없이 최근 구간만 남는다 → paging_from=start
2. 값의 날짜 d 는 d 일 UTC 하루가 끝난 시점의 값이고, d+1 일 UTC 02:28 ~ 03:32 에 완성된다 → 끝에 하루 공개 지연을 허용한다
값이 비거나 0 이하면 메우지 않고 멈춘다 — 휴장이 없어 빈 값은 소스의 결함이다.
"""

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Final

import pandas as pd

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.logger import get_logger
from quant_data.series import validate_series
from quant_data.sources.crypto_days import exclude_unfinished_days, require_complete_range

logger = get_logger(__name__)

COINMETRICS_METRICS_URL: Final = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
COINMETRICS_ASSET: Final = "btc"
FIRST_DAY: Final = date(2010, 7, 18)  # 마운트곡스 개장일 — 받는 세 지표의 첫 날 (verify-lab 실측)
PAGE_SIZE: Final = 10_000  # 커뮤니티 API 최대
PUBLICATION_LAG_DAYS: Final = 1  # 함정 2
_USER_AGENT: Final = "quant-data"
_TIMEOUT_SECONDS: Final = 60


def first_page_url(metric: str) -> str:
    """오래된 행부터 묻는 첫 페이지 URL (함정 1)."""
    query = urllib.parse.urlencode(
        {
            "assets": COINMETRICS_ASSET,
            "metrics": metric,
            "frequency": "1d",
            "page_size": PAGE_SIZE,
            "paging_from": "start",
        }
    )
    return f"{COINMETRICS_METRICS_URL}?{query}"


def _request_page(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise ValueError(f"Coin Metrics 응답이 HTTP 오류입니다 ({error.code}) - URL: {url}") from None
    except urllib.error.URLError as error:
        raise ValueError(f"Coin Metrics 에 연결하지 못했습니다: {error.reason} - URL: {url}") from None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError(f"Coin Metrics 응답이 JSON 이 아닙니다 - URL: {url}, 앞부분: {body[:200]}") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):  # pyright: ignore[reportUnknownMemberType]
        raise ValueError(f"Coin Metrics 응답 모양이 예상과 다릅니다 (data 목록 없음) - URL: {url}, 앞부분: {body[:200]}")
    return payload  # pyright: ignore[reportUnknownVariableType] — 서버가 준 JSON 그대로


def _fetch_rows(metric: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    url: str | None = first_page_url(metric)
    while url is not None:
        payload = _request_page(url)
        rows.extend(payload["data"])
        next_url = payload.get("next_page_url")
        if next_url is not None and next_url == url:
            raise ValueError(f"Coin Metrics 다음 페이지가 앞으로 나아가지 않습니다 (같은 URL) - {url}")
        url = next_url
    return rows


def parse_metric_rows(rows: list[dict[str, Any]], metric: str) -> pd.DataFrame:
    """
    행 → 계열(Date · Value), 날짜는 그 값의 UTC 날짜. 값이 없는 행은 결측으로 남긴다(뒤의 검사가 멈춘다).

    Raises:
        ValueError: 행이 없음 · time 이 없음 · UTC 자정이 아닌 시각
    """
    if not rows:
        raise ValueError(f"Coin Metrics 응답이 비어 있습니다 - 지표: {metric}")
    frame = pd.DataFrame(rows)
    if "time" not in frame.columns:
        raise ValueError(f"Coin Metrics 행에 time 이 없습니다 - 지표: {metric}")
    times = pd.to_datetime(frame["time"], utc=True)
    off_midnight = times != times.dt.normalize()
    if off_midnight.any():
        raise ValueError(f"UTC 자정이 아닌 시각이 있습니다 - 지표: {metric}, 예시: {frame.loc[off_midnight, 'time'].head().tolist()}")
    values = frame[metric] if metric in frame.columns else pd.Series(math.nan, index=frame.index)
    return pd.DataFrame({COL_DATE: times.dt.date, COL_VALUE: pd.to_numeric(values, errors="coerce")})


def fetch_coinmetrics_series(metric: str, now: datetime) -> pd.DataFrame:
    """
    지표 하나의 전 기간 — 끝나지 않은 UTC 날을 빼고, 결측 · 0 이하 값, 첫 날 · 끝(하루 지연) · 사이의 빈틈을 본다.

    Args:
        metric: Coin Metrics 지표 이름 (PriceUSD · CapMVRVCur · CapMrktCurUSD)
        now: 받기 전에 잰 지금 시각 (시간대 필수)

    Raises:
        ValueError: 받기 · 해석에서 걸림, 결측 · 0 이하 값, 이력이 잘렸거나 빈틈이 있음, now 에 시간대가 없음
    """
    frame = parse_metric_rows(_fetch_rows(metric), metric).sort_values(COL_DATE).reset_index(drop=True)
    frame = exclude_unfinished_days(frame, now)
    validate_series(frame)
    invalid = ~(frame[COL_VALUE] > 0) | ~frame[COL_VALUE].map(math.isfinite)
    if invalid.any():
        raise ValueError(f"유한한 양수가 아닌 값 발견(0 이하 · 무한대) - 지표: {metric}, 날짜: {frame.loc[invalid, COL_DATE].head().tolist()}")
    require_complete_range(frame[COL_DATE], first_day=FIRST_DAY, now=now, publication_lag_days=PUBLICATION_LAG_DAYS)
    logger.debug(f"Coin Metrics {metric}: {len(frame):,}행 받음 ({frame[COL_DATE].iloc[0]} ~ {frame[COL_DATE].iloc[-1]})")
    return frame
