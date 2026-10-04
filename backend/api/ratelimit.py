"""Rate limits per client (SPEC-api, "Conventions"): `RATE_LIMIT` (60/minute) on every route,
and 10/minute more on starting a check. Over the limit, a friendly 429 with `Retry-After`.

Built on `limits`, the library slowapi wraps: slowapi keeps its limiter and its per-route limits
at module level, so every app (and every test) would share one counter; this middleware belongs
to its app. The client is the connection's address; behind nginx every browser shares it, which
is fine for a single staff tool.
"""

import math
import re
import time

from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

RUN_LIMIT = "10/minute"
RUN_PATH = re.compile(r"/cases/\d+/run")
MESSAGE = "You're going a bit fast. Please wait a few seconds."


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, *, limit: str, run_limit: str = RUN_LIMIT) -> None:
        self.app = app
        self.limiter = MovingWindowRateLimiter(MemoryStorage())
        self.limit = parse(limit)
        self.run_limit = parse(run_limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope["client"][0] if scope.get("client") else "unknown"
        limits = [(self.limit, "all")]
        if scope["method"] == "POST" and RUN_PATH.fullmatch(scope["path"]):
            limits.append((self.run_limit, "run"))
        for item, bucket in limits:
            if not self.limiter.hit(item, bucket, client):
                await self._refuse(item, bucket, client)(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _refuse(self, item: RateLimitItem, bucket: str, client: str) -> JSONResponse:
        reset_at = self.limiter.get_window_stats(item, bucket, client).reset_time
        retry_after = max(1, math.ceil(reset_at - time.time()))
        return JSONResponse(
            {"error": {"code": "rate_limited", "message": MESSAGE}},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
