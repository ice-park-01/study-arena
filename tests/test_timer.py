from datetime import date, datetime, timedelta, timezone

from app.timer import (
    IDLE_LIMIT,
    MAX_CREDIT,
    credit_seconds,
    format_duration,
    is_studying,
    kst_date,
    week_start,
)

T0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)


def after(seconds):
    return T0 + timedelta(seconds=seconds)


def test_limits_match_the_spec():
    assert MAX_CREDIT == 30
    assert IDLE_LIMIT == 90


def test_first_tick_earns_nothing():
    assert credit_seconds(None, T0) == 0


def test_regular_tick_earns_the_gap():
    assert credit_seconds(T0, after(30)) == 30
    assert credit_seconds(T0, after(12)) == 12


def test_one_tick_never_earns_more_than_30_seconds():
    assert credit_seconds(T0, after(45)) == 30
    assert credit_seconds(T0, after(90)) == 30


def test_gap_over_90_seconds_starts_a_new_session():
    assert credit_seconds(T0, after(91)) == 0
    assert credit_seconds(T0, after(3600)) == 0


def test_clock_going_backwards_earns_nothing():
    assert credit_seconds(T0, after(-5)) == 0


def test_two_tabs_do_not_double_the_time():
    # 탭 A는 0, 30, 60... 초에, 탭 B는 15, 45, 75... 초에 신호를 보낸다.
    ticks = sorted([after(s) for s in range(0, 121, 30)] + [after(s) for s in range(15, 121, 30)])
    total, prev = 0, None
    for now in ticks:
        total += credit_seconds(prev, now)
        prev = now
    assert total <= 120


def test_is_studying_within_90_seconds():
    assert is_studying(T0, after(90)) is True
    assert is_studying(T0, after(91)) is False
    assert is_studying(None, T0) is False


def test_kst_date_rolls_over_at_15_utc():
    assert kst_date(datetime(2026, 11, 24, 14, 59, tzinfo=timezone.utc)) == date(2026, 11, 24)
    assert kst_date(datetime(2026, 11, 24, 15, 30, tzinfo=timezone.utc)) == date(2026, 11, 25)


def test_week_starts_on_monday():
    assert week_start(date(2026, 11, 29)) == date(2026, 11, 23)  # 일요일
    assert week_start(date(2026, 11, 23)) == date(2026, 11, 23)  # 월요일


def test_format_duration():
    assert format_duration(0) == "0분"
    assert format_duration(59) == "0분"
    assert format_duration(65 * 60) == "1시간 05분"
    assert format_duration(25 * 60 + 10) == "25분"


def test_credit_crossing_midnight_is_split_by_korean_date():
    from app.timer import split_by_day

    midnight = datetime(2026, 11, 24, 15, 0, 0, tzinfo=timezone.utc)  # 한국 시간 25일 0시
    assert split_by_day(midnight, 30) == [(date(2026, 11, 24), 30)]
    assert split_by_day(midnight + timedelta(seconds=10), 30) == [(date(2026, 11, 24), 20), (date(2026, 11, 25), 10)]
    assert split_by_day(midnight + timedelta(seconds=30), 30) == [(date(2026, 11, 25), 30)]
    assert split_by_day(midnight, 0) == []
