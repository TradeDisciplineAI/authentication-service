import logging
import random
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def generate_market_price(symbol: str):
    return {
        "symbol": symbol,
        "price": round(random.uniform(400, 500), 2),
        "timestamp": datetime.now(UTC).isoformat()
    }
