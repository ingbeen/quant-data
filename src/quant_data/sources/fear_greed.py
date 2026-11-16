"""CNN 공포탐욕지수 받기 — 공개 결합본(GitHub whit3rabbit/fear-greed-data)의 fear-greed.csv

CNN 은 과거 시계열을 내지 않는다. 결합본은 2011-01-03 ~ 2021-01-29 를 복원본(고정)으로, 2021-02-01 ~ 를 CNN 피드로
평일 23:00 UTC 마다 다시 만든다 — 출처 대조는 docs/research/시세_받기_판정.md 6장. 파일은 쓰지 않는다 — 판정 · 쓰기는 update 가 한다.
값은 0 ~ 100 이고 0 인 날이 실재한다(2014-10-13). 범위 밖 · 결측 · 중복 날짜 · 다른 헤더면 메우지 않고 멈춘다.
"""

import csv
import io
import urllib.error
import urllib.request
from typing import Final

import pandas as pd

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.logger import get_logger
from quant_data.series import validate_series

logger = get_logger(__name__)

FEAR_GREED_URL: Final = "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv"
# 결합본 README 「Canonical dataset」의 열 — Rating 은 값에서 나온 이름표라 버림
SOURCE_COLUMNS: Final = ["Date", "Fear Greed", "Rating"]
_SOURCE_VALUE: Final = "Fear Greed"
_DATE_FORMAT: Final = "%Y-%m-%d"
VALUE_MIN: Final = 0.0
VALUE_MAX: Final = 100.0
_USER_AGENT: Final = "quant-data"
_TIMEOUT_SECONDS: Final = 60


def parse_fear_greed_csv(text: str) -> pd.DataFrame:
    """
    결합본 CSV → 계열(Date · Value), 날짜 오름차순. 값은 그대로 두고(저장 자릿수는 update 가 자른다) 범위를 본다.

    Raises:
        ValueError: 헤더가 다름 · 행이 없음 · 칸 수가 다른 행 · 연-월-일로 읽히지 않는 날짜(빈 날짜 포함) · 결측(숫자가 아닌 값 포함) ·
            중복 날짜 · 0 ~ 100 밖의 값
    """
    # pandas 는 칸이 헤더보다 많은 행의 첫 칸을 조용히 인덱스로 돌림 → 값을 옆 칸에서 읽으므로 행마다 칸 수를 셈
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != SOURCE_COLUMNS:
        header = rows[0] if rows else []
        raise ValueError(f"공포탐욕지수 결합본의 헤더가 {SOURCE_COLUMNS} 가 아닙니다: {header} — 저장소가 모양을 바꿨는지 보세요")
    body = [row for row in rows[1:] if row]
    if not body:
        raise ValueError("공포탐욕지수 결합본이 비어 있습니다")
    malformed = [row for row in body if len(row) != len(SOURCE_COLUMNS)]
    if malformed:
        raise ValueError(f"공포탐욕지수 결합본에 칸 수가 {len(SOURCE_COLUMNS)} 가 아닌 행이 있습니다 - {len(malformed)}개, 예시: {malformed[:3]}")
    frame = pd.DataFrame(body, columns=SOURCE_COLUMNS)
    # 연-월-일로 읽히지 않는 날짜(빈 날짜 · 다른 구분자)는 NaT 로 남아 뒤의 기준일 자르기에서 조용히 빠짐 → 멈춤
    dates = pd.to_datetime(frame["Date"], format=_DATE_FORMAT, errors="coerce")
    if dates.isna().any():
        raise ValueError(f"공포탐욕지수 결합본에 {_DATE_FORMAT} 가 아닌 날짜가 있습니다 - 예시: {frame.loc[dates.isna(), 'Date'].head().tolist()}")
    series = pd.DataFrame(
        {
            COL_DATE: dates.dt.date,
            COL_VALUE: pd.to_numeric(frame[_SOURCE_VALUE], errors="coerce"),
        }
    )
    series = series.sort_values(COL_DATE).reset_index(drop=True)
    validate_series(series)
    outside = ~series[COL_VALUE].between(VALUE_MIN, VALUE_MAX)
    if outside.any():
        examples = series.loc[outside, [COL_DATE, COL_VALUE]].head().values.tolist()
        raise ValueError(f"공포탐욕지수가 {VALUE_MIN:g} ~ {VALUE_MAX:g} 밖입니다 - {int(outside.sum())}개, 예시: {examples}")
    return series


def fetch_fear_greed() -> pd.DataFrame:
    """
    결합본 전 기간을 받는다.

    Raises:
        ValueError: HTTP 오류 · 연결 실패 · parse_fear_greed_csv 와 같은 경우
    """
    request = urllib.request.Request(FEAR_GREED_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise ValueError(f"공포탐욕지수 결합본 응답이 HTTP 오류입니다 ({error.code}) - URL: {FEAR_GREED_URL}") from None
    except urllib.error.URLError as error:
        raise ValueError(f"공포탐욕지수 결합본에 연결하지 못했습니다: {error.reason} - URL: {FEAR_GREED_URL}") from None
    frame = parse_fear_greed_csv(text)
    logger.debug(f"공포탐욕지수: {len(frame):,}행 받음 ({frame[COL_DATE].iloc[0]} ~ {frame[COL_DATE].iloc[-1]})")
    return frame
