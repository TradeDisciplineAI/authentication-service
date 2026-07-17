# Testing Architecture & Infrastructure

This directory contains the automated test suite for the **AI Trading Discipline Copilot** backend. The testing infrastructure is designed for high scalability, developer ergonomics, and reliability.

---

## Directory Structure

```text
tests/
│
├── unit/                 # Pure unit tests (no database or external network I/O)
│   ├── services/         # Business logic & services tests
│   ├── repositories/     # Data access layer tests
│   ├── core/             # Configuration, security, and exception handling tests
│   └── utils/            # Helper utilities tests
│
├── integration/          # Integration tests involving multiple components (e.g. database + services)
│
├── api/                  # Endpoints & route handlers functional tests
│
├── authentication/       # Registration, login, OAuth2, MFA, and verification tests
│
├── e2e/                  # End-to-end tests (simulating complete user workflows via Playwright)
│
├── performance/          # Locust/K6 load testing scenarios
│
├── fixtures/             # Reusable pytest fixtures (loaded via pytest_plugins in conftest.py)
│   ├── database.py       # Engine creation, AsyncSession creation, lifecycle events, and DB cleanup
│   ├── client.py         # HTTPX AsyncClient and FastAPI app instances
│   ├── auth.py           # Authenticated clients and authentication headers
│   ├── users.py          # Reusable user object creators
│   ├── tokens.py         # JWT tokens and refresh token fixtures
│   └── mocks.py          # Global mocks (Resend email service, slowapi rate limiting)
│
├── factories/            # Test data generators (Factory Boy)
│   └── user_factory.py   # Factory generator placeholder for User models
│
├── helpers/              # Common assertions, JWT decoding, and DB seed utilities
│   ├── assertions.py     # Custom domain/API assertions
│   ├── jwt.py            # Token generation/decoding utilities
│   └── database.py       # DB schema and seeding utilities
│
├── conftest.py           # Test suite configuration and plugin registry
└── README.md             # This documentation
```

---

## Testing Principles & Conventions

1. **Isolation**: Tests must run against a clean database state. The `database.py` fixture drops and recreates tables before every test.
2. **Naming Conventions**:
   - Files: Must start with `test_` (e.g., `test_auth.py`).
   - Functions: Must start with `test_` (e.g., `test_register_success`).
   - Classes: Must start with `Test` (e.g., `TestPasswordReset`).
3. **Mocks vs. Real Services**:
   - Mock all third-party external APIs (e.g., Resend, Finnhub, OpenAI) using pytest-mock/unittest.mock.
   - Use a test database for database interactions; do not mock database tables or queries in integration/api tests unless specifically required.
4. **Async Support**: Use `@pytest.mark.anyio` or `@pytest.mark.asyncio` for asynchronous test functions.

---

## Running Tests

### 1. Prerequisites
Ensure Docker is running, and the PostgreSQL/Redis database services are active:
```bash
docker compose up -d db redis
```

### 2. Execution
Run the test suite using `uv` (recommended):
```bash
# Run all tests
uv run pytest

# Run a specific test category (e.g., Authentication)
uv run pytest tests/authentication/

# Run tests and generate coverage report
uv run pytest --cov=src --cov-report=term-missing
```

---

## Future Testing Strategy

* **Factory Boy**: Migrate manual DB object creation in tests to Factory Boy factories (located in `tests/factories/`) to reduce setup boilerplate.
* **Playwright**: Implement frontend-backend browser-based test scenarios in `tests/e2e/`.
* **CI/CD Integration**: Add a GitHub Action workflow to automatically run tests and verify coverage limits before code merges.
* **Security Scanning**: Integrate Bandit/Trivy/Semgrep scans on codebase and dependency layers.
