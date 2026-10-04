"""Jev (TypeSafe System One) classifier, through `typesafe-sdk` (request shape: docs/notes/jev.md).

All questions go in one request. The SDK's own retries are switched off on every call: retries,
backoff and the run deadline belong to our policy (T15), so every attempt is counted.
"""

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
    def __init__(self, client: AsyncTypeSafeClient, *, model: str, timeout_s: float) -> None:
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    async def classify(
        self, state: Mapping[str, str], questions: Sequence[Question]
    ) -> Classification:
        started = time.perf_counter()
        try:
            response = await self._client.system_one(
                state=dict(state),
                questions={question.key: _to_jev(question) for question in questions},
                model=self._model,
                retry=NO_SDK_RETRIES,
                timeout=self._timeout_s,
            )
        except TypeSafeError as error:
            # `from None`: the SDK error can carry the request body, and with it the message.
            raise ProviderUnavailable(_reason(error)) from None
        latency_ms = round((time.perf_counter() - started) * 1000)

        return Classification(
            answers={question.key: _answer(question, response) for question in questions},
            meta=CallMeta(
                provider="jev",
                model=response.model,
                mode="live",
                latency_ms=latency_ms,
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
                attempts=1,
            ),
        )


def _to_jev(question: Question) -> Choice | Noul:
    if isinstance(question, ChoiceQuestion):
        return Choice(
            instructions=question.prompt,
            criteria={option.key: option.description for option in question.options},
        )
    return Noul(instructions=question.statement)


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
