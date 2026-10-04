"""Jev (TypeSafe System One) classifier, through `typesafe-sdk` (request shape: docs/notes/jev.md).

All questions go in one request. The SDK's own retries are switched off: our call policy owns the
timeout, the retries, Retry-After and the run deadline, so every attempt is counted.
"""

import asyncio
import time
from collections.abc import Mapping, Sequence

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeError,
    TypeSafeInternalServerError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
)

from backend.providers.config import ProviderConfig
from backend.providers.cost import Usage, compute_cost
from backend.providers.retry import Clock, Sleep, call_with_retries
from backend.providers.types import (
    CallMeta,
    ChoiceAnswer,
    ChoiceQuestion,
    Classification,
    NoulAnswer,
    NoulQuestion,
    ProviderUnavailable,
    Question,
    UnavailableReason,
)

NO_SDK_RETRIES = RetryPolicy(max_retries=0)


class JevClassifier:
    def __init__(
        self,
        client: AsyncTypeSafeClient,
        *,
        config: ProviderConfig,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._config = config
        self._clock = clock
        self._sleep = sleep

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        deadline: float | None = None,
    ) -> Classification:
        jev_questions = {question.key: _to_jev(question) for question in questions}

        async def attempt(timeout_s: float) -> SystemOneResponse:
            try:
                return await self._client.system_one(
                    state=dict(state),
                    questions=jev_questions,
                    model=self._config.model,
                    retry=NO_SDK_RETRIES,
                    timeout=timeout_s,
                )
            except TypeSafeError as error:
                # `from None`: the SDK error can carry the request body, and with it the message.
                raise _unavailable(error) from None

        started = self._clock()
        result = await call_with_retries(
            attempt, self._config.policy, deadline=deadline, clock=self._clock, sleep=self._sleep
        )
        response = result.value
        latency_ms = round((self._clock() - started) * 1000)

        tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
        usage = Usage(tokens_in=tokens_in or 0, tokens_out=tokens_out or 0)
        # Without the token counts the cost is unknown, not zero.
        cost = compute_cost(response.model, usage) if None not in (tokens_in, tokens_out) else None
        return Classification(
            answers={question.key: _answer(question, response) for question in questions},
            meta=CallMeta(
                provider="jev",
                model=response.model,
                mode="live",
                latency_ms=latency_ms,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=cost,
                attempts=result.attempts,
            ),
        )


def _to_jev(question: Question) -> Choice | Noul:
    if isinstance(question, ChoiceQuestion):
        return Choice(
            instructions=question.prompt,
            criteria={option.key: option.description for option in question.options},
        )
    if question.criteria is None:
        return Noul(instructions=question.statement)
    return Noul(
        instructions=question.statement,
        criteria={"true": question.criteria.yes, "false": question.criteria.no},
    )


def _answer(question: Question, response: SystemOneResponse) -> ChoiceAnswer | NoulAnswer:
    """Map one answer exactly. Anything missing or unexpected is an error, never a default."""
    if isinstance(question, NoulQuestion):
        noul = response.nouls.get(question.key)
        if noul is None:
            raise ProviderUnavailable("bad_response")
        return NoulAnswer(p_yes=noul.noul, label=noul.noul >= 0.5)

    choice = response.choices.get(question.key)
    if choice is None or choice.choice not in {option.key for option in question.options}:
        raise ProviderUnavailable("bad_response")
    return ChoiceAnswer(
        choice=choice.choice,
        probabilities=dict(choice.probabilities),
        confidence=choice.confidence,
    )


def _unavailable(error: TypeSafeError) -> ProviderUnavailable:
    retry_after_s = None
    if isinstance(error, TypeSafeRateLimitError) and error.retry_after_ms is not None:
        retry_after_s = error.retry_after_ms / 1000
    return ProviderUnavailable(_reason(error), retry_after_s=retry_after_s)


def _reason(error: TypeSafeError) -> UnavailableReason:
    # Order matters: a timeout is also a connection error, and validation is also an API error.
    match error:
        case TypeSafeAPITimeoutError():
            return "timeout"
        case TypeSafeAPIConnectionError():
            return "connection"
        case TypeSafeAPIResponseValidationError():
            return "bad_response"
        case TypeSafeAuthenticationError() | TypeSafePermissionDeniedError():
            return "auth"
        case TypeSafeRateLimitError():
            return "rate_limited"
        case TypeSafeInternalServerError():
            return "server_error"
        case TypeSafeAPIError():
            return "invalid_request"
        case _:  # any other SDK failure happens before or without an HTTP response
            return "connection"
