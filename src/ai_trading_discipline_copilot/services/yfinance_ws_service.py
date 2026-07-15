import asyncio
from datetime import datetime
from ai_trading_discipline_copilot.services.yfinance_service import YFinanceService
from ai_trading_discipline_copilot.core.redis import save_market_data, get_market_data, get_market_analysis
from ai_trading_discipline_copilot.core.websocket_manager import manager

class YFinanceWebSocketService:
    def __init__(self):
        self.service = YFinanceService()
        self.symbols = self.service.WATCHLIST

    async def connect_and_listen(self):
        print("==================================================")
        print(f"[YFinance WS Sim] Started! Polling {len(self.symbols)} symbols...")
        print("==================================================")
        
        while True:
            try:
                # We can reuse the service's get_stock_quote function 
                # but we'll fetch them concurrently here
                quotes_map = await self._fetch_all_quotes()
                
                for symbol, quote in quotes_map.items():
                    if not quote:
                        continue
                    new_price = quote.current_price
                    timestamp = datetime.utcnow().isoformat()
                    
                    existing_data = get_market_data(symbol) or {}
                    existing_data["symbol"] = symbol
                    existing_data["price"] = new_price
                    existing_data["timestamp"] = timestamp
                    existing_data["currency"] = quote.currency
                    
                    save_market_data(symbol, existing_data)
                    
                # Broadcast the newly calculated list to all connected frontends instantly!
                await manager.broadcast(get_market_analysis())
                
                # Poll every 10 seconds to avoid Yahoo Finance rate limits
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"[YFinance WS Sim] Unexpected Error: {e}")
                await asyncio.sleep(5)
                
    async def _fetch_all_quotes(self):
        # Fetch all quotes concurrently using the yfinance service
        tasks = [self.service.get_stock_quote(symbol) for symbol in self.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = {}
        for idx, res in enumerate(results):
            if not isinstance(res, Exception):
                valid_results[self.symbols[idx]] = res
        return valid_results
