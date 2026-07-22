import logging
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_trading_discipline_copilot.core.database import Base
from ai_trading_discipline_copilot.models.user import User

logger = logging.getLogger(__name__)

# Single source of truth — conftest.py sets TEST_DATABASE_URL before any fixture runs.
LOCAL_TEST_DB = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5434/trading_test_db",
)
parsed = urlsplit(LOCAL_TEST_DB)
TEST_DATABASE_URL = LOCAL_TEST_DB

# Derive the database name and admin URL directly from TEST_DATABASE_URL so
# create_test_db() always targets the same database as the test engine.
_db_name = parsed.path.lstrip("/")  # e.g. "trading_test_db"
admin_url = urlunsplit(parsed._replace(path="/postgres"))

# Guard: only allow destructive schema resets on local/test hosts to prevent
# accidentally nuking a shared or production database.
_SAFE_HOSTS = {"localhost", "127.0.0.1", "::1", "shared_test_db"}
_test_host = parsed.hostname or ""
if _test_host not in _SAFE_HOSTS:
    raise RuntimeError(
        f"TEST_DATABASE_URL points to non-local host '{_test_host}'. "
        "Destructive schema resets are only allowed on local test databases. "
        "Set TEST_DATABASE_URL to a localhost instance."
    )


async def create_test_db() -> None:
    """Create the test database if it does not exist."""
    try:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname='{_db_name}'")  # noqa: S608
            )
            if not result.scalar():
                await conn.execute(text(f'CREATE DATABASE "{_db_name}"'))  # noqa: S608
        await engine.dispose()
    except OSError as exc:
        # PostgreSQL host not reachable (e.g. Docker not started) — skip creation.
        logger.debug("Test DB host unreachable, skipping creation: %s", exc)
    except Exception as exc:  # noqa: BLE001
        # Covers asyncpg connection errors and "already exists" races.
        # Re-raise anything that is not a connection-level failure so real
        # misconfigurations surface immediately instead of being silently hidden.
        if "already exists" in str(exc).lower() or "connection" in str(exc).lower():
            logger.debug("Database creation skipped: %s", exc)
        else:
            raise


# Enterprise PostgreSQL schemas used by the application.
SCHEMAS = (
    "public",
    "authentication",
    "market",
    "sentiment",
    "strategy",
    "risk",
    "execution",
    "learning",
    "discipline",
    "analytics",
    "audit",
    "system",
)


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    """Create a database engine scoped to the test's event loop."""
    await create_test_db()

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"statement_cache_size": 0},
    )

    # Recreate schemas for every test to ensure 100% clean test isolation
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            if schema == "public":
                await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
            else:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(
    db_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Yield a session factory bound to the test engine."""
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Yield a database session from the test session factory."""
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def patch_session_factory(
    db_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[None]:
    """Patch the global AsyncSessionFactory and engine to use the test database
    during tests.
    """
    from ai_trading_discipline_copilot.core import database

    old_factory = database.AsyncSessionFactory
    old_engine = database.engine
    database.AsyncSessionFactory = session_factory
    database.engine = db_engine
    yield
    database.AsyncSessionFactory = old_factory
    database.engine = old_engine


# Event listener to set is_verified=True on User instantiation if not explicitly passed.
# This prevents existing tests from failing since email verification wasn't present.


@event.listens_for(User, "init")
def receive_init(target: Any, args: Any, kwargs: dict[str, Any]) -> None:
    if "is_verified" not in kwargs:
        kwargs["is_verified"] = True
