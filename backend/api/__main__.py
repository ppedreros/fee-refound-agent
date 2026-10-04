"""Entrypoint: `python -m backend.api`. Checks the configuration before serving."""

import sys

import uvicorn

from backend.api.main import create_app
from backend.core.settings import ConfigError, load_settings


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as error:
        sys.exit(f"Invalid configuration: {error}")
    # create_app sets up JSON logging; uvicorn must not replace it with its own config.
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
