# ─────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for ai-trading-discipline-copilot
#
# Stage 1 (builder) — installs all dependencies using uv
# Stage 2 (runtime) — lean production image, no build tools, non-root user
# ─────────────────────────────────────────────────────────────────────────────


# ── Stage 1: Builder ──────────────────────────────────────────────────────────
# Standard Python Slim image (from Docker Hub, no ghcr.io login needed)
FROM python:3.13-slim-bookworm AS builder

# Install uv via pip
RUN pip install --no-cache-dir uv

WORKDIR /app

# Compile Python bytecode for faster startup in production
ENV UV_COMPILE_BYTECODE=1
# Use copy mode — works correctly when source and target are on different
# filesystems (common in Docker layer caching scenarios)
ENV UV_LINK_MODE=copy

# ── Install dependencies (cached layer — only re-runs if lockfile changes) ────
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ── Install the project itself ────────────────────────────────────────────────
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
# Clean Debian Slim — no uv, no build tools, minimal attack surface
FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

# ── Security: run as non-root user ───────────────────────────────────────────
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser

# ── Copy only what's needed from builder ─────────────────────────────────────
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src   /app/src

# ── Environment ───────────────────────────────────────────────────────────────
# Add virtualenv binaries to PATH
ENV PATH="/app/.venv/bin:$PATH"
# Add src/ to PYTHONPATH so the package is importable
ENV PYTHONPATH="/app/src"
# Prevent Python from writing .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
# Prevent Python from buffering stdout/stderr (important for container logs)
ENV PYTHONUNBUFFERED=1

# ── Switch to non-root ────────────────────────────────────────────────────────
USER appuser

# ── Port ──────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Health Check ──────────────────────────────────────────────────────────────
# Uses stdlib urllib — no curl or extra packages needed
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# ── Start the server ──────────────────────────────────────────────────────────
# NOTE: Update this path when main.py is created by the team:
#   ai_trading_discipline_copilot.main:app
# --workers 1  → use 1 worker per container (scale via replicas, not workers)
# --host 0.0.0.0 → listen on all interfaces inside the container
CMD ["uvicorn", "ai_trading_discipline_copilot.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
