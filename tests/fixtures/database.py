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

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.database import Base
from ai_trading_discipline_copilot.models.user import User

settings = get_settings()

db_url = settings.database_url.get_secret_value()
parsed = urlsplit(db_url)
TEST_DATABASE_URL = urlunsplit(parsed._replace(path="/trading_test_db"))
admin_url = urlunsplit(parsed._replace(path="/postgres"))


async def create_test_db() -> None:
    """Create the test database if it does not exist."""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname='trading_test_db'")
        )
        if not result.scalar():
            await conn.execute(text("CREATE DATABASE trading_test_db"))
    await engine.dispose()


@pytest.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    """Create a database engine scoped to the test's event loop."""
    await create_test_db()

    engine = create_async_engine(TEST_DATABASE_URL)

    # Recreate tables for every test to ensure a clean state and avoid loop mismatch
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
        await conn.execute(text("CREATE SCHEMA auth"))

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
    session_factory: async_sessionmaker[AsyncSession],
) -> Generator[None]:
    """Patch the global AsyncSessionFactory to use the test session factory
    during tests.
    """
    from ai_trading_discipline_copilot.core import database

    old_factory = database.AsyncSessionFactory
    database.AsyncSessionFactory = session_factory
    yield
    database.AsyncSessionFactory = old_factory


# Event listener to set is_verified=True on User instantiation if not explicitly passed.
# This prevents existing tests from failing since email verification wasn't present.


@event.listens_for(User, "init")
def receive_init(target: Any, args: Any, kwargs: dict[str, Any]) -> None:
    if "is_verified" not in kwargs:
        kwargs["is_verified"] = True
