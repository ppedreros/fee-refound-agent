"""Sol, the drafter: OpenAI's Responses API with `gpt-6.1-sol` (SPEC-providers; D2).

Sol gets facts only (`DraftInput`), never the member's message. The static system prompt goes
first and unchanged on every call, so OpenAI's prefix caching applies once it passes 1,024 tokens;
cached and cache-written tokens are counted and priced. The output is a strict schema with a
single `reply` field. Failures raise `DrafterUnavailable`, and the node falls back to a template.
"""

import asyncio
import time
from typing import Any, Final

from openai import AsyncOpenAI, OpenAIError
from openai.types.responses import EasyInputMessageParam, Response, ResponseTextConfigParam
from openai.types.shared_params import Reasoning

from backend.providers.config import ProviderConfig
from backend.providers.cost import compute_cost
from backend.providers.openai_common import structured_output, unavailable, usage_of
from backend.providers.retry import Clock, Sleep, call_with_retries
from backend.providers.types import (
    CallMeta,
    Draft,
    DrafterUnavailable,
    DraftInput,
    ProviderUnavailable,
    UnavailableReason,
)

REASONING_EFFORT: Final = "low"  # gpt-6.1-sol's lowest; it doesn't support "none" or "minimal"
MAX_OUTPUT_TOKENS = 4000  # reasoning tokens count as output; the reply itself is ~150
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string", "description": "The reply to the member."}},
    "required": ["reply"],
    "additionalProperties": False,
}


class OpenAIDrafter:
    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        config: ProviderConfig,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._config = config
        self._clock = clock
        self._sleep = sleep

    async def draft(
        self,
        payload: DraftInput,
        *,
        instructions: str,
        prompt_version: str | None = None,
        deadline: float | None = None,
    ) -> Draft:
        message: EasyInputMessageParam = {
            "role": "user",
            "content": payload.model_dump_json(indent=2),
        }
        reasoning: Reasoning = {"effort": REASONING_EFFORT}
        text: ResponseTextConfigParam = {
            "format": {"type": "json_schema", "name": "reply", "schema": SCHEMA, "strict": True}
        }

        async def attempt(timeout_s: float) -> Response:
            try:
                return await self._client.responses.create(
                    model=self._config.model,
                    instructions=instructions,
                    input=[message],
                    reasoning=reasoning,
                    text=text,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    store=False,
                    timeout=timeout_s,
                )
            except OpenAIError as error:
                raise unavailable(error) from None

        started = self._clock()
        try:
            result = await call_with_retries(
                attempt,
                self._config.policy,
                deadline=deadline,
                clock=self._clock,
                sleep=self._sleep,
            )
        except ProviderUnavailable as error:
            raise _drafter_unavailable(error.reason, error.attempts) from None
        try:
            reply = structured_output(result.value).get("reply")
        except ProviderUnavailable as error:
            raise _drafter_unavailable(error.reason, result.attempts) from None
        if not isinstance(reply, str) or not reply.strip():
            raise _drafter_unavailable("bad_response", result.attempts)

        usage = usage_of(result.value)
        return Draft(
            reply=reply.strip(),
            meta=CallMeta(
                provider="openai",
                model=self._config.model,
                mode="live",
                latency_ms=round((self._clock() - started) * 1000),
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                tokens_cached=usage.tokens_cached,
                tokens_cache_write=usage.tokens_cache_write,
                cost_usd=compute_cost(self._config.model, usage),
                attempts=result.attempts,
            ),
        )


def _drafter_unavailable(reason: UnavailableReason, attempts: int) -> DrafterUnavailable:
    error = DrafterUnavailable(reason)
    error.attempts = attempts
    return error
