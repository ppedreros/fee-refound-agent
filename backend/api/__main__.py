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
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
