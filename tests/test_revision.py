"""
revision 모듈 테스트 — 다시 받은 시세를 기존 파일과 견주는 판정 (판정 규칙 ①)

이 파일은 무엇을 검증하나요?
1. 흔들림뿐이면 기존 행을 그대로 두고 새 날짜 행만 붙이는가?
2. 응답의 배당 기록으로 설명되는 변화면 응답으로 덮어쓰는가? (기존 파일이 잘라낸 날의 배당을 이미 반영한 경우 포함)
3. 그 밖(배당 빠짐 · 금액 바뀜 · 기록 없는 변화 · 일부 열만 바뀜 · 날짜 변화 · 작은 변화의 누적)은 비정상인가?
4. 분할은 기록과 맞아도 비정상이고 원인 줄에 「분할로 보이는 변화」를 적는가? (결정 Q23)
5. 원본가는 배당 기록으로 설명되지 않는가? (야후 원본가는 분할만 과거에 반영된다)
6. 비정상 원인 블록이 짧고, 그대로 AI 에 붙여 넣을 수 있으며 --accept · --exclude 의 뜻을 적는가? (결정 Q16)

왜 중요한가요?
야후는 수정 종가를 요청마다 미세하게 다르게 주고, 배당 기록을 늦게 넣거나 넣었다가 빼기도 한다.
판정이 틀리면 흔들림이 받을 때마다 수만 행 diff 로 들어오거나, 배당이 빠진 시세가 조용히 덮어써진다
(근거: quant docs/research/합성_시세_연장.md 결정 14). 분할은 사람이 운용사 공시와 비율을 맞춰 본 뒤에만 받아들인다.
"""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant_data.constants import COL_CLOSE, COL_DATE, COL_HIGH, COL_LOW, COL_OPEN, COL_VOLUME, PRICE_COLUMNS
from quant_data.revision import (
    PriceEvents,
    PriceRevision,
    RevisionKind,
    format_abnormal_block,
    judge_revision,
)

DECIMALS = 6  # 저장된 기존 파일의 가격 자릿수
DATES: list[date] = [d.date() for d in pd.bdate_range("2026-01-05", periods=10)]  # 2026-01-05 ~ 01-16 평일
RAW_CLOSE: list[float] = [100.0 + i for i in range(10)]


def _factors(dividends: dict[date, float] | None = None, splits: dict[date, float] | None = None) -> np.ndarray:
    """야후 방식의 누적 조정 비율 — 배당락일 앞 행에 (1 − 배당 ÷ 전날 원시 종가), 분할일 앞 행에 1 ÷ 배수를 곱한다."""
    factors = np.ones(len(DATES))
    for day, amount in (dividends or {}).items():
        i = DATES.index(day)
        factors[:i] *= 1 - amount / RAW_CLOSE[i - 1]
    for day, ratio in (splits or {}).items():
        i = DATES.index(day)
        factors[:i] *= 1 / ratio
    return factors


def _prices(closes: np.ndarray | list[float], dates: list[date] | None = None) -> pd.DataFrame:
    """종가로 만든 시세 — 시가 · 고가 · 저가는 종가의 고정 배수라 조정 비율이 네 열에 똑같이 걸린다."""
    close_array = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            COL_DATE: dates if dates is not None else DATES[: len(close_array)],
            COL_OPEN: close_array * 0.99,
            COL_HIGH: close_array * 1.01,
            COL_LOW: close_array * 0.98,
            COL_CLOSE: close_array,
            COL_VOLUME: 1000,
        }
    )


def _adjusted(dividends: dict[date, float] | None = None, splits: dict[date, float] | None = None) -> pd.DataFrame:
    """원시 종가에 야후 방식의 조정 비율을 곱한 시세."""
    return _prices(np.array(RAW_CLOSE) * _factors(dividends, splits))


def _stored(frame: pd.DataFrame, rows: int | None = None) -> pd.DataFrame:
    """저장된 기존 파일처럼 — 앞 rows 행, 가격 6자리."""
    stored = frame.iloc[:rows].copy() if rows is not None else frame.copy()
    stored[PRICE_COLUMNS] = stored[PRICE_COLUMNS].round(DECIMALS)
    return stored.reset_index(drop=True)


def _row_scale(row: int, factor: float) -> np.ndarray:
    """한 행만 factor 배인 10행 배수."""
    scale = np.ones(len(DATES))
    scale[row] = factor
    return scale


def _events(dividends: dict[date, float] | None = None, splits: dict[date, float] | None = None) -> PriceEvents:
    return PriceEvents(
        dividends=pd.Series(dividends or {}, dtype=float),
        splits=pd.Series(splits or {}, dtype=float),
        raw_close=pd.Series(RAW_CLOSE, index=DATES, dtype=float),
    )


def _judge(
    existing: pd.DataFrame | None,
    response: pd.DataFrame,
    events: PriceEvents | None = None,
    *,
    explain_dividends: bool = True,
) -> PriceRevision:
    return judge_revision(
        existing,
        response,
        events if events is not None else _events(),
        price_decimals=DECIMALS,
        explain_dividends=explain_dividends,
    )


class TestNewAndNoise:
    """기존 파일이 없을 때와 흔들림뿐일 때"""

    def test_new_file_without_existing(self) -> None:
        """
        목적: 기존 파일이 없으면 응답 그대로 새 파일로 쓴다

        Given: 기존 없음, 응답 10행
        When: judge_revision
        Then: NEW, 저장할 표 = 응답, 기존 끝날 없음 · 행 0
        """
        # Given
        response = _prices(RAW_CLOSE)

        # When
        revision = _judge(None, response)

        # Then
        assert revision.kind is RevisionKind.NEW
        pd.testing.assert_frame_equal(revision.prices, response)
        assert revision.existing_end is None
        assert revision.existing_rows == 0
        assert (revision.response_end, revision.response_rows) == (date(2026, 1, 16), 10)

    def test_noise_keeps_existing_rows_and_appends_new_dates(self) -> None:
        """
        목적: 흔들림뿐이면 기존 행은 한 글자도 바꾸지 않고 응답의 새 날짜 행만 붙인다 — 받을 때마다 생기던 diff 를 막는다

        Given: 기존 8행(6자리), 응답 10행 = 같은 시세에 상대 ±4e-6 흔들림 (관측 최대 4.2e-6 수준)
        When: judge_revision
        Then: NOISE, 저장할 표 = 기존 8행 + 응답의 9 · 10번째 행
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        wobble = 1 + 4e-6 * np.array([(-1) ** i for i in range(10)])
        response = _prices(np.array(RAW_CLOSE) * wobble)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.NOISE
        expected = pd.concat([existing, response.iloc[8:]], ignore_index=True)
        pd.testing.assert_frame_equal(revision.prices, expected)

    @pytest.mark.parametrize(
        ("relative_change", "expected_kind"),
        [(1.9e-5, RevisionKind.NOISE), (2.2e-5, RevisionKind.ABNORMAL)],
    )
    def test_noise_tolerance_boundary(self, relative_change: float, expected_kind: RevisionKind) -> None:
        """
        목적: 흔들림 상한(상대 2e-5)의 양쪽 — 아래면 흔들림, 위면 기록 없는 변화라 비정상

        Given: 기존 10행, 응답은 다섯째 행만 네 가격 모두 relative_change 만큼 다르다
        When: judge_revision
        Then: 1.9e-5 → NOISE, 2.2e-5 → ABNORMAL
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(RAW_CLOSE)
        response[PRICE_COLUMNS] = response[PRICE_COLUMNS].to_numpy() * _row_scale(4, 1 + relative_change)[:, None]

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is expected_kind

    def test_small_prices_use_rounding_floor(self) -> None:
        """
        목적: 아주 작은 가격은 6자리 반올림 반 단위까지 흔들림으로 본다 — 상대 차만 보면 반올림 잡음을 변화로 읽는다

        Given: 종가 0.010 ~ 0.019 (6자리로 저장), 응답 = 상대 +4e-5 (상한의 2배지만 절대 차 4e-7 ~ 7.7e-7 — 반 단위 5e-7 + 상한 몫 안)
        When: judge_revision
        Then: NOISE
        """
        # Given
        closes = np.array([0.01 + 0.001 * i for i in range(10)])
        existing = _stored(_prices(closes))
        response = _prices(closes * (1 + 4e-5))

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.NOISE


class TestExplained:
    """응답의 배당 기록으로 설명되는 변화 → 응답으로 덮어쓴다"""

    def test_dividend_added_inside_overlap(self) -> None:
        """
        목적: 늦게 들어온 배당(기존에 없던 겹친 기간 안의 배당)은 정상 변화로 받아들인다 — 2026 TLT 02-02 · VUSTX 09-30 모양

        Given: 기존 = 배당 없는 10행, 응답 = 2026-01-12 배당 $0.50 이 반영된 10행과 그 기록
        When: judge_revision
        Then: EXPLAINED, 저장할 표 = 응답, 반영 기록에 그날 · 금액
        """
        # Given
        dividend = {DATES[5]: 0.5}
        existing = _stored(_prices(RAW_CLOSE))
        response = _adjusted(dividends=dividend)

        # When
        revision = _judge(existing, response, _events(dividends=dividend))

        # Then
        assert revision.kind is RevisionKind.EXPLAINED
        pd.testing.assert_frame_equal(revision.prices, response)
        assert any("2026-01-12" in line and "$0.500" in line for line in revision.applied)

    def test_dividend_after_existing_end(self) -> None:
        """
        목적: 기존 끝날 뒤의 새 배당은 겹친 행 전체를 같은 비율로 낮춘다 — 그 비율이 기록과 맞으면 정상

        Given: 기존 8행(01-05 ~ 01-14), 응답 10행 = 2026-01-16 배당 $0.50 이 반영된 시세와 그 기록
        When: judge_revision
        Then: EXPLAINED, 반영 기록에 2026-01-16
        """
        # Given
        dividend = {DATES[9]: 0.5}
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _adjusted(dividends=dividend)

        # When
        revision = _judge(existing, response, _events(dividends=dividend))

        # Then
        assert revision.kind is RevisionKind.EXPLAINED
        assert any("2026-01-16" in line for line in revision.applied)

    def test_dividend_in_trimmed_days_already_in_existing(self) -> None:
        """
        목적: 기존 파일이 잘라낸 날의 배당을 이미 반영했으면 그 배당을 뺀 나머지 기록으로 맞춘다 —
              TLT 2026-05-02 → 07-26 커밋 모양(05-02 커밋본이 05-01 배당을 이미 반영)

        Given: 기존 6행(~ 01-12) = 01-13 배당 $0.50 이 반영된 시세, 응답 10행 = 01-13 $0.50 · 01-15 $0.40 이 반영된 시세와 두 기록
        When: judge_revision
        Then: EXPLAINED, 반영 기록에 01-15 만 (01-13 은 기존이 이미 반영)
        """
        # Given
        first = {DATES[6]: 0.5}
        both = {**first, DATES[8]: 0.4}
        existing = _stored(_adjusted(dividends=first), rows=6)
        response = _adjusted(dividends=both)

        # When
        revision = _judge(existing, response, _events(dividends=both))

        # Then
        assert revision.kind is RevisionKind.EXPLAINED
        assert any("2026-01-15" in line for line in revision.applied)
        assert not any("2026-01-13" in line for line in revision.applied)

    def test_late_dividend_inside_and_new_dividend_after_end_together(self) -> None:
        """
        목적: 겹친 기간 안의 늦은 배당과 기존 끝날 뒤의 새 배당이 한 응답에 함께 와도 둘 다 기록으로 맞춘다 —
              기존 파일이 몇 달 묵었을 때의 흔한 모양

        Given: 기존 8행(~ 01-14, 배당 없음), 응답 10행 = 01-08 $0.30 · 01-16 $0.50 이 반영된 시세와 두 기록
        When: judge_revision
        Then: EXPLAINED, 반영 기록에 01-08 · 01-16 둘 다
        """
        # Given
        dividends = {DATES[3]: 0.3, DATES[9]: 0.5}
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _adjusted(dividends=dividends)

        # When
        revision = _judge(existing, response, _events(dividends=dividends))

        # Then
        assert revision.kind is RevisionKind.EXPLAINED
        assert any("2026-01-08" in line for line in revision.applied)
        assert any("2026-01-16" in line for line in revision.applied)

    def test_record_on_existing_last_day(self) -> None:
        """
        목적: 기록 날짜가 기존 끝날과 같으면 겹친 기간의 계단(끝날 앞 행들)으로 맞춘다 — 계단과 끝 구간의 경계

        Given: 기존 8행(~ 01-14), 응답 = 01-14 배당 $0.40 이 반영된 10행과 그 기록
        When: judge_revision
        Then: EXPLAINED, 반영 기록에 「2026-01-14」 · 「이전 7행」
        """
        # Given
        dividend = {DATES[7]: 0.4}
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _adjusted(dividends=dividend)

        # When
        revision = _judge(existing, response, _events(dividends=dividend))

        # Then
        assert revision.kind is RevisionKind.EXPLAINED
        assert any("2026-01-14" in line and "이전 7행" in line for line in revision.applied)


class TestSplitIsAbnormal:
    """분할은 기록과 맞아도 비정상 — 사람이 운용사 공시와 날짜 · 비율을 맞춰 본 뒤 --accept 한다 (결정 Q23)"""

    @pytest.mark.parametrize(("ratio", "ratio_text"), [(2.0, "2배"), (0.2, "0.2배")])
    def test_split_record_matching_change_is_abnormal(self, ratio: float, ratio_text: str) -> None:
        """
        목적: 새 분할 기록(액면분할 2배 · 역분할 1:5)이 그날 앞 가격의 변화와 정확히 맞아도 비정상이고, 원인 줄에
              분할로 보이는 날짜 · 비율을 적는다 — 하루 급등락 검사는 2:1 분할 날 시장이 오르면 −49.x% 로 빠져나가
              분할 감지로 믿지 않는다

        Given: 기존 = 분할 전 10행, 응답 = 2026-01-12 분할이 반영된 10행과 그 기록
        When: judge_revision
        Then: ABNORMAL, 저장할 표 = 응답, 원인 줄에 「분할로 보이는 변화: 2026-01-12 · {배수} (야후 기록)」,
              split_changes = ((2026-01-12, 배수),)
        """
        # Given
        split = {DATES[5]: ratio}
        existing = _stored(_prices(RAW_CLOSE))
        response = _adjusted(splits=split)

        # When
        revision = _judge(existing, response, _events(splits=split))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        pd.testing.assert_frame_equal(revision.prices, response)
        assert any(f"분할로 보이는 변화: 2026-01-12 · {ratio_text} (야후 기록)" in line for line in revision.issues)
        assert revision.split_changes == ((DATES[5], ratio),)

    def test_split_after_existing_end_is_abnormal(self) -> None:
        """
        목적: 기존 끝날 뒤의 분할도 겹친 행 전체를 1 ÷ 배수로 바꾼다 — 그 비율이 기록과 맞아도 비정상이고 같은 원인 줄을 적는다

        Given: 기존 8행(~ 01-14), 응답 10행 = 2026-01-16 2배 분할이 반영된 시세와 그 기록
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「분할로 보이는 변화: 2026-01-16 · 2배 (야후 기록)」
        """
        # Given
        split = {DATES[9]: 2.0}
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _adjusted(splits=split)

        # When
        revision = _judge(existing, response, _events(splits=split))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("분할로 보이는 변화: 2026-01-16 · 2배 (야후 기록)" in line for line in revision.issues)
        assert revision.split_changes == ((DATES[9], 2.0),)

    def test_dividend_beside_split_is_still_explained_but_split_stops(self) -> None:
        """
        목적: 같은 응답에 배당과 분할이 함께 오면 배당은 설명된 변화로 적고, 판정은 분할 때문에 비정상이다 —
              배당까지 원인 줄에 섞으면 사람이 무엇을 공시와 맞춰야 하는지 흐려진다

        Given: 기존 = 기록 없는 10행, 응답 = 2026-01-08 배당 $0.30 · 2026-01-12 2배 분할이 반영된 10행과 두 기록
        When: judge_revision
        Then: ABNORMAL, 설명된 변화에 01-08 배당, 원인 줄은 분할 하나
        """
        # Given
        dividend = {DATES[3]: 0.3}
        split = {DATES[5]: 2.0}
        existing = _stored(_prices(RAW_CLOSE))
        response = _adjusted(dividends=dividend, splits=split)

        # When
        revision = _judge(existing, response, _events(dividends=dividend, splits=split))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("2026-01-08" in line for line in revision.applied)
        assert len(revision.issues) == 1
        assert "분할로 보이는 변화: 2026-01-12 · 2배 (야후 기록)" in revision.issues[0]


class TestRawPrices:
    """원본가 파일의 판정 — 야후 원본가는 분할만 과거에 반영되어 배당은 원본가의 변화를 설명하지 못한다"""

    def test_dividend_record_does_not_explain_raw_change(self) -> None:
        """
        목적: 원본가 판정(explain_dividends=False)은 배당 기록이 있어도 과거 가격의 변화를 설명된 변화로 받지 않는다 —
              받으면 수정주가처럼 바뀐 원본가가 조용히 덮어써진다

        Given: 기존 = 원본가 10행, 응답 = 2026-01-12 배당 $0.50 만큼 앞 행이 낮아진 10행과 그 배당 기록
        When: judge_revision(explain_dividends=False)
        Then: ABNORMAL
        """
        # Given
        dividend = {DATES[5]: 0.5}
        existing = _stored(_prices(RAW_CLOSE))
        response = _adjusted(dividends=dividend)

        # When
        revision = _judge(existing, response, _events(dividends=dividend), explain_dividends=False)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL

    def test_unchanged_raw_with_new_rows_is_noise(self) -> None:
        """
        목적: 원본가는 배당이 있어도 과거가 그대로라 흔들림뿐으로 새 날짜만 붙는다 (덧붙이기)

        Given: 기존 = 원본가 8행, 응답 = 같은 원본가 10행과 2026-01-12 배당 기록
        When: judge_revision(explain_dividends=False)
        Then: NOISE, 저장할 표 = 기존 8행 + 새 2행
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _prices(RAW_CLOSE)

        # When
        revision = _judge(existing, response, _events(dividends={DATES[5]: 0.5}), explain_dividends=False)

        # Then
        assert revision.kind is RevisionKind.NOISE
        assert revision.prices[COL_DATE].tolist() == DATES


class TestAbnormal:
    """그 밖의 변화 → 비정상, 저장할 표는 덮어쓸 때 쓸 응답"""

    def test_removed_dividend_is_abnormal_with_implied_amount(self) -> None:
        """
        목적: 기존에 반영된 배당이 응답에서 빠지면(2026-11-07 TLT 10-01 모양) 비정상 — 원인 줄에 기존이 반영했던 금액을 역산해 적는다

        Given: 기존 = 2026-01-12 배당 $0.312 가 반영된 10행, 응답 = 배당 없는 10행 · 기록 없음
        When: judge_revision
        Then: ABNORMAL, 저장할 표 = 응답, 원인 줄 「2026-01-12 이전 5행 +0.301%」 · 「배당이라면 약 $0.312」 · 「기록 없음」
              (0.312 ÷ (104 − 0.312) = 0.301% — 손 계산). 금액은 원인이 배당일 때의 추정으로 적는다 — 빠진 분할 · 정정일 수도 있다
        """
        # Given
        existing = _stored(_adjusted(dividends={DATES[5]: 0.312}))
        response = _prices(RAW_CLOSE)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        pd.testing.assert_frame_equal(revision.prices, response)
        assert len(revision.issues) == 1
        assert "2026-01-12 이전 5행 +0.301%" in revision.issues[0]
        assert "기존 가격이 응답보다 낮음(빠진 배당이라면 약 $0.312)" in revision.issues[0]
        assert "기록 없음" in revision.issues[0]

    def test_split_with_extra_change_is_abnormal(self) -> None:
        """
        목적: 분할 기록이 있어도 그날 계단에 다른 변화가 섞이면 비정상 — 기록 크기에 비례해 허용하면 2배 분할에 ±2.5% 가 묻힌다

        Given: 기존 = 분할 전 10행, 응답 = 2026-01-12 2배 분할 기록과, 그날 앞 5행이 분할에 더해 +4%
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「분할 2배」
        """
        # Given
        split = {DATES[5]: 2.0}
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(np.array(RAW_CLOSE) * _factors(splits=split) * np.array([1.04] * 5 + [1.0] * 5))

        # When
        revision = _judge(existing, response, _events(splits=split))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("분할 2배" in line for line in revision.issues)

    def test_later_records_do_not_absorb_removed_trimmed_day_dividend(self) -> None:
        """
        목적: 기존 끝날 뒤 기록이 많아도(오래 묵은 파일) 기존이 반영했던 잘라낸 날의 배당이 빠진 것을 삼키지 않는다

        Given: 기존 2행 = 01-07 배당 $0.31 이 반영된 시세(잘라낸 날의 배당), 응답 = 01-07 배당이 빠지고 01-08 ~ 01-16 에
               전날 종가의 1% 씩인 배당 7건이 반영된 10행과 그 7건의 기록
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「기존 끝날 2026-01-06」
        """
        # Given
        existing = _stored(_adjusted(dividends={DATES[2]: 0.31}), rows=2)
        later = {DATES[i]: 0.01 * RAW_CLOSE[i - 1] for i in range(3, 10)}
        response = _adjusted(dividends=later)

        # When
        revision = _judge(existing, response, _events(dividends=later))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("기존 끝날 2026-01-06" in line for line in revision.issues)

    def test_changed_dividend_amount_is_abnormal(self) -> None:
        """
        목적: 같은 날 배당의 금액이 바뀌면 계단이 기록 크기와 맞지 않아 비정상 — 정정인지 오류인지 사람이 본다

        Given: 기존 = 2026-01-12 배당 $0.30 반영, 응답 = 같은 날 $0.40 반영과 그 기록
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 응답 기록 금액 $0.400
        """
        # Given
        existing = _stored(_adjusted(dividends={DATES[5]: 0.3}))
        response = _adjusted(dividends={DATES[5]: 0.4})

        # When
        revision = _judge(existing, response, _events(dividends={DATES[5]: 0.4}))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("$0.400" in line for line in revision.issues)

    def test_drop_without_record_is_abnormal(self) -> None:
        """
        목적: 기록 없이 과거 가격이 내려가면 비정상

        Given: 기존 10행, 응답 = 앞 5행만 × 0.997 · 기록 없음
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「2026-01-12 이전 5행 -0.300%」 · 「기록 없음」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(np.array(RAW_CLOSE) * np.array([0.997] * 5 + [1.0] * 5))

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "2026-01-12 이전 5행 -0.300%" in revision.issues[0]
        assert "기록 없음" in revision.issues[0]

    def test_only_high_changed_is_abnormal(self) -> None:
        """
        목적: 한 행의 일부 열만 바뀌면(봉 정정 · 장 마감 직후의 확정 전 값) 조정이 아니라 비정상

        Given: 기존 10행, 응답 = 넷째 행의 고가만 +0.5%
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「1행에서」 · 「+0.500%」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(RAW_CLOSE)
        response[COL_HIGH] = response[COL_HIGH].to_numpy() * _row_scale(3, 1.005)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("1행에서" in line and "+0.500%" in line for line in revision.issues)

    def test_missing_date_is_abnormal(self) -> None:
        """
        목적: 기존에 있던 날짜가 응답에 없으면 비정상 — 덮어쓰면 그 날이 지워진다

        Given: 기존 10행, 응답 = 2026-01-08 이 빠진 9행
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「기존 날짜 1개가 응답에 없음 — 2026-01-08」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(RAW_CLOSE).drop(index=3).reset_index(drop=True)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "기존 날짜 1개가 응답에 없음 — 2026-01-08" in revision.issues

    def test_new_date_inside_existing_period_is_abnormal(self) -> None:
        """
        목적: 기존 기간 안에 없던 날짜가 생기면 비정상

        Given: 기존 = 2026-01-08 이 없는 9행, 응답 10행
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「기존 기간 안에 새 날짜 1개 — 2026-01-08」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE)).drop(index=3).reset_index(drop=True)
        response = _prices(RAW_CLOSE)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "기존 기간 안에 새 날짜 1개 — 2026-01-08" in revision.issues

    def test_new_date_before_existing_first_is_abnormal(self) -> None:
        """
        목적: 기존 첫날 앞에 날짜가 생겨도 비정상 — 흔들림으로 보면 그 행이 조용히 버려지고, 덮어쓰면 조용히 들어온다

        Given: 기존 10행(2026-01-05 ~), 응답 = 2026-01-02 한 행 + 같은 10행
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「기존 첫날(2026-01-05) 앞에 날짜 1개가 생김 — 2026-01-02」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        earlier = _prices([99.0], dates=[date(2026, 1, 2)])
        response = pd.concat([earlier, _prices(RAW_CLOSE)], ignore_index=True)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "기존 첫날(2026-01-05) 앞에 날짜 1개가 생김 — 2026-01-02" in revision.issues

    def test_rise_of_all_rows_without_record_is_abnormal(self) -> None:
        """
        목적: 기존 끝날까지 모든 행이 함께 오르면(기존 끝날 뒤 배당이 빠진 모양) 그 뒤 기록으로 설명되지 않아 비정상

        Given: 기존 10행, 응답 = 10행 모두 × 1.004 · 기록 없음
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「기존 끝날 2026-01-16 까지 10행 +0.400%」 · 「없음」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(np.array(RAW_CLOSE) * 1.004)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "기존 끝날 2026-01-16 까지 10행 +0.400%" in revision.issues[0]
        assert "없음" in revision.issues[0]

    def test_small_change_without_record_is_abnormal(self) -> None:
        """
        목적: 흔들림 상한은 넘었는데 어느 원인 검사에도 걸리지 않고 맞춘 기록도 없으면 비정상 — 설명된 것이 없는데
              응답으로 덮어쓰면 다른 행의 흔들림까지 들어온다

        Given: 기존 10행, 응답 = 다섯째 행만 시가 +3e-5 · 종가 +1.5e-5 (열 차 · 계단 · 끝 구간 · 누적 모두 상한 아래) · 기록 없음
        When: judge_revision
        Then: ABNORMAL, 원인 줄 「기록 없는 작은 변화 — 1행」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(RAW_CLOSE)
        response[COL_OPEN] = response[COL_OPEN].to_numpy() * _row_scale(4, 1 + 3e-5)
        response[COL_CLOSE] = response[COL_CLOSE].to_numpy() * _row_scale(4, 1 + 1.5e-5)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any(line.startswith("기록 없는 작은 변화 — 1행") for line in revision.issues)

    def test_small_steps_accumulating_is_abnormal(self) -> None:
        """
        목적: 하루하루는 상한 아래인 변화가 쌓여 상한을 넘으면 비정상 — 계단만 보면 통과한다

        Given: 기존 10행, 응답 = 첫 행 +9e-5 에서 끝 행 0 까지 하루 1e-5 씩 줄어드는 비율 · 기록 없음
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「쌓임」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        drift = 1 + 1e-5 * np.arange(9, -1, -1)
        response = _prices(np.array(RAW_CLOSE) * drift)

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("쌓임" in line for line in revision.issues)

    def test_issues_largest_first(self) -> None:
        """
        목적: 원인 줄은 크기가 큰 것부터 — 블록이 앞 몇 줄만 보여도 가장 큰 변화가 보인다

        Given: 기존 = 2026-01-12 배당 $0.312 반영, 응답 = 배당 없음 + 앞 8행 × 0.999 (01-15 에 기록 없는 −0.1%)
        When: judge_revision
        Then: 첫 줄 +0.301% (01-12), 둘째 줄 -0.100% (01-15)
        """
        # Given
        existing = _stored(_adjusted(dividends={DATES[5]: 0.312}))
        response = _prices(np.array(RAW_CLOSE) * np.array([0.999] * 8 + [1.0] * 2))

        # When
        revision = _judge(existing, response)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert "2026-01-12 이전 5행 +0.301%" in revision.issues[0]
        assert "2026-01-15 이전 8행 -0.100%" in revision.issues[1]


class TestRecordMatch:
    """계단 · 끝 구간을 기록과 맞추는 기준 — (1 + 계단) ÷ 기록 비율이 흔들림 상한 안"""

    @pytest.mark.parametrize(
        ("extra", "expected_kind"),
        [(1.9e-5, RevisionKind.EXPLAINED), (2.2e-5, RevisionKind.ABNORMAL)],
    )
    def test_record_match_boundary(self, extra: float, expected_kind: RevisionKind) -> None:
        """
        목적: 배당 기록에 더해 섞인 변화는 상한(상대 2e-5)까지만 받아들인다 — 기록 크기와 상관없이 같은 기준.
              기록 크기에 비례해 허용하면 두 경우 모두 설명됨이 된다 (분할은 맞아도 비정상이라 경계가 없다 — TestSplitIsAbnormal)

        Given: 기존 10행, 응답 = 2026-01-12 배당 $0.50 이 반영되고 그날 앞 5행에 extra 만큼 더 바뀐 시세와 그 기록
        When: judge_revision
        Then: 1.9e-5 → EXPLAINED, 2.2e-5 → ABNORMAL
        """
        # Given
        dividends = {DATES[5]: 0.5}
        existing = _stored(_prices(RAW_CLOSE))
        extra_scale = np.array([1 + extra] * 5 + [1.0] * 5)
        response = _prices(np.array(RAW_CLOSE) * _factors(dividends) * extra_scale)

        # When
        revision = _judge(existing, response, _events(dividends=dividends))

        # Then
        assert revision.kind is expected_kind

    @pytest.mark.parametrize(
        ("dividends", "splits"),
        [({DATES[5]: RAW_CLOSE[4]}, None), (None, {DATES[5]: float("inf")})],
    )
    def test_unusable_record_on_step_is_abnormal(
        self, dividends: dict[date, float] | None, splits: dict[date, float] | None
    ) -> None:
        """
        목적: 조정 비율을 셀 수 없는 기록(배당 = 전날 종가 → 비율 0, 분할 배수 무한 → 비율 0)이 계단에 걸려도 멈추지 않고 비정상

        Given: 기존 10행, 응답 = 앞 5행 × 0.5 와 2026-01-12 의 그 기록
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「셀 수 없는 기록」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE))
        response = _prices(np.array(RAW_CLOSE) * np.array([0.5] * 5 + [1.0] * 5))

        # When
        revision = _judge(existing, response, _events(dividends=dividends, splits=splits))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("셀 수 없는 기록" in line for line in revision.issues)

    def test_unusable_record_after_existing_end_is_abnormal(self) -> None:
        """
        목적: 기존 끝날 뒤의 셀 수 없는 기록도 0 으로 나누지 않고 맞지 않는 기록으로 본다

        Given: 기존 8행, 응답 = 10행 × 0.99 와 2026-01-16 배당 = 전날 종가(비율 0)의 기록
        When: judge_revision
        Then: ABNORMAL, 원인 줄에 「기존 끝날 2026-01-14」
        """
        # Given
        existing = _stored(_prices(RAW_CLOSE), rows=8)
        response = _prices(np.array(RAW_CLOSE) * 0.99)

        # When
        revision = _judge(existing, response, _events(dividends={DATES[9]: RAW_CLOSE[8]}))

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("기존 끝날 2026-01-14" in line for line in revision.issues)


class TestRecentDividends:
    """원인 블록에 붙일 응답의 최근 배당"""

    def test_last_three_dividends_by_date(self) -> None:
        """
        목적: 응답의 배당 기록 중 날짜가 늦은 3건을 날짜순으로 담는다 — 배당 일정에 빈 달이 있는지 AI 가 본다

        Given: 배당 기록 4건 (날짜순이 아니게 넣음)
        When: judge_revision
        Then: recent_dividends = 늦은 3건, 날짜 오름차순
        """
        # Given
        dividends = {DATES[8]: 0.4, DATES[2]: 0.1, DATES[6]: 0.3, DATES[4]: 0.2}

        # When
        revision = _judge(None, _prices(RAW_CLOSE), _events(dividends=dividends))

        # Then
        assert revision.recent_dividends == ((DATES[4], 0.2), (DATES[6], 0.3), (DATES[8], 0.4))


def _abnormal_revision(
    issues: tuple[str, ...],
    recent: tuple[tuple[date, float], ...],
    split_changes: tuple[tuple[date, float], ...] = (),
) -> PriceRevision:
    return PriceRevision(
        kind=RevisionKind.ABNORMAL,
        prices=pd.DataFrame(),
        issues=issues,
        applied=(),
        split_changes=split_changes,
        existing_end=date(2026, 10, 29),
        existing_rows=6103,
        response_end=date(2026, 11, 6),
        response_rows=6109,
        recent_dividends=recent,
    )


class TestFormatAbnormalBlock:
    """사용자가 그대로 AI 에 붙여 넣는 원인 블록"""

    def test_block_lines(self) -> None:
        """
        목적: 블록 머리 · 종목 머리줄 · 사건 5줄 · 「외 N건」 · 최근 배당 · --accept / --exclude 의 뜻을 이 순서로 낸다 —
              터미널 y / N 은 없다(결정 Q16). 둘 다 사람이 정한다

        Given: 사건 7건 · 최근 배당 3건인 TLT 판정, 실행 2026-11-07 21:10 KST, 기준일 2026-11-06, yfinance 0.2.66
        When: format_abnormal_block
        Then: 줄마다 정해진 문구
        """
        # Given
        revision = _abnormal_revision(
            issues=tuple(f"사건 {i}" for i in range(7)),
            recent=((date(2026, 7, 1), 0.318), (date(2026, 8, 3), 0.33), (date(2026, 9, 1), 0.315)),
        )
        run_at = datetime(2026, 11, 7, 21, 10, tzinfo=ZoneInfo("Asia/Seoul"))

        # When
        block = format_abnormal_block(
            [("TLT", Path("storage/prices/TLT_adjusted.csv"), revision)],
            run_at=run_at,
            cutoff_date=date(2026, 11, 6),
            yfinance_version="0.2.66",
        )

        # Then
        assert block.splitlines() == [
            "[갱신 비정상 판정 — 이 블록을 그대로 AI 에 붙여 판단을 받으세요]",
            "실행 2026-11-07 21:10 KST · 기준일 2026-11-06 · yfinance 0.2.66",
            "판단 요청: 아래 변화가 야후 쪽 오류인지 실제 정정인지, 이번 응답으로 덮어써도 되는지",
            "",
            "TLT — storage/prices/TLT_adjusted.csv (기존 ~ 2026-10-29 6,103행 · 응답 ~ 2026-11-06 6,109행)",
            "  - 사건 0",
            "  - 사건 1",
            "  - 사건 2",
            "  - 사건 3",
            "  - 사건 4",
            "  - 외 2건",
            "  - 응답의 최근 배당: 2026-07-01 $0.318 · 2026-08-03 $0.330 · 2026-09-01 $0.315",
            "  --accept TLT = 응답으로 덮어씀(위 변화가 저장됨) · --exclude TLT = 기존 파일 그대로(새 날짜도 붙지 않음)",
        ]

    def test_split_adds_exclude_warning(self) -> None:
        """
        목적: 분할로 보이는 변화가 있는 종목에는 「--exclude 해도 다음 갱신에서 다시 멈춘다」와 공시 대조를 안내한다 —
              분할은 되돌려지지 않아 제외만 하면 갱신 때마다 같은 자리에서 멈춘다 (결정 Q23)

        Given: 2026-01-12 2배 분할로 보이는 변화가 있는 TQQQ 판정
        When: format_abnormal_block
        Then: --accept / --exclude 줄 다음에 분할 안내 줄
        """
        # Given
        revision = _abnormal_revision(
            issues=("2026-01-12 이전 5행 -50.000% — 분할로 보이는 변화: 2026-01-12 · 2배 (야후 기록)",),
            recent=(),
            split_changes=((date(2026, 1, 12), 2.0),),
        )

        # When
        block = format_abnormal_block(
            [("TQQQ", Path("storage/prices/TQQQ_adjusted.csv"), revision)],
            run_at=datetime(2026, 11, 7, 21, 10, tzinfo=ZoneInfo("Asia/Seoul")),
            cutoff_date=date(2026, 11, 6),
            yfinance_version="0.2.66",
        )

        # Then
        lines = block.splitlines()
        accept_line = lines.index(
            "  --accept TQQQ = 응답으로 덮어씀(위 변화가 저장됨) · --exclude TQQQ = 기존 파일 그대로(새 날짜도 붙지 않음)"
        )
        assert lines[accept_line + 1] == (
            "  분할로 보이는 변화(2026-01-12 · 2배)는 운용사 공시와 날짜 · 비율을 맞춰 본 뒤 --accept 하세요"
            " — --exclude 하면 다음 갱신에서도 다시 멈춥니다"
        )

    def test_block_without_dividends(self) -> None:
        """
        목적: 응답에 배당 기록이 없으면 그렇다고 적는다 — 빈 줄로 두면 기록이 없는 것인지 빠뜨린 것인지 모른다

        Given: 사건 1건 · 배당 기록 없음
        When: format_abnormal_block
        Then: 「  - 응답에 배당 기록 없음」 줄이 있고 「외」 줄은 없다
        """
        # Given
        revision = _abnormal_revision(issues=("사건 0",), recent=())

        # When
        block = format_abnormal_block(
            [("GLD", Path("storage/prices/GLD_adjusted.csv"), revision)],
            run_at=datetime(2026, 11, 7, 21, 10, tzinfo=ZoneInfo("Asia/Seoul")),
            cutoff_date=date(2026, 11, 6),
            yfinance_version="0.2.66",
        )

        # Then
        lines = block.splitlines()
        assert "  - 응답에 배당 기록 없음" in lines
        assert not any(line.startswith("  - 외 ") for line in lines)
