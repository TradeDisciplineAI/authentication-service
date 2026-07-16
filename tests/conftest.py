import os

# Configure test-only allowed hosts before importing the FastAPI application.
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

pytest_plugins = [
    "tests.fixtures.database",
    "tests.fixtures.client",
    "tests.fixtures.mocks",
    "tests.fixtures.auth",
    "tests.fixtures.users",
    "tests.fixtures.tokens",
]
