"""One error shape for every response (SPEC-api, "Conventions"): `code` is for UI logic only,
`message` is what Luis may see. Full hardening (validation details, the friendly 500) is T37."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


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
