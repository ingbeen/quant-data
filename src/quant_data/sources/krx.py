"""KRX 받기 — 국내 ETF 원본가(기준가 · 공식 등락률 · 상장좌수) · 지수 종가 · NAV

pykrx 를 쓴다. ETF 원본가는 pykrx 공개 함수(get_etf_ohlcv_by_date)가 KRX 응답의 대비 · 등락률 · 상장좌수를 버려,
내부 클래스 `개별종목시세_ETF`(KRX 화면 MDCSTAT04501)를 직접 부른다(착수 전 측정 ①). pykrx 버전이 바뀌어 그 클래스 ·
열이 바뀌면 import · 열 이름 에러로 드러난다. 파일은 쓰지 않는다 — 판정 · 쓰기는 update 가 한다.

pykrx 는 import 할 때 로그인하고 계정 아이디를 표준출력에 찍는다 → 자격증명을 환경 변수에 올린 뒤 함수 안에서
import 하고, pykrx 의 표준출력에서 아이디가 든 줄을 뺀 나머지만 로그로 남긴다.
"""

import contextlib
import io
import os
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from quant_data.constants import (
    COL_BASE_PRICE,
    COL_CHANGE_RATE,
    COL_CLOSE,
    COL_DATE,
    COL_HIGH,
    COL_LISTED_SHARES,
    COL_LOW,
    COL_OPEN,
    COL_VALUE,
    COL_VOLUME,
    REQUIRED_COLUMNS,
)
from quant_data.logger import get_logger

logger = get_logger(__name__)

ENV_KRX_ID: Final = "KRX_ID"  # pykrx 가 정한 이름
ENV_KRX_PW: Final = "KRX_PW"
ENV_PATH: Final = Path(__file__).resolve().parents[3] / ".env"  # 저장소 루트 — 실행 위치와 무관하게
KST: Final = ZoneInfo("Asia/Seoul")
_REQUEST_DATE_FORMAT: Final = "%Y%m%d"
ETF_FIRST_REQUEST_DATE: Final = date(2002, 10, 14)  # 국내 첫 ETF(KODEX 200) 상장일 — 그 앞의 ETF 시세는 없다
INDEX_FIRST_REQUEST_DATE: Final = date(1980, 1, 1)  # 코스피 종합 지수 첫 행 1980-01-04 (verify-lab 실측)

# KRX 등락 구분 → 대비의 부호 (1 상승 · 2 하락 · 3 보합 · 4 상한 · 5 하한)
_SIGN_BY_FLUC_CODE: Final[Mapping[str, int]] = {"1": 1, "2": -1, "3": 0, "4": 1, "5": -1}
_ETF_KEYS: Final = (
    "TRD_DD",
    "TDD_OPNPRC",
    "TDD_HGPRC",
    "TDD_LWPRC",
    "TDD_CLSPRC",
    "ACC_TRDVOL",
    "FLUC_TP_CD",
    "CMPPREVDD_PRC",
    "FLUC_RT",
    "LIST_SHRS",
)


def load_krx_credentials(path: Path = ENV_PATH) -> None:
    """
    .env 의 KRX 계정을 환경 변수에 올린다 — pykrx 를 import 하기 전에 부른다. 예외 메시지에 값은 넣지 않는다.

    Raises:
        ValueError: 파일이 없거나 키 값이 비었을 때
    """
    if not path.is_file():
        raise ValueError(f"KRX 자격증명 파일이 없습니다: {path} — data.krx.co.kr 계정({ENV_KRX_ID} · {ENV_KRX_PW})을 담은 .env 를 만드세요")
    load_dotenv(path, override=True)  # 셸에 남은 옛 값보다 .env 를 우선
    missing = [key for key in (ENV_KRX_ID, ENV_KRX_PW) if not os.environ.get(key)]
    if missing:
        raise ValueError(f"{path} 에 값이 비어 있습니다: {', '.join(missing)}")


def filtered_pykrx_output(text: str, account: str) -> list[str]:
    """pykrx 표준출력에서 빈 줄과 계정 아이디가 든 줄을 뺀 나머지 — 계정이 비면 빈 줄만 뺀다."""
    return [line for line in text.splitlines() if line.strip() and not (account and account in line)]


@contextlib.contextmanager
def _pykrx_output_hidden() -> Iterator[None]:
    """블록 안의 표준출력을 모았다가 아이디가 든 줄을 빼고 로그로 남긴다 — 예외가 나도 남긴다."""
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            yield
    finally:
        for line in filtered_pykrx_output(buffer.getvalue(), os.environ.get(ENV_KRX_ID, "")):
            logger.debug(f"pykrx: {line}")


def _import_pykrx() -> tuple[Any, Any, Any]:
    """자격증명을 올린 뒤 (stock, 개별종목시세_ETF, get_etx_isin) 을 가져온다 — import 자체가 로그인한다."""
    load_krx_credentials()
    with _pykrx_output_hidden():
        from pykrx import stock  # noqa: PLC0415 — 자격증명보다 먼저 import 하면 로그인이 빈 계정으로 시도된다
        from pykrx.website.krx.etx.core import 개별종목시세_ETF  # noqa: PLC0415
        from pykrx.website.krx.etx.ticker import get_etx_isin  # noqa: PLC0415
    return stock, 개별종목시세_ETF, get_etx_isin


def _number(text: object) -> float:
    cleaned = str(text).replace(",", "").strip()
    return float(cleaned) if cleaned not in ("", "-") else float("nan")


def normalize_etf_records(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """
    KRX 화면 행 → 시세 표: 필수 열 + 기준가(종가 − 부호 붙은 대비) · 공식 등락률(%) · 상장좌수, 날짜 오름차순.
    가격 · 기준가 · 거래량 · 상장좌수는 부호 있는 int64 다 — `uint32` 로 두면 차분에서 하락일이 40억 근처 양수가 된다.

    Raises:
        ValueError: 행에 필요한 열이 없을 때, 모르는 등락 구분, 가격이 비어 정수로 둘 수 없을 때
    """
    rows: list[dict[str, object]] = []
    for record in records:
        missing = [key for key in _ETF_KEYS if key not in record]
        if missing:
            raise ValueError(f"KRX 응답 행에 열이 없습니다: {missing} — pykrx · KRX 화면이 바뀌었는지 확인하세요")
        code = str(record["FLUC_TP_CD"]).strip()
        if code not in _SIGN_BY_FLUC_CODE:
            raise ValueError(f"KRX 등락 구분 '{code}' 을 모릅니다 ({record['TRD_DD']}) — 대비의 부호를 정할 수 없습니다")
        close = _number(record["TDD_CLSPRC"])
        rows.append(
            {
                COL_DATE: datetime.strptime(str(record["TRD_DD"]).strip(), "%Y/%m/%d").date(),
                COL_OPEN: _number(record["TDD_OPNPRC"]),
                COL_HIGH: _number(record["TDD_HGPRC"]),
                COL_LOW: _number(record["TDD_LWPRC"]),
                COL_CLOSE: close,
                COL_VOLUME: _number(record["ACC_TRDVOL"]),
                COL_BASE_PRICE: close - _SIGN_BY_FLUC_CODE[code] * _number(record["CMPPREVDD_PRC"]),
                COL_CHANGE_RATE: _number(record["FLUC_RT"]),
                COL_LISTED_SHARES: _number(record["LIST_SHRS"]),
            }
        )
    frame = pd.DataFrame(rows, columns=[*REQUIRED_COLUMNS, COL_BASE_PRICE, COL_CHANGE_RATE, COL_LISTED_SHARES])
    integer_columns = [COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOLUME, COL_BASE_PRICE, COL_LISTED_SHARES]
    if frame[integer_columns].isna().any().any():
        bad = frame.loc[frame[integer_columns].isna().any(axis=1), COL_DATE].tolist()
        raise ValueError(f"KRX 응답에 비어 있는 가격 · 거래량 칸이 있습니다 — 날짜: {bad[:5]} (메우지 않습니다)")
    frame[integer_columns] = frame[integer_columns].round(0).astype("int64")
    return frame.sort_values(COL_DATE).reset_index(drop=True)


def _today_text() -> str:
    return datetime.now(KST).strftime(_REQUEST_DATE_FORMAT)


def fetch_krx_etf(code: str) -> pd.DataFrame:
    """
    국내 ETF 의 상장일부터 오늘까지 원본가(+ 기준가 · 공식 등락률 · 상장좌수). 기준일로 자르는 것은 update 다.

    Raises:
        ValueError: 자격증명 · 응답이 비었거나 열 · 값이 깨졌을 때
    """
    _, etf_daily, get_isin = _import_pykrx()
    with _pykrx_output_hidden():
        isin = get_isin(code)
        response = etf_daily().fetch(ETF_FIRST_REQUEST_DATE.strftime(_REQUEST_DATE_FORMAT), _today_text(), isin)
    if response.empty:
        raise ValueError(f"KRX 응답이 비었습니다 - ETF {code}")
    frame = normalize_etf_records(response.to_dict("records"))
    logger.debug(f"KRX {code}: {len(frame):,}행 받음 ({frame[COL_DATE].iloc[0]} ~ {frame[COL_DATE].iloc[-1]})")
    return frame


def _value_series(raw: pd.DataFrame, column: str, what: str) -> pd.DataFrame:
    if raw.empty or column not in raw.columns:
        raise ValueError(f"KRX {what} 응답이 비었거나 「{column}」 열이 없습니다 (열: {list(raw.columns)})")
    series = pd.DataFrame({COL_DATE: pd.to_datetime(raw.index).date, COL_VALUE: raw[column].astype(float).to_numpy()})
    return series.sort_values(COL_DATE).reset_index(drop=True)


def fetch_krx_index(code: str) -> pd.DataFrame:
    """
    국내 지수의 종가 하나짜리 계열 — 옛 구간에 시가 · 고가 · 저가가 0 인 행이 있어 시세 모양으로 둘 수 없다(verify-lab 실측).

    Raises:
        ValueError: 응답이 비었거나 종가 열이 없을 때
    """
    stock, _, _ = _import_pykrx()
    with _pykrx_output_hidden():
        raw = stock.get_index_ohlcv(INDEX_FIRST_REQUEST_DATE.strftime(_REQUEST_DATE_FORMAT), _today_text(), code)
    return _value_series(raw, "종가", f"지수 {code}")


def fetch_krx_nav(code: str) -> pd.DataFrame:
    """
    국내 ETF 의 NAV 계열 — 호가가 아니라 계산된 값이라 소수 둘째 자리까지 온다.

    Raises:
        ValueError: 응답이 비었거나 NAV 열이 없을 때
    """
    stock, _, _ = _import_pykrx()
    with _pykrx_output_hidden():
        raw = stock.get_etf_ohlcv_by_date(ETF_FIRST_REQUEST_DATE.strftime(_REQUEST_DATE_FORMAT), _today_text(), code)
    return _value_series(raw, "NAV", f"NAV {code}")
