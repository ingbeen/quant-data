"""quant-data 공통 상수 — 두 개 이상 모듈이 쓰는 저장 경로 · 열 이름 · 자릿수."""

from pathlib import Path
from typing import Final

# ============================================================
# 저장 경로 — 저장소 루트 기준 상대 경로
# ============================================================
# 판 요약 · 내보내기가 이 상대 경로를 파일 이름처럼 적는다 — 절대 경로면 공개 저장소에 로컬 경로가 올라간다
STORAGE_DIR: Final = Path("storage")
PRICES_DIR: Final = STORAGE_DIR / "prices"  # 시세 — 이름은 prices.price_path
SERIES_DIR: Final = STORAGE_DIR / "series"  # 하루 · 한 달에 값 하나인 계열 (금리 · 운용비율 · 금값 · 환율)
RECORDS_DIR: Final = STORAGE_DIR / "records"  # 사람 · AI 가 쓰는 기록
VALIDATION_DIR: Final = STORAGE_DIR / "validation"  # 합성 검증 표
EDITION_PATH: Final = STORAGE_DIR / "edition.json"  # 판 요약

PASS_LIST_PATH: Final = RECORDS_DIR / "pass_list.csv"  # 새로 붙는 날 검사의 예외 — 사람과 AI 가 적는다
KR_ACTIONS_PATH: Final = RECORDS_DIR / "kr_actions.csv"  # 국내 분할 기록 — 사람만 적는다

FFR_DATA_PATH: Final = SERIES_DIR / "federal_funds_rate_monthly.csv"  # FRED 월별 연방기금금리
EXPENSE_RATIO_DATA_PATH: Final = SERIES_DIR / "tqqq_net_expense_ratio_monthly.csv"  # TQQQ 순운용비율 (손 갱신)
PERTH_MINT_GOLD_DATA_PATH: Final = SERIES_DIR / "perth_mint_gold_daily.csv"  # Perth Mint 하루 평균 금값
AUD_USD_DATA_PATH: Final = SERIES_DIR / "aud_usd_daily.csv"  # FRED 호주달러 환율 (DEXUSAL)

# ============================================================
# 시세 열
# ============================================================
COL_DATE: Final = "Date"
COL_OPEN: Final = "Open"
COL_HIGH: Final = "High"
COL_LOW: Final = "Low"
COL_CLOSE: Final = "Close"
COL_VOLUME: Final = "Volume"
REQUIRED_COLUMNS: Final = [COL_DATE, COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE, COL_VOLUME]
PRICE_COLUMNS: Final = [COL_OPEN, COL_HIGH, COL_LOW, COL_CLOSE]

# KRX 공식 등락률 — pykrx 반환 그대로 % 단위 (전역 python.md 「pykrx」)
COL_CHANGE_RATE: Final = "change_rate"

# FRED fredgraph.csv 의 날짜 열 — 이름을 바꾼 적이 있음(DATE → observation_date) → 받을 때 머리까지 고정
FRED_DATE_COLUMN: Final = "observation_date"

# ============================================================
# 기간 · 자릿수
# ============================================================
ANNUAL_DAYS: Final = 365.25  # 1년의 평균 달력 일수 — CAGR 의 연수 환산
TRADING_DAYS_PER_YEAR: Final = 252  # 일일 비용 ↔ 연간 비용 환산

# 시세 파일의 가격 자릿수 — 사용처 백테스트의 계산 입력이라 quant 의 지금 입력과 같은 자리(결정 Q6)
ROUND_INPUT_PRICE: Final = 6
ROUND_PERCENT: Final = 2  # 검증 표의 백분율 (CAGR · MDD · 수익률)
ROUND_RATIO: Final = 4  # 검증 표의 비율 (상관)
