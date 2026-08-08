"""Async PostgreSQL engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url.get_secret_value(),
    echo=settings.debug,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    # Validates connections before use — prevents stale connection errors
    # after idle periods or database restarts.
    pool_pre_ping=True,
    # Disable prepared statement caching for PgBouncer / Supabase transaction pooling
    connect_args={
        "statement_cache_size": 0,
    },
)

# expire_on_commit=False keeps ORM objects usable after commit without
# issuing an additional SELECT to reload them.
AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# NOTE: get_db() intentionally lives in core/dependencies.py, not here —
# that version rolls back the session on an unhandled exception.
