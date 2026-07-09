import os
from collections.abc import AsyncGenerator, Generator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Configure test-only allowed hosts before importing the FastAPI application.
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.database import Base
from ai_trading_discipline_copilot.core.dependencies import get_db
from ai_trading_discipline_copilot.main import app
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
        await conn.run_sync(Base.metadata.drop_all)
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


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient]:
    """Yield an AsyncClient with the database dependency overridden to use tests."""

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_resend_emails() -> Generator[None]:
    """Globally mock resend email calls during tests to prevent API key errors."""
    from unittest.mock import patch

    with (
        patch("resend.Emails.send") as _mock_send,
        patch("resend.Emails.send_async") as _mock_send_async,
    ):
        yield


@pytest.fixture(autouse=True)
def disable_limiter() -> Generator[None]:
    """Globally disable the slowapi rate limiter for functional tests."""
    from ai_trading_discipline_copilot.core.limiter import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


# Event listener to set is_verified=True on User instantiation if not explicitly passed.
# This prevents existing tests from failing since email verification wasn't present.


@event.listens_for(User, "init")
def receive_init(target: Any, args: Any, kwargs: dict[str, Any]) -> None:
    if "is_verified" not in kwargs:
        kwargs["is_verified"] = True
