"""Async PostgreSQL engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()

engine = create_async_engine(
    str(settings.database_url),
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    # Validates connections before use — prevents stale connection errors
    # after idle periods or database restarts.
    pool_pre_ping=True,
)

# expire_on_commit=False keeps ORM objects usable after commit without
# issuing an additional SELECT to reload them.
AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
