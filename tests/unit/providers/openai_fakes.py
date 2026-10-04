"""A mocked OpenAI Responses API (httpx2.MockTransport) for the adapter tests. Never calls the
network. Responses follow the documented Responses API shape."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
from openai import AsyncOpenAI

type Handler = Callable[[httpx2.Request], httpx2.Response]


def response_body(
    output: dict[str, Any] | str,
    *,
    model: str,
    tokens_in: int = 320,
    tokens_out: int = 40,
    cached: int = 0,
    cache_write: int = 0,
    refusal: str | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    text = output if isinstance(output, str) else json.dumps(output)
    content = (
        {"type": "refusal", "refusal": refusal}
        if refusal is not None
        else {"type": "output_text", "text": text, "annotations": []}
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1791100000,
        "status": status,
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "status": "completed",
                "role": "assistant",
                "content": [content],
            }
        ],
        "usage": {
            "input_tokens": tokens_in,
            "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": cache_write},
            "output_tokens": tokens_out,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": tokens_in + tokens_out,
        },
    }


class Recorder:
    """Answers each request with the next handler result and keeps the requests it saw."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        result = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(result, Exception):
            raise result
        return result


def client_for(handler: Handler) -> AsyncOpenAI:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return AsyncOpenAI(api_key="test-key", max_retries=0, http_client=http)


async def no_sleep(seconds: float) -> None:
    return None
