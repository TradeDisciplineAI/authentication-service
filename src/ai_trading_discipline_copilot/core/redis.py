import redis
import json
from datetime import datetime
from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()

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
            "last_updated": datetime.utcnow().isoformat()
        })
    )

def get_market_analysis():
    from ai_trading_discipline_copilot.services.yfinance_service import YFinanceService
    symbols = YFinanceService.WATCHLIST
    gainers = []
    losers = []
    
    for symbol in symbols:
        data = get_market_data(symbol)
        if not data:
            continue
            
        current_price = data.get("price")
        previous_close = data.get("previous_close")
        
        if current_price and previous_close and previous_close > 0:
            percent_change = ((current_price - previous_close) / previous_close) * 100
            stock_data = {
                "symbol": symbol,
                "price": round(current_price, 5),
                "percent_change": round(percent_change, 2),
                "currency": data.get("currency", "USD")
            }
            if current_price > previous_close:
                gainers.append(stock_data)
            elif current_price < previous_close:
                losers.append(stock_data)
                
    gainers.sort(key=lambda x: x["percent_change"], reverse=True)
    losers.sort(key=lambda x: x["percent_change"])
    
    last_updated = datetime.utcnow().isoformat()
    analysis_data = redis_client.get("market:analysis")
    if analysis_data:
        try:
            last_updated = json.loads(analysis_data).get("last_updated", last_updated)
        except Exception:
            pass
            
    return {
        "gainers": gainers,
        "losers": losers,
        "last_updated": last_updated
    }