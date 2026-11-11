"""테스트 공통 픽스처 — 여러 테스트 파일이 같은 모양의 시세 · 월별 데이터를 쓴다."""

from datetime import date

import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME


@pytest.fixture
def sample_stock_df() -> pd.DataFrame:
    """3행 시세 (Date, Open, High, Low, Close, Volume) — 테스트마다 새 복사본."""
    return pd.DataFrame(
        {
            COL_DATE: [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
            COL_OPEN: [100.0, 101.0, 102.0],
            COL_HIGH: [105.0, 106.0, 107.0],
            COL_LOW: [99.0, 100.0, 101.0],
            COL_CLOSE: [103.0, 104.0, 105.0],
            COL_VOLUME: [1000000, 1100000, 1200000],
        }
    )


@pytest.fixture
def sample_ffr_df() -> pd.DataFrame:
    """월별 금리 (DATE: yyyy-mm 문자열, VALUE: 0~1 비율).

    열 이름을 리터럴로 둔다 — 저장 파일 형식이 바뀌면 이 픽스처가 잡는다.
    """
    return pd.DataFrame({"DATE": ["2023-01", "2023-02", "2023-03"], "VALUE": [0.045, 0.046, 0.047]})
