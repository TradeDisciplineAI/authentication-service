# =============================================================================
# Builder Stage
# =============================================================================
FROM python:3.13-slim-bookworm AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml ./

# Install only dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --python /usr/local/bin/python3 \
    --no-install-project \
    --no-dev

COPY . .

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --python /usr/local/bin/python3 \
    --no-dev


# =============================================================================
# Runtime Stage
# =============================================================================
FROM python:3.13-slim-bookworm

WORKDIR /app

RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup appuser

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src /app/src
COPY --from=builder --chown=appuser:appgroup /app/alembic /app/alembic
COPY --from=builder --chown=appuser:appgroup /app/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "ai_trading_discipline_copilot.main:app", "--host", "0.0.0.0", "--port", "8000"]