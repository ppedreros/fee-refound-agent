"""Jev first, Luna when Jev is unavailable (SPEC-providers; D-agent-7: this is normal operation).

`ClassifierUnavailable` is raised only after both have failed. The answer's `meta` is the one
that answered, with every attempt of the chain counted and the time of the whole chain, and
`fallback_reason` says why Jev didn't answer.
"""

import time
from collections.abc import Mapping, Sequence

import structlog

from backend.providers.retry import Clock
from backend.providers.types import (
    Classification,
    Classifier,
    ProviderUnavailable,
    Question,
    UnavailableReason,
)

log = structlog.get_logger()


class ClassifierUnavailable(ProviderUnavailable):
    """Both classifiers failed. `reason` is the backup's, `primary_reason` the primary's."""

    def __init__(self, reason: UnavailableReason, *, primary_reason: UnavailableReason) -> None:
        super().__init__(reason)
        self.primary_reason: UnavailableReason = primary_reason


class ClassifierChain:
    def __init__(
        self, primary: Classifier, backup: Classifier, *, clock: Clock = time.monotonic
    ) -> None:
        self._primary = primary
        self._backup = backup
        self._clock = clock

    @property
    def primary(self) -> Classifier:
        return self._primary

    @property
    def backup(self) -> Classifier:
        return self._backup

    async def classify(
        self,
        state: Mapping[str, str],
        questions: Sequence[Question],
        *,
        deadline: float | None = None,
    ) -> Classification:
        started = self._clock()
        try:
            return await self._primary.classify(state, questions, deadline=deadline)
        except ProviderUnavailable as primary:
            log.info("classifier_fallback", reason=primary.reason, attempts=primary.attempts)
            try:
                answer = await self._backup.classify(state, questions, deadline=deadline)
            except ProviderUnavailable as backup:
                error = ClassifierUnavailable(backup.reason, primary_reason=primary.reason)
                error.attempts = primary.attempts + backup.attempts
                raise error from None
            meta = answer.meta.model_copy(
                update={
                    "attempts": primary.attempts + answer.meta.attempts,
                    "latency_ms": round((self._clock() - started) * 1000),
                }
            )
            return answer.model_copy(update={"meta": meta, "fallback_reason": primary.reason})
