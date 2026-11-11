"""
catalog 모듈 테스트 — 자료별 갱신 방식 표

이 파일은 무엇을 검증하나요?
1. 자료마다 갱신 방식(다시 받음 · 덧붙이기 · 고정)이 계획서의 표와 같은가? (결정 Q20 · Q36)
2. 새로 붙는 날 검사의 짝 · 배율이 결정대로인가? (결정 Q29 · Q30) 짝이 없는 금 · 장기채만 하루 변동 50% 인가? (결정 Q27)
3. 자료마다 저장 파일이 가격 기준을 이름에 담은 경로인가? (결정 Q10 · Q33)
4. 표 안의 연결(짝 · 레버리지 합성의 실물)이 표 안의 자료를 가리키는가?

왜 중요한가요?
갱신 방식은 이 표 한 곳에서 정한다. 고정 자료가 다시 받음으로 바뀌면 쓰는 곳 없는 자료가 갱신마다 판정에 걸려 멈추고,
짝 · 배율이 틀리면 정상인 날이 멈추거나 오류인 날이 통과한다 — 둘 다 에러 없이 일어난다.
"""

from pathlib import Path

import pytest

from quant_data.catalog import CATALOG, Kind, Method
from quant_data.leveraged.constants import LEVERAGED_SYNTHETIC_TARGETS
from quant_data.new_days import TEMP_DAILY_MOVE_LIMIT

BY_NAME = {dataset.name: dataset for dataset in CATALOG}


class TestMethods:
    """자료별 갱신 방식"""

    def test_method_by_name(self) -> None:
        """
        목적: 자료마다 갱신 방식을 고정한다 — 쓰는 곳이 없으면 고정이 기본(Q20), 나스닥100 · S&P500 지수는 짝 대조에 쓰여
              덧붙이기(Q20 예외 · Q29), 월별 금리는 새로 나온 달을 받아 붙인다(Q36)

        Given: 자료별 갱신 방식 표
        When: 이름별 방식을 모은다
        Then: quant 몫 실물 8종 다시 받음, 지수 둘 · 월별 금리 덧붙이기, 합성 재료 · 검증용 펀드 고정
        """
        # When
        method_by_name = {name: dataset.method for name, dataset in BY_NAME.items()}

        # Then
        assert method_by_name == {
            "SPY": Method.REFETCH,
            "QQQ": Method.REFETCH,
            "GLD": Method.REFETCH,
            "TLT": Method.REFETCH,
            "TQQQ": Method.REFETCH,
            "SSO": Method.REFETCH,
            "QLD": Method.REFETCH,
            "UPRO": Method.REFETCH,
            "^NDX": Method.APPEND,
            "^GSPC": Method.APPEND,
            "FFR": Method.APPEND,
            "VFINX": Method.FIXED,
            "VUSTX": Method.FIXED,
            "GC=F": Method.FIXED,
            "UOPIX": Method.FIXED,
            "ULPIX": Method.FIXED,
            "RYNVX": Method.FIXED,
            "PERTH_GOLD": Method.FIXED,
            "AUD_USD": Method.FIXED,
            "EXPENSE": Method.FIXED,
        }

    def test_names_are_unique(self) -> None:
        """
        목적: 자료 이름은 하나뿐이다 — --exclude · --accept · 패스 목록이 이름으로 자료를 가리킨다

        Given: 자료별 갱신 방식 표
        When: 이름을 센다
        Then: 중복 없음
        """
        # When
        names = [dataset.name for dataset in CATALOG]

        # Then
        assert len(names) == len(set(names))


class TestNewDayChecks:
    """새로 붙는 날 검사의 짝 · 배율 (판정 규칙 ②)"""

    def test_pair_and_leverage_by_name(self) -> None:
        """
        목적: 짝과 배율을 고정한다 — QQQ · QLD · TQQQ 는 나스닥100 지수, SPY · SSO · UPRO 는 S&P500 지수에
              배율 1 · 2 · 3 으로 견준다 (Q29). 배율이 틀리면 기준(배율 × 1%p)과 견줄 수익률이 함께 틀린다

        Given: 자료별 갱신 방식 표
        When: 짝이 있는 자료의 (짝, 배율)을 모은다
        Then: 여섯 종목, 정해진 짝 · 배율
        """
        # When
        pairs = {name: (d.pair, d.leverage) for name, d in BY_NAME.items() if d.pair is not None}

        # Then
        assert pairs == {
            "QQQ": ("^NDX", 1.0),
            "QLD": ("^NDX", 2.0),
            "TQQQ": ("^NDX", 3.0),
            "SPY": ("^GSPC", 1.0),
            "SSO": ("^GSPC", 2.0),
            "UPRO": ("^GSPC", 3.0),
        }

    def test_pairs_are_appended_indexes_in_catalog(self) -> None:
        """
        목적: 짝은 표 안의 야후 지수이고 고정이 아니다 — 짝을 받지 않으면 새로 붙는 날의 짝 값이 없어 모든 날이 멈춘다

        Given: 짝이 있는 자료들
        When: 짝 이름으로 표를 찾는다
        Then: 짝마다 야후 지수 · 덧붙이기
        """
        # When
        pair_names = {d.pair for d in CATALOG if d.pair is not None}

        # Then
        for pair in pair_names:
            assert BY_NAME[pair].kind is Kind.YAHOO_INDEX
            assert BY_NAME[pair].method is Method.APPEND

    def test_daily_move_limit_only_for_unpaired_gold_and_bonds(self) -> None:
        """
        목적: 하루 변동 50% 검사는 짝이 정해지기 전의 금 · 장기채에만 임시로 남는다 (Q27) — 짝이 있는 종목에 함께 걸면
              짝 대조가 놓아준 실제 급락일이 50% 에서 다시 멈출 수 있고, 50% 의 근거 기록은 없다

        Given: 자료별 갱신 방식 표
        When: 하루 변동 한도가 있는 자료를 모은다
        Then: GLD · TLT 둘, 한도 TEMP_DAILY_MOVE_LIMIT · 짝 없음
        """
        # When
        limits = {name: d.daily_move_limit for name, d in BY_NAME.items() if d.daily_move_limit is not None}

        # Then
        assert limits == {"GLD": TEMP_DAILY_MOVE_LIMIT, "TLT": TEMP_DAILY_MOVE_LIMIT}
        assert BY_NAME["GLD"].pair is None
        assert BY_NAME["TLT"].pair is None

    def test_temp_daily_move_limit_is_half(self) -> None:
        """
        목적: 임시 한도는 하루 50% 다 (비율 0.5) — quant 의 저장 거부 기준 그대로 옮긴 값이고 근거 기록은 없다(Q27)

        Given: 임시 한도 상수
        When: 비교
        Then: 0.5
        """
        # Then
        assert TEMP_DAILY_MOVE_LIMIT == 0.5


class TestFiles:
    """자료별 저장 파일 — 가격 기준이 이름에 들어간 저장소 루트 기준 경로"""

    @pytest.mark.parametrize(
        ("name", "files"),
        [
            ("QQQ", ("storage/prices/QQQ_raw.csv", "storage/prices/QQQ_adjusted.csv")),
            ("TQQQ", ("storage/prices/TQQQ_raw.csv", "storage/prices/TQQQ_adjusted.csv")),
            ("^NDX", ("storage/prices/^NDX_raw.csv",)),
            ("^GSPC", ("storage/prices/^GSPC_raw.csv",)),
            ("VFINX", ("storage/prices/VFINX_adjusted.csv",)),
            ("GC=F", ("storage/prices/GC=F_adjusted.csv",)),
            ("FFR", ("storage/series/federal_funds_rate_monthly.csv",)),
            ("EXPENSE", ("storage/series/tqqq_net_expense_ratio_monthly.csv",)),
            ("PERTH_GOLD", ("storage/series/perth_mint_gold_daily.csv",)),
            ("AUD_USD", ("storage/series/aud_usd_daily.csv",)),
        ],
    )
    def test_files_by_name(self, name: str, files: tuple[str, ...]) -> None:
        """
        목적: 자료마다 저장 파일을 고정한다 — 다시 받는 ETF 는 한 응답에서 원본가 · 수정주가 둘, 지수는 배당이 빠진 가격지수라
              원본가 하나, 고정 펀드 · 금 선물은 quant 첫 판 그대로 수정주가 하나, 한 값짜리 계열은 quant 의 이름 그대로

        Given: 자료별 갱신 방식 표
        When: 이름으로 파일을 찾는다
        Then: 정해진 경로
        """
        # When
        actual = BY_NAME[name].files

        # Then
        assert actual == tuple(Path(file) for file in files)

    def test_kind_by_name(self) -> None:
        """
        목적: 받는 방식(종류)을 고정한다 — 종류가 받기 함수와 판정을 고른다

        Given: 자료별 갱신 방식 표
        When: 이름별 종류를 모은다
        Then: 지수 둘은 야후 지수, 월별 금리는 FRED 월별, 운용비율은 손 갱신, 금값 · 환율은 각자의 종류, 나머지는 야후 ETF · 펀드
        """
        # When
        kinds = {name: d.kind for name, d in BY_NAME.items()}

        # Then
        expected = {name: Kind.YAHOO_FUND for name in BY_NAME}
        expected |= {
            "^NDX": Kind.YAHOO_INDEX,
            "^GSPC": Kind.YAHOO_INDEX,
            "FFR": Kind.FRED_MONTHLY,
            "EXPENSE": Kind.MANUAL_MONTHLY,
            "PERTH_GOLD": Kind.PERTH_GOLD,
            "AUD_USD": Kind.FRED_DAILY,
        }
        assert kinds == expected

    def test_leveraged_actuals_are_catalog_files(self) -> None:
        """
        목적: 레버리지 합성이 잇는 실물은 표가 받는 파일이다 — 표 밖의 파일을 이으면 그 실물은 갱신되지 않아 합성이 낡는다

        Given: 레버리지 합성 상품 표, 자료별 갱신 방식 표의 모든 파일
        When: 상품마다 실물 경로를 찾는다
        Then: 모두 표 안에 있다
        """
        # Given
        catalog_files = {file for dataset in CATALOG for file in dataset.files}

        # When
        actuals = [actual for _, _, actual, _, _ in LEVERAGED_SYNTHETIC_TARGETS]

        # Then
        assert all(actual in catalog_files for actual in actuals)
