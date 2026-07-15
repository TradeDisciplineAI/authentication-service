import random
from datetime import datetime


def generate_market_price(symbol: str):
    return {
        "symbol": symbol,
        "price": round(random.uniform(400, 500), 2),
        "timestamp": datetime.utcnow().isoformat()
    }