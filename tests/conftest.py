"""Settings shared by every test."""

import asyncio
from collections.abc import Mapping

import pytest
from pytest_asyncio.plugin import LoopFactory


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, LoopFactory]:
    # psycopg's async mode can't run on Windows' default (Proactor) loop. A selector loop is the
    # default on Linux, so every async test runs the same everywhere.
    return {"selector": asyncio.SelectorEventLoop}
