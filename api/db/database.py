from collections.abc import AsyncGenerator

import asyncpg
from asyncpg import Connection, Pool

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger(__name__)

_pool: Pool | None = None


def _clean_url(url: str) -> str:
    """asyncpg only understands postgresql://, not postgresql+asyncpg://"""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def create_pool() -> None:
    global _pool
    settings = get_settings()
    dsn = _clean_url(settings.DATABASE_URL)
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    logger.info("db_pool_created", min_size=2, max_size=10)


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call create_pool() first.")
    return _pool


async def get_db() -> AsyncGenerator[Connection, None]:
    """FastAPI dependency — yields a connection from the pool."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db_pool_closed")


async def check_db_connection() -> None:
    """Raises if the DB is unreachable. Used by GET /health/ready."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")
