"""The async SQLAlchemy engine, and a database ping that never raises."""

import asyncio

from pydantic import SecretStr
from sqlalchemy import literal, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def make_engine(url: SecretStr) -> AsyncEngine:
    # pre_ping drops pooled connections that died, for example after a database restart.
    return create_async_engine(url.get_secret_value(), pool_pre_ping=True)


async def ping(engine: AsyncEngine, timeout_s: float) -> bool:
    """True when the database answers `SELECT 1` within `timeout_s`."""
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as connection:
            await connection.execute(select(literal(1)))
    except TimeoutError, OSError, SQLAlchemyError:
        return False
    return True
