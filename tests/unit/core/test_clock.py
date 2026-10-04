from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.core.clock import Clock, FixedClock, SystemClock


def test_system_clock_gives_the_current_time_in_utc() -> None:
    clock: Clock = SystemClock()

    now = clock.now()

    assert now.tzinfo is UTC
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_fixed_clock_always_gives_the_same_time() -> None:
    at = datetime(2026, 9, 15, 8, 12, 44, tzinfo=UTC)
    clock: Clock = FixedClock(at)

    assert clock.now() == at
    assert clock.now() == at


def test_fixed_clock_converts_other_timezones_to_utc() -> None:
    bogota = timezone(timedelta(hours=-5))

    now = FixedClock(datetime(2026, 9, 15, 3, 12, 44, tzinfo=bogota)).now()

    assert now == datetime(2026, 9, 15, 8, 12, 44, tzinfo=UTC)
    assert now.tzinfo is UTC


def test_fixed_clock_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone"):
        FixedClock(datetime(2026, 9, 15, 8, 12, 44))
