import pytest
from httpx import ASGITransport, AsyncClient

from ai_trading_discipline_copilot.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint() -> None:
    """Verify /metrics endpoint returns HTTP 200 OK and Prometheus metric text."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        response = await ac.get("/metrics")
        assert response.status_code == 200
        assert (
            "http_requests_total" in response.text
            or "process_cpu_seconds_total" in response.text
        )


@pytest.mark.asyncio
async def test_health_endpoint_unchanged() -> None:
    """Verify /health endpoint remains functional and unchanged."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
