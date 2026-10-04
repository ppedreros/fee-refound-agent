"""One call policy for every model call (SPEC-providers, "Timeouts and retries").

Each attempt gets the smaller of its timeout and the time left before the run's deadline.
Timeouts, connection errors, 429 and 5xx are retried with exponential backoff and full jitter
(a Retry-After is honoured up to the cap); other errors fail at once. No attempt, and no wait,
goes past the deadline. Written as a small loop rather than tenacity hooks, because the deadline
has to bound the wait as well as the attempts.
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.providers.config import CallPolicy
from backend.providers.types import ProviderUnavailable, UnavailableReason

RETRYABLE: frozenset[UnavailableReason] = frozenset(
    {"timeout", "connection", "rate_limited", "server_error"}
)

type Clock = Callable[[], float]  # monotonic seconds
type Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class Attempted[T]:
    value: T
    attempts: int


def backoff_s(
    attempt: int,
    policy: CallPolicy,
    retry_after_s: float | None,
    rng: Callable[[], float] = random.random,
) -> float:
    """How long to wait after failed attempt number `attempt` (1-based)."""
    if retry_after_s is not None:
        return min(retry_after_s, policy.backoff_cap_s)
    ceiling = min(policy.backoff_cap_s, policy.backoff_base_s * 2.0 ** (attempt - 1))
    return rng() * ceiling


async def call_with_retries[T](
    operation: Callable[[float], Awaitable[T]],
    policy: CallPolicy,
    *,
    deadline: float | None = None,
    clock: Clock = time.monotonic,
    sleep: Sleep = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> Attempted[T]:
    """Run `operation(timeout_s)` under the policy. Raises ProviderUnavailable, with `attempts`
    set, when every allowed attempt failed or the deadline left no room for another."""
    attempt = 0
    while True:
        left = None if deadline is None else deadline - clock()
        if left is not None and left <= 0:
            raise _with_attempts(ProviderUnavailable("timeout"), attempt)
        timeout = policy.timeout_s if left is None else min(policy.timeout_s, left)
        attempt += 1
        try:
            async with asyncio.timeout(timeout):
                return Attempted(value=await operation(timeout), attempts=attempt)
        except TimeoutError:
            error = ProviderUnavailable("timeout")
        except ProviderUnavailable as failure:
            error = failure

        if error.reason not in RETRYABLE or attempt > policy.retries:
            raise _with_attempts(error, attempt) from None
        wait = backoff_s(attempt, policy, error.retry_after_s, rng)
        if deadline is not None and clock() + wait >= deadline:
            raise _with_attempts(error, attempt) from None
        await sleep(wait)


def _with_attempts(error: ProviderUnavailable, attempts: int) -> ProviderUnavailable:
    error.attempts = attempts
    return error
