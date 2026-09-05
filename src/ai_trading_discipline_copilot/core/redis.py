import logging

import redis.asyncio as redis

from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

redis_client = redis.from_url(
    settings.redis_url,
    decode_responses=True,
)


def get_redis_client() -> redis.Redis:
    """Return a fresh async Redis client for explicit lifecycle management (e.g. in Celery tasks)."""
    return redis.from_url(settings.redis_url, decode_responses=True)
