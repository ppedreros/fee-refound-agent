"""One error shape for every response (SPEC-api, "Conventions"): `code` is for UI logic only,
`message` is what Luis may see. No response ever holds a traceback."""

import traceback
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = structlog.get_logger()

# Starlette's own errors (no route, wrong method), in the same shape as ours.
HTTP_ERRORS = {
    404: ("not_found", "We couldn't find that page."),
    405: ("method_not_allowed", "That isn't something this page can do."),
}
UNEXPECTED = ("internal_error", "Something went wrong on our side. Please try again.")


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, extra: dict[str, Any] | None = None
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}


NOT_FOUND = ("not_found", "We couldn't find that conversation.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        body = {"error": {"code": error.code, "message": error.message}, **error.extra}
        return JSONResponse(body, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        body = {
            "error": {
                "code": "invalid_request",
                "message": "Something in that request isn't valid.",
            }
        }
        return JSONResponse(body, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code, message = HTTP_ERRORS.get(error.status_code, UNEXPECTED)
        return JSONResponse(
            {"error": {"code": code, "message": message}},
            status_code=error.status_code,
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        # Logged with the request id (bound by the middleware) and where it happened, but never
        # with the error's message, which can carry data from the case.
        frame = traceback.extract_tb(error.__traceback__)[-1] if error.__traceback__ else None
        log.error(
            "unhandled_error",
            error=type(error).__name__,
            at=f"{frame.filename}:{frame.lineno}" if frame else None,
            path=request.url.path,
        )
        code, message = UNEXPECTED
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=500)
