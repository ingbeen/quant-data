"""레버리지 합성 상수 — 상품 표, 비용 모델 기본값 · 가산금리 상한, 월별 CSV 열 이름."""

from typing import Final

from quant_data.prices import PriceBasis, price_path

# ============================================================
# 레버리지 상품
# ============================================================

DEFAULT_LEVERAGE_MULTIPLIER: Final = 3.0  # 3배 레버리지
LEVERAGE_2X: Final = 2.0  # 2배 레버리지

# 레버리지 합성 상품 — (상품 이름, 기초 시세, 실물 시세, 배율, 합성 파일). 한 줄에 상품 하나의 연결을 모두 둠
# → 기초 · 저장 경로가 다른 상품과 섞이지 않음. 실물은 수정주가 — 이음매 뒤 행이 실물 행 그대로라 원본가를 이으면 배당이 빠짐
LEVERAGED_SYNTHETIC_TARGETS: Final = (
    (
        "TQQQ",
        price_path("QQQ", PriceBasis.SYNTHETIC),
        price_path("TQQQ", PriceBasis.ADJUSTED),
        DEFAULT_LEVERAGE_MULTIPLIER,
        price_path("TQQQ", PriceBasis.SYNTHETIC),
    ),
    (
        "QLD",
        price_path("QQQ", PriceBasis.SYNTHETIC),
        price_path("QLD", PriceBasis.ADJUSTED),
        LEVERAGE_2X,
        price_path("QLD", PriceBasis.SYNTHETIC),
    ),
    (
        "SSO",
        price_path("SPY", PriceBasis.SYNTHETIC),
        price_path("SSO", PriceBasis.ADJUSTED),
        LEVERAGE_2X,
        price_path("SSO", PriceBasis.SYNTHETIC),
    ),
    (
        "UPRO",
        price_path("SPY", PriceBasis.SYNTHETIC),
        price_path("UPRO", PriceBasis.ADJUSTED),
        DEFAULT_LEVERAGE_MULTIPLIER,
        price_path("UPRO", PriceBasis.SYNTHETIC),
    ),
)

# ============================================================
# 비용 모델 파라미터
# ============================================================

DEFAULT_PRE_LISTING_EXPENSE_RATIO: Final = 0.0095  # TQQQ 상장 이전 운용비율 가정값 (0.0095 = 0.95%)

# --- Softplus 동적 스프레드 — 전체기간 튜닝 최적값 (스프레드 랩 튜닝 결과의 RMSE 최소 행) ---
DEFAULT_SOFTPLUS_A: Final = -6.1  # softplus 절편 파라미터
DEFAULT_SOFTPLUS_B: Final = 0.37  # softplus 기울기 파라미터

# --- 가산금리 상한 (docs/research/합성_시세_연장.md 결정 4) ---
# 맞춘 범위(금리 5.33%) 밖 고금리에서 softplus 가 지수처럼 부풂 → 1999년 전 달에만 막음.
# 마지막 달을 1999 이후로 밀면 기존 합성의 1999년 이후 값이 바뀜 (사용자 결정 2026-11-05)
SPREAD_CAP: Final = 0.016  # 비율 (0.016 = 1.6%)
SPREAD_CAP_LAST_MONTH: Final = "1998-12"

# ============================================================
# 월별 CSV 열
# ============================================================

COL_FFR_DATE: Final = "DATE"  # FFR CSV의 날짜 컬럼
COL_FFR_VALUE: Final = "VALUE"  # FFR CSV의 금리 값 컬럼
COL_EXPENSE_DATE: Final = "DATE"  # Expense Ratio CSV의 날짜 컬럼
COL_EXPENSE_VALUE: Final = "VALUE"  # Expense Ratio CSV의 값 컬럼

# 월별 딕셔너리를 문자열 비교로 가름 → 모양이 다르면 조용히 틀림
MONTH_KEY_PATTERN: Final = r"\d{4}-(0[1-9]|1[0-2])"
