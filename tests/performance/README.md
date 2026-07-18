# Performance & Load Testing with Locust

This directory contains the production-quality performance testing suite built with [Locust](https://locust.io/) for the AI Trading Discipline Copilot backend.

---

## Architecture & Design Principles

The load testing framework features **automatic test-user provisioning**, multi-account user pools, and **native automatic report generation**:

```
tests/performance/
├── __init__.py          # Package initialization
├── locustfile.py        # Main Locust entry point (HttpUser lifecycle & @events hooks)
├── config.py            # Environment & Report configuration settings
├── provisioner.py       # Automatic test-user provisioning module
├── reporter.py          # Native Locust HTML & CSV report generator
├── utils.py             # Helper utilities (headers, JSON parsing)
├── users.json           # Auto-generated user pool JSON file
├── tasks/
│   ├── __init__.py      # Tasks package init
│   └── auth_tasks.py    # Reusable authentication task definitions
└── README.md            # Documentation & execution guide
```

---

## Configurable Login Rate Limiting (ENG-38.4)

### Why Login Rate Limiting Exists
In production, the `/auth/login` endpoint is rate limited (e.g. 10 requests/minute per IP) to protect the backend against automated brute-force attacks and credential stuffing.

### Why Rate Limiting is Problematic During Load Testing
During performance benchmarks, all simulated Locust virtual users originate from the **same client IP address** (e.g., `127.0.0.1` or the load generator server). Consequently, high-concurrency swarms hit the IP rate limit almost instantly, returning HTTP 429 status codes even though the backend application and database are operating healthy.

### Environment Variable Configuration

To allow realistic authentication load testing without modifying security rules for other endpoints or modifying Locust, login rate limiting is configurable via `ENABLE_LOGIN_RATE_LIMITING`:

#### Production Environment (Default)
```bash
ENABLE_LOGIN_RATE_LIMITING=true
```
- Rate limiting is **active** on `/auth/login` (HTTP 429 issued when limit exceeded).
- Production security is 100% preserved.

#### Performance Testing Environment
```bash
ENABLE_LOGIN_RATE_LIMITING=false
```
- Rate limiting check is **bypassed** specifically for `/auth/login`.
- Authentication, password verification, JWT creation, refresh cookies, and session auditing operate normally.
- All other rate-limited endpoints (`/auth/register`, `/auth/password-reset`) remain rate-limited.

#### Docker Compose Performance Environment (ENG-38.9)
In Docker Compose, environment variables are isolated from the host shell unless explicitly passed in `docker-compose.yml`. The `app` service environment block includes:

```yaml
environment:
  - ENABLE_LOGIN_RATE_LIMITING=${ENABLE_LOGIN_RATE_LIMITING:-false}
```

- **Host `.env` vs Docker Compose**: Docker Compose reads `${ENABLE_LOGIN_RATE_LIMITING}` from your host `.env` file or environment. If unset, it defaults to `false` for development and performance load testing against `http://localhost:8000`.
- **To test Docker in Production Mode**: Pass `ENABLE_LOGIN_RATE_LIMITING=true` in `.env` or run `docker compose up -d app` with `ENABLE_LOGIN_RATE_LIMITING=true`.

> [!WARNING]
> Production environments MUST ALWAYS keep `ENABLE_LOGIN_RATE_LIMITING=true`. Set `ENABLE_LOGIN_RATE_LIMITING=false` ONLY in dedicated performance testing environments.

---

## Authentication Lifecycle & Rate-Limiting Protection

Each Locust virtual user represents a single client session with the following lifecycle:

```
Virtual User Spawn (on_start)
         │
         ▼
Round-Robin Account Assignment (get_next_account)
         │
         ▼
Single Login Request (POST /auth/login)
  ├── Success (200 OK): Store access_token & refresh cookie -> Execute authenticated @tasks
  └── Rate Limited (429): Log warning -> Session remains unauthenticated (no retry storm)
         │
         ▼
Swarming Phase (@task)
  ├── @task(3) /auth/me      (Runs ONLY if access_token exists)
  ├── @task(2) /auth/refresh (Runs ONLY if access_token exists)
  └── @task(1) /health       (Runs for all users as baseline)
         │
         ▼
Teardown (on_stop)
  └── Revoke Session (POST /auth/logout)
```

---

## Testing Workflows: Interactive vs Headless

Locust supports two distinct operational modes depending on your testing goals.

### Comparison Overview

| Feature | Interactive Web UI Mode | Headless CLI Mode |
| :--- | :--- | :--- |
| **Execution Command** | `uv run locust -f tests/performance/locustfile.py` | `uv run locust -f tests/performance/... --headless` |
| **Configuration Interface** | Browser Web UI (`http://localhost:8089`) | CLI flags (`-u`, `-r`, `--run-time`) |
| **Duration Limit (`--run-time`)** | **Not supported in Web UI** (Manual start/stop) | **Supported** (Automatic shutdown on timer) |
| **Report Generation** | Generated automatically when user clicks **Stop** | Generated automatically on `--run-time` completion |
| **Primary Use Case** | Real-time debugging, visual monitoring, exploratory tests | Automated CI/CD pipelines, regression benchmarks |

---

### 1. Interactive Web UI Workflow

In Interactive Mode, you control the load test manually via Locust's browser interface.

> [!NOTE]
> The Locust Web UI does **not** use the `--run-time` duration flag. Load tests in the Web UI run continuously until you manually click **Stop**.

#### Step-by-Step Execution:

1. **Start Backend Server in Performance Mode**:
   ```bash
   ENABLE_LOGIN_RATE_LIMITING=false uv run uvicorn ai_trading_discipline_copilot.main:app --host 127.0.0.1 --port 8000
   ```

2. **Launch Locust Web Server**:
   ```bash
   uv run locust -f tests/performance/locustfile.py --host http://localhost:8000
   ```

3. **Configure & Control in Web UI**:
   - Open browser to [http://localhost:8089](http://localhost:8089).
   - Enter **Number of Users** (e.g. `100`) and **Spawn Rate** (e.g. `5`).
   - Click **Start swarming**.
   - Monitor real-time throughput charts, response time graphs, and failure rates.
   - Let the test run for your desired test duration.
   - Click **Stop** to conclude the test session.

4. **Automatic Report Generation**:
   Upon clicking **Stop**, Locust automatically generates native HTML and CSV reports inside `reports/authentication/<TIMESTAMP>/`.

---

### 2. Headless CLI Workflow

Headless Mode runs without a browser interface and automatically terminates after the specified `--run-time`.

#### Step-by-Step Execution:

```bash
uv run locust -f tests/performance/locustfile.py \
  --host http://localhost:8000 \
  --headless \
  -u 100 \
  -r 5 \
  --run-time 30s
```

---

## Native Automatic Report Generation

When any load test completes (Web UI stop or Headless timer completion), performance reports are **automatically saved** using Locust's native reporting engine (`locust.html` and `locust.stats`).

### Report Directory Structure

All test outputs are stored inside timestamped directories under `reports/authentication/`:

```
reports/
└── authentication/
    └── 2026-07-18_20-15-43/
        ├── auth-report.html
        ├── auth-report_stats.csv
        ├── auth-report_failures.csv
        ├── auth-report_exceptions.csv
        └── auth-report_stats_history.csv
```

---

## Configuration Options

Settings can be customized via environment variables:

| Environment Variable | Description | Default |
| :--- | :--- | :--- |
| `ENABLE_LOGIN_RATE_LIMITING` | Enable/disable login endpoint rate limiting (`true`/`false`) | `true` |
| `LOCUST_HOST` / `BASE_URL` | Target FastAPI server base URL | `http://localhost:8000` |
| `LOCUST_REPORT_DIRECTORY` | Output directory for performance reports | `reports/authentication` |
| `LOCUST_REPORT_FILENAME_PREFIX` | Prefix for generated report filenames | `auth-report` |
| `LOCUST_ENABLE_TIMESTAMPED_REPORTS` | Organize reports in timestamped folders (`true`/`false`) | `true` |
| `LOCUST_AUTO_PROVISION` | Enable/disable automatic user creation (`true`/`false`) | `true` |
| `LOCUST_USERS` / `NUM_USERS` | Required virtual users (triggers provisioning) | `20` |
| `LOCUST_USER_PREFIX` | Email and username prefix for load accounts | `loadtest` |
| `LOAD_TEST_PASSWORD` | Password assigned to generated accounts | `Password123!` |
