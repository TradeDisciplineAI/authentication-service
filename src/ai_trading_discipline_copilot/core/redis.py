import json
import logging
from datetime import UTC, datetime

import redis.asyncio as redis

from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True
)


def get_redis_client() -> redis.Redis:
    """Return a fresh async Redis client for explicit lifecycle management (e.g. in Celery tasks)."""
    return redis.from_url(settings.redis_url, decode_responses=True)


async def save_market_data(symbol: str, data: dict, client: redis.Redis | None = None) -> None:
    r = client or redis_client
    await r.set(
        f"market:{symbol}",
        json.dumps(data)
    )


async def get_market_data(symbol: str, client: redis.Redis | None = None) -> dict | None:
    r = client or redis_client
    data = await r.get(f"market:{symbol}")
    if data:
        return json.loads(data)
    return None


async def save_market_analysis(gainers: list, losers: list, client: redis.Redis | None = None) -> None:
    r = client or redis_client
    await r.set(
        "market:analysis",
        json.dumps({
            "gainers": gainers,
            "losers": losers,
            "last_updated": datetime.now(UTC).isoformat()
        })
    )


async def get_market_analysis(client: redis.Redis | None = None) -> dict:
    r = client or redis_client
    data = await r.get("market:analysis")
    if data:
        try:
            parsed = json.loads(data)
            if parsed.get("gainers") or parsed.get("losers"):
                return parsed
        except Exception:
            logger.exception("Failed to parse market analysis from Redis")

    # Cold start fallback: fetch immediately if cache is empty
    try:
        from ai_trading_discipline_copilot.tasks.market_tasks import _update_market_price_async
        await _update_market_price_async()
        data = await r.get("market:analysis")
        if data:
            return json.loads(data)
    except Exception:
        logger.exception("Failed to populate market analysis on cold start")

    return {"gainers": [], "losers": [], "last_updated": None}
