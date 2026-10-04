"""JSON logs for the whole backend (SPEC-platform, "Logging and request ids").

Every line is one JSON object with `ts`, `level`, `event` and `request_id` (null outside a
request). Lines from libraries (uvicorn, SQLAlchemy) go through the same processors as ours.
The deny-list is a safety net: code must not log personal data in the first place.
"""

import hashlib
import hmac
import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from pydantic import SecretStr
from structlog.typing import EventDict, Processor, WrappedLogger

DROPPED_KEYS = frozenset(
    {"body", "message", "text", "name", "first_name", "last_name", "account_number", "email"}
)
HASHED_KEYS = frozenset({"member_id"})


class DenyList:
    """Drops personal fields and replaces member ids with a salted hash, at any depth."""

    def __init__(self, salt: SecretStr) -> None:
        self._salt = salt.get_secret_value().encode()

    def __call__(self, logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
        return self._clean(event_dict)

    def _clean(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in fields.items():
            if key in DROPPED_KEYS:
                continue
            if key in HASHED_KEYS and value is not None:
                cleaned[key] = self._hash(value)
            elif isinstance(value, Mapping):
                cleaned[key] = self._clean(value)
            else:
                cleaned[key] = value
        return cleaned

    def _hash(self, value: object) -> str:
        return hmac.new(self._salt, str(value).encode(), hashlib.sha256).hexdigest()[:16]


def _default_request_id(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    event_dict.setdefault("request_id", None)
    return event_dict


def configure_logging(level: str, salt: SecretStr) -> None:
    """Send every log line, ours and the libraries', to stdout as JSON."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        _default_request_id,
        DenyList(salt),
    ]
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn's own handlers print plain text; send its lines through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    # The request-id middleware writes the access line, with the request id in it.
    logging.getLogger("uvicorn.access").disabled = True
