"""
series 모듈 테스트 — 하루 한 값인 계열(국내 지수 종가 · NAV · Coin Metrics · 국내 ETF 의 야후 분배 기록)

이 파일은 무엇을 검증하나요?
1. 저장 → 읽기가 날짜 · 값을 그대로 되돌리고, 저장 자릿수로 반올림하는가?
2. 중복 날짜 · 결측 값은 지우거나 메우지 않고 멈추는가? 행이 없는 계열(분배 기록이 0건인 ETF)은 받는가?
3. 덧붙이기 판정: 지난 날 값이 흔들림 안이면 기존 행 그대로에 새 날만 붙이고, 값이 바뀌거나 지난 날이 사라지거나
   기존 끝날 앞에 새 날이 생기면 비정상인가? (판정 원칙)

왜 중요한가요?
「정상이면 최신 데이터만 추가된다」 — 계열의 과거 값이 조용히 바뀌어도 시세처럼 멈춰야 한다.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quant_data.constants import COL_DATE, COL_VALUE
from quant_data.revision import RevisionKind
from quant_data.series import judge_series_append, load_series, save_series, validate_series

DAYS = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)]


def _series(values: list[float], days: list[date] | None = None) -> pd.DataFrame:
    return pd.DataFrame({COL_DATE: days if days is not None else DAYS[: len(values)], COL_VALUE: values})


class TestSaveAndLoad:
    """저장 · 읽기"""

    def test_round_trip_with_decimals(self, tmp_path: Path) -> None:
        """
        목적: 저장은 계열의 자릿수로 반올림하고, 읽기는 날짜를 date 로 되돌린다

        Given: 값 1.23456789 · 2.0, 자릿수 4
        When: save_series → load_series
        Then: 날짜 그대로, 값 1.2346 · 2.0
        """
        # Given
        path = tmp_path / "series" / "X_index.csv"

        # When
        save_series(_series([1.23456789, 2.0]), path, decimals=4)
        loaded = load_series(path)

        # Then
        assert list(loaded.columns) == [COL_DATE, COL_VALUE]
        assert loaded[COL_DATE].tolist() == DAYS[:2]
        assert loaded[COL_VALUE].tolist() == pytest.approx([1.2346, 2.0], abs=1e-12)

    def test_empty_series_round_trip(self, tmp_path: Path) -> None:
        """
        목적: 행이 없는 계열도 저장 · 읽기가 된다 (경계) — 분배를 한 번도 안 한 ETF 의 분배 기록이 그렇다(114800 등)

        Given: 머리만 있는 표
        When: save_series → load_series
        Then: 0행, 열 Date · Value
        """
        # Given
        path = tmp_path / "X_yahoo_dividends.csv"

        # When
        save_series(_series([], days=[]), path, decimals=6)
        loaded = load_series(path)

        # Then
        assert len(loaded) == 0
        assert list(loaded.columns) == [COL_DATE, COL_VALUE]

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """
        목적: 파일이 없으면 FileNotFoundError — 빈 계열로 넘기면 지워진 파일을 알아채지 못한다

        Given: 없는 경로
        When: load_series
        Then: FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            load_series(tmp_path / "none.csv")


class TestValidate:
    """검사 — 지우거나 메우지 않는다"""

    @pytest.mark.parametrize(
        ("frame", "pattern"),
        [
            (_series([1.0, 2.0], days=[DAYS[0], DAYS[0]]), "중복"),
            (_series([1.0, float("nan")]), "결측"),
        ],
        ids=["duplicate", "nan"],
    )
    def test_bad_series_raises(self, frame: pd.DataFrame, pattern: str) -> None:
        """
        목적: 중복 날짜 · 결측 값이면 멈춘다 — 메우면 「원래 없던 값」과 「메운 값」을 가를 수 없다

        Given: 같은 날 두 행 / 결측 값
        When: validate_series
        Then: ValueError (중복 / 결측)
        """
        with pytest.raises(ValueError, match=pattern):
            validate_series(frame)


class TestJudgeSeriesAppend:
    """덧붙이기 판정 — 지난 날 그대로면 새 날만 붙인다"""

    def test_no_existing_is_new(self) -> None:
        """
        목적: 기존 파일이 없으면 응답 그대로(새 파일)

        Given: 기존 없음, 응답 2일
        When: judge_series_append
        Then: NEW, 응답 그대로
        """
        # When
        revision = judge_series_append(None, _series([1.0, 2.0]), decimals=4)

        # Then
        assert revision.kind is RevisionKind.NEW
        pd.testing.assert_frame_equal(revision.values, _series([1.0, 2.0]))

    def test_unchanged_past_appends_new_days(self) -> None:
        """
        목적: 지난 날 값이 흔들림 안이면 기존 행은 글자 그대로 두고 기존 끝날 뒤의 새 날만 붙인다

        Given: 기존 2일 (1.0 · 2.0), 응답 4일 (1.00004 · 2.0 · 3.0 · 4.0) — 첫 값은 자릿수 4 의 반 단위 안
        When: judge_series_append
        Then: NOISE, 값 1.0 · 2.0 · 3.0 · 4.0 (첫 값은 기존 값)
        """
        # When
        revision = judge_series_append(_series([1.0, 2.0]), _series([1.00004, 2.0, 3.0, 4.0]), decimals=4)

        # Then
        assert revision.kind is RevisionKind.NOISE
        assert revision.values[COL_VALUE].tolist() == [1.0, 2.0, 3.0, 4.0]

    @pytest.mark.parametrize(
        ("response", "pattern"),
        [
            (_series([1.0, 2.5, 3.0]), "바뀜"),
            (_series([2.0, 3.0], days=DAYS[1:3]), "응답에 없음"),
            (_series([1.0, 1.5, 2.0], days=[DAYS[0], date(2026, 11, 2), DAYS[1]]), "중복"),
        ],
        ids=["changed", "missing_past_day", "duplicate"],
    )
    def test_abnormal(self, response: pd.DataFrame, pattern: str) -> None:
        """
        목적: 지난 날 값이 바뀌거나, 지난 날이 응답에서 사라지면 비정상이다 — 판정 원칙 「데이터가 바뀌면 오류」.
              응답 자체가 깨졌으면(중복 날짜) 판정 전에 멈춘다

        Given: 기존 2일 (1.0 · 2.0) 과 바뀐 응답
        When: judge_series_append
        Then: 바뀜 · 사라짐은 ABNORMAL 과 원인 줄, 중복은 ValueError
        """
        # Given
        existing = _series([1.0, 2.0])

        # When & Then
        if pattern == "중복":
            with pytest.raises(ValueError, match=pattern):
                judge_series_append(existing, response, decimals=4)
            return
        revision = judge_series_append(existing, response, decimals=4)
        assert revision.kind is RevisionKind.ABNORMAL
        assert any(pattern in issue for issue in revision.issues)

    def test_new_day_before_existing_end_is_abnormal(self) -> None:
        """
        목적: 기존 끝날 앞에 새 날이 생기면 비정상이다 — 과거가 바뀐 것이다

        Given: 기존 11-02 · 11-04, 응답 11-02 · 11-03 · 11-04
        When: judge_series_append
        Then: ABNORMAL, 원인에 「앞에 새 날」
        """
        # Given
        existing = _series([1.0, 3.0], days=[DAYS[0], DAYS[2]])
        response = _series([1.0, 2.0, 3.0], days=DAYS[:3])

        # When
        revision = judge_series_append(existing, response, decimals=4)

        # Then
        assert revision.kind is RevisionKind.ABNORMAL
        assert any("앞에 새 날" in issue for issue in revision.issues)
