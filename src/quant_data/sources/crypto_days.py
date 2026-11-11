"""비트코인 두 받기(Bitstamp · Coin Metrics)가 공유하는 UTC 하루 판정 — verify-lab `crypto_common` 에서 옮김

두 출처의 날짜는 모두 UTC 00:00 ~ 24:00 하루를 가리킨다(한국 시각 09:00 에 바뀐다). 「끝나지 않은 날」과 「받은 이력의
양 끝 · 사이가 제자리인가」를 한 곳에서만 판정한다 — 따로 두면 한쪽만 하루 밀려도 예외 없이 대조가 어긋난다.
「지금」은 받기 전에 잰 시각을 인자로 받는다 — 받은 뒤에 재면 09:00 을 걸쳐 돈 실행에서 진행 중이던 날이 끝난 날로 남는다.
"""

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from quant_data.constants import COL_DATE


def unfinished_utc_day(now: datetime) -> date:
    """
    아직 끝나지 않은 UTC 날짜 — 그날과 그 뒤의 값은 확정이 아니다.

    Raises:
        ValueError: now 에 시간대가 없을 때 — PC 의 시간대로 읽히면 PC 마다 경계가 하루 갈린다
    """
    if now.tzinfo is None:
        raise ValueError(f"시간대가 없는 시각입니다 (UTC · KST 처럼 시간대를 붙여 넘기세요): {now}")
    return now.astimezone(UTC).date()


def exclude_unfinished_days(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """UTC 로 끝나지 않은 날의 행을 뺀 복사본."""
    return df.loc[df[COL_DATE] < unfinished_utc_day(now)].reset_index(drop=True)


def require_complete_range(dates: pd.Series, *, first_day: date, now: datetime, publication_lag_days: int) -> None:
    """
    받은 이력의 첫 날이 소스의 첫 날이고, 끝이 끝난 마지막 날에서 공개 지연 안이며, 사이에 빠진 날이 없는지 본다 —
    서버가 덜 주거나 페이지를 건너뛰면 에러 없이 잘린 이력이 온다. 비트코인은 휴장이 없어 빠진 날은 소스의 결함이다.

    Raises:
        ValueError: 날짜가 없음 · 첫 날이 다름 · 끝이 허용 지연보다 이름 · 사이에 빠진 날 · now 에 시간대가 없음
    """
    if dates.empty:
        raise ValueError("받은 이력이 비어 있어 범위를 확인할 수 없습니다")
    days = pd.to_datetime(dates)
    first, last = days.min().date(), days.max().date()
    if first != first_day:
        raise ValueError(f"받은 이력의 시작이 {first} 로 소스의 첫 날 {first_day} 와 다릅니다 — 앞이 잘렸거나 소스가 바뀌었습니다")
    latest_finished = unfinished_utc_day(now) - timedelta(days=1)
    if last < latest_finished - timedelta(days=publication_lag_days):
        raise ValueError(
            f"받은 이력의 끝이 {last} 로, 끝난 마지막 날 {latest_finished} 에서 허용 지연 {publication_lag_days}일보다 멉니다 " "— 뒤가 잘렸습니다"
        )
    missing = pd.date_range(days.min(), days.max(), freq="D").difference(pd.DatetimeIndex(days))
    if len(missing) > 0:
        raise ValueError(f"받은 이력 사이에 빠진 날이 {len(missing)}일 있습니다 — 메우지 않습니다 (예시: {[d.date() for d in missing[:5]]})")
