"""자료별 갱신 방식 표 — 자료마다 받는 방식 · 갱신 방식 · 저장 파일 · 새로 붙는 날 검사를 한 곳에서 정한다

갱신 방식은 셋이다. 다시 받음(한 응답에서 수정주가는 다시 계산 · 원본가는 덧붙이기), 덧붙이기, 고정(첫 판 뒤 받지 않음).
쓰는 곳이 없으면 고정이 기본이다(결정 Q20) — 받으면 판정에 걸려 멈출 일만 는다. 짝 대조에 쓰이는 지수 · ETF 는 덧붙이기 ·
다시 받음이고(Q29 · Q31), 월별 금리 · 비트코인은 새로 나온 날을 받아 붙인다(Q36 · 3장 표). 고정 자료는 판 요약에 오른 적이
없을 때만 한 번 받는다(첫 판). 가공(합성 · 국내 수정주가)은 표에 없다 — 갱신 때마다 다시 만든다.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from quant_data.constants import (
    AUD_USD_DATA_PATH,
    EXPENSE_RATIO_DATA_PATH,
    FFR_DATA_PATH,
    PERTH_MINT_GOLD_DATA_PATH,
    ROUND_INPUT_PRICE,
    SERIES_DIR,
)
from quant_data.prices import PriceBasis, price_path


class Method(Enum):
    REFETCH = "다시 받음"
    APPEND = "덧붙이기"
    FIXED = "고정"


class Kind(Enum):
    """받는 방식 — 받기 함수와 판정을 고른다."""

    YAHOO_FUND = "야후 ETF · 펀드"  # 한 응답에서 원본가 · 수정주가
    YAHOO_INDEX = "야후 지수"  # 배당이 빠진 가격지수 — 원본가 하나
    FRED_MONTHLY = "FRED 월별"
    MANUAL_MONTHLY = "손 갱신 월별"
    PERTH_GOLD = "Perth Mint 금값"
    FRED_DAILY = "FRED 일별"
    KRX_ETF = "KRX ETF"  # KRX 원본가(기준가 · 공식 등락률 · 상장좌수) + 야후(.KS) 원본가 · 분배 기록
    KRX_INDEX = "KRX 지수"  # 종가 하나짜리 계열
    KRX_NAV = "KRX NAV"
    BITSTAMP = "Bitstamp 일봉"
    COINMETRICS = "Coin Metrics 일별"


@dataclass(frozen=True)
class Dataset:
    """자료 하나 — 이름은 --exclude · --accept · 패스 목록이 자료를 가리키는 이름이다.

    files 는 저장소 루트 기준 경로다. pair · leverage 는 새로 붙는 날의 짝 대조, source 는 받기 함수에 넘길 식별자(비면
    이름 — 야후 티커 · KRX 코드 · Coin Metrics 지표), decimals 는 하루 한 값 계열 파일의 저장 자릿수다.
    """

    name: str
    kind: Kind
    method: Method
    files: tuple[Path, ...]
    pair: str | None = None
    leverage: float = 1.0
    source: str | None = None
    decimals: int = ROUND_INPUT_PRICE

    @property
    def source_id(self) -> str:
        return self.source if self.source is not None else self.name


def kr_adjusted_path(code: str) -> Path:
    """국내 수정주가(가공) — 원본가와 같은 폴더의 `_adjusted`."""
    return price_path(code, PriceBasis.ADJUSTED)


def _fund(
    name: str,
    method: Method,
    *,
    bases: tuple[PriceBasis, ...] = (PriceBasis.RAW, PriceBasis.ADJUSTED),
    pair: str | None = None,
    leverage: float = 1.0,
) -> Dataset:
    return Dataset(
        name=name,
        kind=Kind.YAHOO_FUND,
        method=method,
        files=tuple(price_path(name, basis) for basis in bases),
        pair=pair,
        leverage=leverage,
    )


def _index(name: str) -> Dataset:
    return Dataset(name=name, kind=Kind.YAHOO_INDEX, method=Method.APPEND, files=(price_path(name, PriceBasis.RAW),))


def _kr_etf(code: str) -> Dataset:
    return Dataset(
        name=code,
        kind=Kind.KRX_ETF,
        method=Method.FIXED,
        files=(price_path(code, PriceBasis.RAW), SERIES_DIR / f"{code}_yahoo_dividends.csv"),
    )


def _kr_index(code: str) -> Dataset:
    return Dataset(name=code, kind=Kind.KRX_INDEX, method=Method.FIXED, files=(SERIES_DIR / f"{code}_index.csv",))


def _kr_nav(code: str) -> Dataset:
    return Dataset(
        name=f"{code}_NAV", kind=Kind.KRX_NAV, method=Method.FIXED, files=(SERIES_DIR / f"{code}_NAV.csv",), source=code
    )


def _coin_metric(metric: str, decimals: int) -> Dataset:
    return Dataset(
        name=f"BTC_{metric}",
        kind=Kind.COINMETRICS,
        method=Method.APPEND,
        files=(SERIES_DIR / f"BTC_{metric}.csv",),
        source=metric,
        decimals=decimals,
    )


# 고정 펀드 · 금 선물은 quant 첫 판(수정주가 하나)을 그대로 쓴다
_ADJUSTED_ONLY = (PriceBasis.ADJUSTED,)

CATALOG: tuple[Dataset, ...] = (
    # quant 몫 실물 — 다시 받음, 짝 대조(Q29 · Q30 · Q31)
    _fund("SPY", Method.REFETCH, pair="^GSPC", leverage=1.0),
    _fund("QQQ", Method.REFETCH, pair="^NDX", leverage=1.0),
    _fund("GLD", Method.REFETCH, pair="IAU", leverage=1.0),
    _fund("TLT", Method.REFETCH, pair="SPTL", leverage=1.0),
    _fund("TQQQ", Method.REFETCH, pair="^NDX", leverage=3.0),
    _fund("SSO", Method.REFETCH, pair="^GSPC", leverage=2.0),
    _fund("QLD", Method.REFETCH, pair="^NDX", leverage=2.0),
    _fund("UPRO", Method.REFETCH, pair="^GSPC", leverage=3.0),
    # 짝 — 지수는 덧붙이기, 같은 자산의 다른 ETF 는 수정주가 수익률로 견주려고 다시 받음(Q31)
    _index("^NDX"),
    _index("^GSPC"),
    _fund("IAU", Method.REFETCH),
    _fund("SPTL", Method.REFETCH),
    Dataset(name="FFR", kind=Kind.FRED_MONTHLY, method=Method.APPEND, files=(FFR_DATA_PATH,)),
    # verify-lab 몫 미국 — 중간선거 · 역방향 조사의 대상과 그 짝
    _fund("DIA", Method.REFETCH, pair="^DJI", leverage=1.0),
    _index("^DJI"),
    _index("^IXIC"),
    # 합성 재료 · 검증용 펀드 — 고정
    _fund("VFINX", Method.FIXED, bases=_ADJUSTED_ONLY),
    _fund("VUSTX", Method.FIXED, bases=_ADJUSTED_ONLY),
    _fund("GC=F", Method.FIXED, bases=_ADJUSTED_ONLY),
    _fund("UOPIX", Method.FIXED, bases=_ADJUSTED_ONLY),
    _fund("ULPIX", Method.FIXED, bases=_ADJUSTED_ONLY),
    _fund("RYNVX", Method.FIXED, bases=_ADJUSTED_ONLY),
    Dataset(name="PERTH_GOLD", kind=Kind.PERTH_GOLD, method=Method.FIXED, files=(PERTH_MINT_GOLD_DATA_PATH,)),
    Dataset(name="AUD_USD", kind=Kind.FRED_DAILY, method=Method.FIXED, files=(AUD_USD_DATA_PATH,)),
    Dataset(name="EXPENSE", kind=Kind.MANUAL_MONTHLY, method=Method.FIXED, files=(EXPENSE_RATIO_DATA_PATH,)),
    # 조사 전용 미국 레버리지 · 인버스 — 고정(분할이 잦다 — SQQQ 8건)
    *(
        _fund(name, Method.FIXED)
        for name in ("DDM", "DOG", "DXD", "PSQ", "QID", "SDOW", "SDS", "SH", "SPXU", "SQQQ", "UDOW")
    ),
    # 국내 — 고정(조사 전용 · 국내 합성 2단계에서 바뀜). 국내 수정주가는 가공(kr_adjusted_path)
    *(
        _kr_etf(code)
        for code in ("069500", "114800", "122630", "229200", "233740", "251340", "252670", "261240", "261250")
    ),
    *(_kr_index(code) for code in ("1001", "1028", "2001", "2203")),
    _kr_nav("261240"),
    _kr_nav("261250"),
    # 비트코인 — 덧붙이기, Bitstamp 일봉 ↔ Coin Metrics 기준가 두 출처 대조(사용자 결정 2026-11-11)
    Dataset(
        name="BTCUSD",
        kind=Kind.BITSTAMP,
        method=Method.APPEND,
        files=(price_path("BTCUSD", PriceBasis.RAW),),
        pair="BTC_PriceUSD",
    ),
    _coin_metric("PriceUSD", ROUND_INPUT_PRICE),
    _coin_metric("CapMVRVCur", 4),  # 배수 — 비율과 같은 4자리
    _coin_metric("CapMrktCurUSD", 0),  # 달러
)
