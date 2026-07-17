# AI Trading Discipline Copilot

> **AI-powered trading psychology and discipline assistant backend built with FastAPI.**
> Log trades, journal your sessions, track your emotional state, and receive personalised AI coaching to become a more disciplined trader.

---

## 🏗️ Architecture

```
src/ai_trading_discipline_copilot/
├── core/               ← Foundation: config, database, security, exceptions, dependencies
├── models/             ← SQLAlchemy ORM models (PostgreSQL)
├── schemas/            ← Pydantic request/response validation
├── services/           ← Business logic layer
├── routers/            ← FastAPI HTTP endpoints
└── __init__.py         ← App factory (create_app)

alembic/                ← Database migrations
```

## ⚙️ Tech Stack

| Concern | Library |
|---|---|
| Framework | FastAPI (async) |
| Database | PostgreSQL via asyncpg |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Auth | JWT via python-jose + bcrypt |
| Settings | pydantic-settings |
| AI Coaching | OpenAI GPT-4o (swappable) |
| Package Manager | uv |

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.13+
- PostgreSQL running locally (or via Docker)
- [uv](https://docs.astral.sh/uv/) installed

### 2. Clone & Install
```bash
git clone <repo-url>
cd ai-trading-discipline-copilot
uv sync --all-groups
```

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your database URL, secret key, and OpenAI API key
```

Generate a strong secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Run Database Migrations
```bash
# Create the initial migration (first time only)
uv run alembic revision --autogenerate -m "initial schema"

# Apply migrations
uv run alembic upgrade head
```

### 5. Start the Development Server
```bash
uv run fastapi dev src/ai_trading_discipline_copilot/__init__.py
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## 📡 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | ❌ | Health check |
| POST | `/auth/register` | ❌ | Create account |
| POST | `/auth/login` | ❌ | Get JWT token |
| GET | `/trades` | ✅ | List my trades |
| POST | `/trades` | ✅ | Log a new trade |
| GET | `/trades/{id}` | ✅ | Get single trade |
| PUT | `/trades/{id}` | ✅ | Update / close trade |
| DELETE | `/trades/{id}` | ✅ | Delete trade |
| GET | `/journal` | ✅ | List journal entries |
| POST | `/journal` | ✅ | Create journal entry |
| GET | `/journal/{id}` | ✅ | Get single entry |
| DELETE | `/journal/{id}` | ✅ | Delete entry |
| POST | `/psychology/log` | ✅ | Log emotional state |
| GET | `/psychology/summary` | ✅ | Get discipline analytics |
| POST | `/coaching/analyze` | ✅ | Get AI coaching |

---

## 🧪 Running Tests
```bash
uv run pytest
# With coverage report:
uv run pytest --cov=src --cov-report=html
```

## 🔍 Linting & Type Checking
```bash
uv run ruff check src tests
uv run mypy src
```

### Pre-commit Hooks
We use `pre-commit` to automate fast validation checks (formatting, linting, basic file checks, and type-checking) locally before every commit.

To set up the pre-commit git hooks:
```bash
uv run pre-commit install
```

To manually trigger the pre-commit check on all files:
```bash
uv run pre-commit run --all-files
```

## 🗄️ Creating a New Migration
```bash
# After changing a model:
uv run alembic revision --autogenerate -m "describe your change"
uv run alembic upgrade head
```

---

## 📄 License

MIT
# ai-trading-discipline-copilot

# Testing-integration
