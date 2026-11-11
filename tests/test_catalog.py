"""
catalog 모듈 테스트 — 자료별 갱신 방식 표

이 파일은 무엇을 검증하나요?
1. 자료마다 갱신 방식(다시 받음 · 덧붙이기 · 고정)이 계획서의 표와 같은가? (결정 Q20 · Q36, verify-lab 몫 Q9)
2. 새로 붙는 날 검사의 짝 · 배율이 결정대로인가? (결정 Q29 · Q30 · Q31) 짝은 표 안의, 고정이 아닌 자료인가?
3. 자료마다 저장 파일이 가격 기준을 이름에 담은 경로인가? (결정 Q10 · Q33) 국내 ETF 는 원본가와 야후 분배 기록인가?
4. 표 안의 연결(짝 · 레버리지 합성의 실물)이 표 안의 자료를 가리키는가?

왜 중요한가요?
갱신 방식은 이 표 한 곳에서 정한다. 고정 자료가 다시 받음으로 바뀌면 쓰는 곳 없는 자료가 갱신마다 판정에 걸려 멈추고,
짝 · 배율이 틀리면 정상인 날이 멈추거나 오류인 날이 통과한다 — 둘 다 에러 없이 일어난다.
"""

from pathlib import Path

import pytest

from quant_data.catalog import CATALOG, Kind, Method, kr_adjusted_path
from quant_data.leveraged.constants import LEVERAGED_SYNTHETIC_TARGETS

BY_NAME = {dataset.name: dataset for dataset in CATALOG}

US_LEVERAGED_INVERSE = ("DDM", "DOG", "DXD", "PSQ", "QID", "SDOW", "SDS", "SH", "SPXU", "SQQQ", "UDOW")
KR_ETFS = ("069500", "114800", "122630", "229200", "233740", "251340", "252670", "261240", "261250")
KR_INDEXES = ("1001", "1028", "2001", "2203")
KR_NAVS = ("261240_NAV", "261250_NAV")
COIN_METRICS = ("BTC_PriceUSD", "BTC_CapMVRVCur", "BTC_CapMrktCurUSD")


class TestMethods:
    """자료별 갱신 방식"""

    def test_method_by_name(self) -> None:
        """
        목적: 자료마다 갱신 방식을 고정한다 — 쓰는 곳이 없으면 고정이 기본(Q20), 짝 대조에 쓰이는 지수 · ETF 는 덧붙이기 ·
              다시 받음(Q29 · Q31), 월별 금리 · 비트코인은 새 날을 받아 붙인다(Q36 · 3장 표)

        Given: 자료별 갱신 방식 표
        When: 이름별 방식을 모은다
        Then: 3장 「자료별 갱신 방식」 표와 같다
        """
        # When
        method_by_name = {name: dataset.method for name, dataset in BY_NAME.items()}

        # Then
        expected = {
            name: Method.REFETCH
            for name in ("SPY", "QQQ", "GLD", "TLT", "TQQQ", "SSO", "QLD", "UPRO", "IAU", "SPTL", "DIA")
        }
        expected |= {name: Method.APPEND for name in ("^NDX", "^GSPC", "^DJI", "^IXIC", "FFR", "BTCUSD", *COIN_METRICS)}
        expected |= {
            name: Method.FIXED
            for name in (
                "VFINX",
                "VUSTX",
                "GC=F",
                "UOPIX",
                "ULPIX",
                "RYNVX",
                "PERTH_GOLD",
                "AUD_USD",
                "EXPENSE",
                *US_LEVERAGED_INVERSE,
                *KR_ETFS,
                *KR_INDEXES,
                *KR_NAVS,
            )
        }
        assert method_by_name == expected

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

    def test_krx_kinds_are_fixed(self) -> None:
        """
        목적: KRX 자료(국내 ETF · 지수 · NAV)는 고정이다 — 다시 받을 때의 판정이 없고, 국내 합성(2단계)을 만들 때 바꾼다

        Given: 자료별 갱신 방식 표
        When: KRX 종류의 방식을 모은다
        Then: 모두 고정
        """
        # When
        methods = {d.method for d in CATALOG if d.kind in (Kind.KRX_ETF, Kind.KRX_INDEX, Kind.KRX_NAV)}

        # Then
        assert methods == {Method.FIXED}


class TestNewDayChecks:
    """새로 붙는 날 검사의 짝 · 배율 (판정 규칙 ②)"""

    def test_pair_and_leverage_by_name(self) -> None:
        """
        목적: 짝과 배율을 고정한다 — QQQ · QLD · TQQQ 는 나스닥100 지수, SPY · SSO · UPRO 는 S&P500 지수, DIA 는 다우 지수,
              GLD 는 IAU, TLT 는 SPTL 에 견주고(Q29 · Q31), 비트코인 Bitstamp 일봉은 Coin Metrics 기준가에 견준다(Q6).
              배율이 틀리면 기준(배율 × 1%p)과 견줄 수익률이 함께 틀린다

        Given: 자료별 갱신 방식 표
        When: 짝이 있는 자료의 (짝, 배율)을 모은다
        Then: 정해진 짝 · 배율
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
            "DIA": ("^DJI", 1.0),
            "GLD": ("IAU", 1.0),
            "TLT": ("SPTL", 1.0),
            "BTCUSD": ("BTC_PriceUSD", 1.0),
        }

    def test_pairs_are_fetched_catalog_datasets(self) -> None:
        """
        목적: 짝은 표 안의 자료이고 고정이 아니다 — 짝을 받지 않으면 새로 붙는 날의 짝 값이 없어 모든 날이 멈춘다

        Given: 짝이 있는 자료들
        When: 짝 이름으로 표를 찾는다
        Then: 짝마다 표에 있고 고정이 아니다
        """
        # When
        pair_names = {d.pair for d in CATALOG if d.pair is not None}

        # Then
        for pair in pair_names:
            assert pair in BY_NAME
            assert BY_NAME[pair].method is not Method.FIXED


class TestFiles:
    """자료별 저장 파일 — 가격 기준이 이름에 들어간 저장소 루트 기준 경로"""

    @pytest.mark.parametrize(
        ("name", "files"),
        [
            ("QQQ", ("storage/prices/QQQ_raw.csv", "storage/prices/QQQ_adjusted.csv")),
            ("TQQQ", ("storage/prices/TQQQ_raw.csv", "storage/prices/TQQQ_adjusted.csv")),
            ("SQQQ", ("storage/prices/SQQQ_raw.csv", "storage/prices/SQQQ_adjusted.csv")),
            ("^NDX", ("storage/prices/^NDX_raw.csv",)),
            ("^DJI", ("storage/prices/^DJI_raw.csv",)),
            ("VFINX", ("storage/prices/VFINX_adjusted.csv",)),
            ("GC=F", ("storage/prices/GC=F_adjusted.csv",)),
            ("FFR", ("storage/series/federal_funds_rate_monthly.csv",)),
            ("EXPENSE", ("storage/series/tqqq_net_expense_ratio_monthly.csv",)),
            ("PERTH_GOLD", ("storage/series/perth_mint_gold_daily.csv",)),
            ("AUD_USD", ("storage/series/aud_usd_daily.csv",)),
            ("069500", ("storage/prices/069500_raw.csv", "storage/series/069500_yahoo_dividends.csv")),
            ("1028", ("storage/series/1028_index.csv",)),
            ("261240_NAV", ("storage/series/261240_NAV.csv",)),
            ("BTCUSD", ("storage/prices/BTCUSD_raw.csv",)),
            ("BTC_PriceUSD", ("storage/series/BTC_PriceUSD.csv",)),
        ],
    )
    def test_files_by_name(self, name: str, files: tuple[str, ...]) -> None:
        """
        목적: 자료마다 저장 파일을 고정한다 — 다시 받는 · 처음 받는 미국 ETF 는 한 응답에서 원본가 · 수정주가 둘, 지수는
              원본가 하나, 고정 펀드 · 금 선물은 quant 첫 판 그대로 수정주가 하나, 국내 ETF 는 KRX 원본가와 야후 분배 기록
              (수정주가는 가공), 국내 지수 · NAV · Coin Metrics 는 하루 한 값 계열, 비트코인 일봉은 원본가

        Given: 자료별 갱신 방식 표
        When: 이름으로 파일을 찾는다
        Then: 정해진 경로
        """
        # When
        actual = BY_NAME[name].files

        # Then
        assert actual == tuple(Path(file) for file in files)

    def test_kr_adjusted_path(self) -> None:
        """
        목적: 국내 수정주가(가공)는 원본가와 같은 폴더의 `_adjusted` 다 — 미국 수정주가와 같은 이름 규칙

        Given: 069500
        When: kr_adjusted_path
        Then: storage/prices/069500_adjusted.csv
        """
        assert kr_adjusted_path("069500") == Path("storage/prices/069500_adjusted.csv")

    def test_kind_by_name(self) -> None:
        """
        목적: 받는 방식(종류)을 고정한다 — 종류가 받기 함수와 판정을 고른다

        Given: 자료별 갱신 방식 표
        When: 이름별 종류를 모은다
        Then: 지수는 야후 지수, 금리 · 운용비율 · 금값 · 환율은 각자의 종류, KRX · 비트코인은 각자의 종류, 나머지는 야후 ETF · 펀드
        """
        # When
        kinds = {name: d.kind for name, d in BY_NAME.items()}

        # Then
        expected = {name: Kind.YAHOO_FUND for name in BY_NAME}
        expected |= {name: Kind.YAHOO_INDEX for name in ("^NDX", "^GSPC", "^DJI", "^IXIC")}
        expected |= {
            "FFR": Kind.FRED_MONTHLY,
            "EXPENSE": Kind.MANUAL_MONTHLY,
            "PERTH_GOLD": Kind.PERTH_GOLD,
            "AUD_USD": Kind.FRED_DAILY,
            "BTCUSD": Kind.BITSTAMP,
        }
        expected |= {name: Kind.KRX_ETF for name in KR_ETFS}
        expected |= {name: Kind.KRX_INDEX for name in KR_INDEXES}
        expected |= {name: Kind.KRX_NAV for name in KR_NAVS}
        expected |= {name: Kind.COINMETRICS for name in COIN_METRICS}
        assert kinds == expected

    def test_series_decimals(self) -> None:
        """
        목적: 하루 한 값 계열의 저장 자릿수 — Coin Metrics 기준가는 시세처럼 6자리, MVRV 는 배수라 4자리, 시가총액은 달러라 0자리

        Given: 자료별 갱신 방식 표
        When: Coin Metrics 자료의 자릿수를 모은다
        Then: 6 · 4 · 0
        """
        # When
        decimals = {name: BY_NAME[name].decimals for name in COIN_METRICS}

        # Then
        assert decimals == {"BTC_PriceUSD": 6, "BTC_CapMVRVCur": 4, "BTC_CapMrktCurUSD": 0}

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
