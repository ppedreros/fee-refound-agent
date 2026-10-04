"""The clock. Code that decides takes a `Clock` instead of reading the wall clock."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware, in UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock stopped at one moment. For tests."""

    def __init__(self, at: datetime) -> None:
        if at.utcoffset() is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at
