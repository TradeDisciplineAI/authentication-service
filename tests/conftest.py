import os

from ai_trading_discipline_copilot.core.config import get_settings

# Single source of truth for the test database URL.
# tests/fixtures/database.py reads TEST_DATABASE_URL so both the application
# settings and the SQLAlchemy test engine always point at the same host.
_TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5434/trading_test_db",
)
os.environ["TEST_DATABASE_URL"] = _TEST_DB_URL
os.environ["DATABASE_URL"] = _TEST_DB_URL

# Configure test-only allowed hosts before importing the FastAPI application.
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'
get_settings.cache_clear()

pytest_plugins = [
    "tests.fixtures.database",
    "tests.fixtures.client",
    "tests.fixtures.mocks",
    "tests.fixtures.auth",
    "tests.fixtures.users",
    "tests.fixtures.tokens",
]
