import json
import logging
from datetime import UTC, datetime

import redis

from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True
)

def save_market_data(symbol, data):
    redis_client.set(
        f"market:{symbol}",
        json.dumps(data)
    )

def get_market_data(symbol):
    data = redis_client.get(f"market:{symbol}")
    if data:
        return json.loads(data)
    return None

def save_market_analysis(gainers, losers):
    redis_client.set(
        "market:analysis",
        json.dumps({
            "gainers": gainers,
            "losers": losers,
            "last_updated": datetime.now(UTC).isoformat()
        })
    )

def get_market_analysis():
    data = redis_client.get("market:analysis")
    if data:
        try:
            return json.loads(data)
        except Exception:
            logger.exception("Failed to parse market analysis from Redis")
    return {"gainers": [], "losers": [], "last_updated": None}
