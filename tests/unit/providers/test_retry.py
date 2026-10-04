"""The call policy: timeouts, retries with backoff, Retry-After and the run deadline
(SPEC-providers, "Timeouts and retries"). A fake clock and sleep keep the tests instant."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from backend.providers.config import CallPolicy
from backend.providers.retry import backoff_s, call_with_retries
from backend.providers.types import ProviderUnavailable, UnavailableReason

POLICY = CallPolicy(timeout_s=2.0, retries=2, backoff_base_s=0.5, backoff_cap_s=4.0)


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


type Operation = Callable[[float], Awaitable[str]]


def failing(
    *reasons: UnavailableReason, retry_after_s: float | None = None
) -> tuple[Operation, list[float]]:
    """An operation that fails with these reasons, in order, then answers "ok"."""
    queue = list(reasons)
    calls: list[float] = []

    async def operation(timeout_s: float) -> str:
        calls.append(timeout_s)
        if queue:
            raise ProviderUnavailable(queue.pop(0), retry_after_s=retry_after_s)
        return "ok"

    return operation, calls


async def test_a_first_try_success_counts_one_attempt() -> None:
    time = FakeTime()
    operation, _ = failing()

    result = await call_with_retries(operation, POLICY, clock=time.clock, sleep=time.sleep)

    assert (result.value, result.attempts) == ("ok", 1)
    assert time.slept == []


async def test_a_timeout_is_retried_twice_then_gives_up() -> None:
    time = FakeTime()
    operation, calls = failing("timeout", "timeout", "timeout")

    with pytest.raises(ProviderUnavailable) as error:
        await call_with_retries(operation, POLICY, clock=time.clock, sleep=time.sleep)

    assert error.value.reason == "timeout"
    assert error.value.attempts == 3
    assert len(calls) == 3


async def test_a_retry_that_succeeds_reports_every_attempt() -> None:
    time = FakeTime()
    operation, _ = failing("server_error", "connection")

    result = await call_with_retries(operation, POLICY, clock=time.clock, sleep=time.sleep)

    assert (result.value, result.attempts) == ("ok", 3)


@pytest.mark.parametrize("reason", ["invalid_request", "auth", "bad_response", "replay_miss"])
async def test_client_errors_are_not_retried(reason: UnavailableReason) -> None:
    time = FakeTime()
    operation, calls = failing(reason)

    with pytest.raises(ProviderUnavailable) as error:
        await call_with_retries(operation, POLICY, clock=time.clock, sleep=time.sleep)

    assert len(calls) == 1
    assert error.value.attempts == 1


@pytest.mark.parametrize(("retry_after_s", "waited"), [(1.0, 1.0), (10.0, 4.0)])
async def test_retry_after_is_honoured_up_to_the_cap(retry_after_s: float, waited: float) -> None:
    time = FakeTime()
    operation, _ = failing("rate_limited", retry_after_s=retry_after_s)

    await call_with_retries(operation, POLICY, clock=time.clock, sleep=time.sleep)

    assert time.slept == [waited]


@pytest.mark.parametrize(
    ("attempt", "draw", "expected"),
    [(1, 1.0, 0.5), (2, 1.0, 1.0), (3, 1.0, 2.0), (5, 1.0, 4.0), (2, 0.0, 0.0), (2, 0.5, 0.5)],
)
def test_backoff_is_exponential_with_full_jitter_and_a_cap(
    attempt: int, draw: float, expected: float
) -> None:
    assert backoff_s(attempt, POLICY, None, rng=lambda: draw) == expected


async def test_no_attempt_starts_after_the_deadline() -> None:
    time = FakeTime()
    starts: list[float] = []

    async def slow(timeout_s: float) -> str:
        starts.append(time.now)
        time.now += timeout_s  # it hangs for its whole budget
        raise ProviderUnavailable("timeout")

    deadline = time.now + 3.0
    with pytest.raises(ProviderUnavailable):
        await call_with_retries(
            slow, POLICY, deadline=deadline, clock=time.clock, sleep=time.sleep, rng=lambda: 1.0
        )

    assert starts and all(start < deadline for start in starts)
    assert time.now <= deadline + POLICY.timeout_s


async def test_an_attempt_gets_only_the_time_left_before_the_deadline() -> None:
    time = FakeTime()
    operation, calls = failing()

    await call_with_retries(
        operation, POLICY, deadline=time.now + 0.75, clock=time.clock, sleep=time.sleep
    )

    assert calls == [0.75]


async def test_a_passed_deadline_means_no_attempt_at_all() -> None:
    time = FakeTime()
    operation, calls = failing()

    with pytest.raises(ProviderUnavailable) as error:
        await call_with_retries(
            operation, POLICY, deadline=time.now - 1, clock=time.clock, sleep=time.sleep
        )

    assert calls == []
    assert (error.value.reason, error.value.attempts) == ("timeout", 0)


async def test_an_operation_that_hangs_is_cut_off_by_the_timeout() -> None:
    async def hangs(timeout_s: float) -> str:
        await asyncio.sleep(10)
        return "never"

    quick = CallPolicy(timeout_s=0.05, retries=0, backoff_base_s=0.5, backoff_cap_s=4.0)

    with pytest.raises(ProviderUnavailable) as error:
        await call_with_retries(hangs, quick)

    assert error.value.reason == "timeout"
