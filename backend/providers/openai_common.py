"""What the OpenAI adapters (Luna and Sol) share: error mapping, token usage and reading the
structured output of a Responses API call. Checked against OpenAI's docs on 2026-10-04."""

import json
from typing import Any

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.responses import Response

from backend.providers.cost import Usage
from backend.providers.types import ProviderUnavailable, UnavailableReason


def unavailable(error: OpenAIError) -> ProviderUnavailable:
    retry_after_s = None
    if isinstance(error, RateLimitError):
        retry_after_s = _retry_after_s(error.response.headers)
    return ProviderUnavailable(_reason(error), retry_after_s=retry_after_s)


def _reason(error: OpenAIError) -> UnavailableReason:
    # Order matters: a timeout is also a connection error.
    match error:
        case APITimeoutError():
            return "timeout"
        case APIConnectionError():
            return "connection"
        case APIResponseValidationError():
            return "bad_response"
        case AuthenticationError() | PermissionDeniedError():
            return "auth"
        case RateLimitError():
            return "rate_limited"
        case APIStatusError() if error.status_code >= 500:
            return "server_error"
        case APIStatusError():
            return "invalid_request"
        case _:  # any other SDK failure happens before or without an HTTP response
            return "connection"


def _retry_after_s(headers: Any) -> float | None:
    for name, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            return float(value) / scale
        except ValueError:
            return None
    return None


def usage_of(response: Response) -> Usage:
    """Tokens of one call. `input_tokens` already includes the cached and cache-written ones."""
    usage = response.usage
    if usage is None:
        return Usage(tokens_in=0, tokens_out=0)
    details = usage.input_tokens_details
    return Usage(
        tokens_in=usage.input_tokens,
        tokens_out=usage.output_tokens,
        tokens_cached=details.cached_tokens or 0,
        tokens_cache_write=getattr(details, "cache_write_tokens", 0) or 0,
    )


def structured_output(response: Response) -> dict[str, Any]:
    """The JSON object a strict-schema call returned. A refusal, a cut-off answer or anything
    that isn't a JSON object is a bad response, which is not retried."""
    if response.status != "completed":
        raise ProviderUnavailable("bad_response")
    for item in response.output:
        if item.type != "message":
            continue
        if any(content.type == "refusal" for content in item.content):
            raise ProviderUnavailable("bad_response")
    try:
        parsed = json.loads(response.output_text)
    except ValueError:
        raise ProviderUnavailable("bad_response") from None
    if not isinstance(parsed, dict):
        raise ProviderUnavailable("bad_response")
    return parsed
