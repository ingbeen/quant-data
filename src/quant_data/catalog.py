"""자료별 갱신 방식 표 — 자료마다 받는 방식 · 갱신 방식 · 저장 파일 · 새로 붙는 날 검사를 한 곳에서 정한다

갱신 방식은 셋이다. 다시 받음(한 응답에서 수정주가는 다시 계산 · 원본가는 덧붙이기), 덧붙이기, 고정(첫 판 뒤 받지 않음).
쓰는 곳이 없으면 고정이 기본이다(결정 Q20) — 받으면 판정에 걸려 멈출 일만 는다. 나스닥100 · S&P500 지수는 짝 대조에
쓰여 덧붙이고(Q29), 월별 금리는 새로 나온 달을 받아 붙인다(Q36). 가공(합성 · 국내 수정주가)은 표에 없다 — 갱신 때마다
다시 만든다.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from quant_data.constants import AUD_USD_DATA_PATH, EXPENSE_RATIO_DATA_PATH, FFR_DATA_PATH, PERTH_MINT_GOLD_DATA_PATH
from quant_data.new_days import TEMP_DAILY_MOVE_LIMIT
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


@dataclass(frozen=True)
class Dataset:
    """자료 하나 — 이름은 --exclude · --accept · 패스 목록이 자료를 가리키는 이름이다.

    files 는 저장소 루트 기준 경로다. pair · leverage 는 새로 붙는 날의 짝 대조(대상 하루 수익률 − 배율 × 짝 하루 수익률),
    daily_move_limit 은 짝이 없는 자료의 하루 변동 한도(비율)다.
    """

    name: str
    kind: Kind
    method: Method
    files: tuple[Path, ...]
    pair: str | None = None
    leverage: float = 1.0
    daily_move_limit: float | None = None


def _fund(
    name: str,
    method: Method,
    *,
    bases: tuple[PriceBasis, ...] = (PriceBasis.RAW, PriceBasis.ADJUSTED),
    pair: str | None = None,
    leverage: float = 1.0,
    daily_move_limit: float | None = None,
) -> Dataset:
    return Dataset(
        name=name,
        kind=Kind.YAHOO_FUND,
        method=method,
        files=tuple(price_path(name, basis) for basis in bases),
        pair=pair,
        leverage=leverage,
        daily_move_limit=daily_move_limit,
    )


def _index(name: str) -> Dataset:
    return Dataset(name=name, kind=Kind.YAHOO_INDEX, method=Method.APPEND, files=(price_path(name, PriceBasis.RAW),))


# 고정 펀드 · 금 선물은 quant 첫 판(수정주가 하나)을 그대로 쓴다
_ADJUSTED_ONLY = (PriceBasis.ADJUSTED,)

CATALOG: tuple[Dataset, ...] = (
    # quant 몫 실물 — 다시 받음, 짝 대조(Q29 · Q30) 또는 하루 변동 임시 한도(Q27)
    _fund("SPY", Method.REFETCH, pair="^GSPC", leverage=1.0),
    _fund("QQQ", Method.REFETCH, pair="^NDX", leverage=1.0),
    _fund("GLD", Method.REFETCH, daily_move_limit=TEMP_DAILY_MOVE_LIMIT),
    _fund("TLT", Method.REFETCH, daily_move_limit=TEMP_DAILY_MOVE_LIMIT),
    _fund("TQQQ", Method.REFETCH, pair="^NDX", leverage=3.0),
    _fund("SSO", Method.REFETCH, pair="^GSPC", leverage=2.0),
    _fund("QLD", Method.REFETCH, pair="^NDX", leverage=2.0),
    _fund("UPRO", Method.REFETCH, pair="^GSPC", leverage=3.0),
    # 짝 지수 — 덧붙이기
    _index("^NDX"),
    _index("^GSPC"),
    Dataset(name="FFR", kind=Kind.FRED_MONTHLY, method=Method.APPEND, files=(FFR_DATA_PATH,)),
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
)
