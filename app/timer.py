"""공부 시간 규칙. 시간은 서버 시계로만 계산한다."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

MAX_CREDIT = 30  # 신호 하나가 인정받는 최대 초
IDLE_LIMIT = 90  # 이보다 오래 신호가 없으면 세션이 끝난 것으로 본다
KST = timezone(timedelta(hours=9))


def credit_seconds(prev: datetime | None, now: datetime) -> int:
    """직전 신호 이후 이번 신호로 인정할 공부 시간(초)."""
    if prev is None:
        return 0
    gap = (now - prev).total_seconds()
    if gap <= 0 or gap > IDLE_LIMIT:
        return 0
    return int(min(gap, MAX_CREDIT))


def is_studying(last: datetime | None, now: datetime) -> bool:
    if last is None:
        return False
    return 0 <= (now - last).total_seconds() <= IDLE_LIMIT


def kst_date(dt: datetime) -> date:
    return dt.astimezone(KST).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def format_duration(seconds: int) -> str:
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}시간 {minutes:02d}분"
    return f"{minutes}분"
