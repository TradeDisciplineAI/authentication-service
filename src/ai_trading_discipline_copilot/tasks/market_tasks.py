import asyncio
from datetime import datetime
from ai_trading_discipline_copilot.core.celery import celery_app
from ai_trading_discipline_copilot.services.yfinance_service import YFinanceService

from ai_trading_discipline_copilot.core.redis import (
    save_market_data,
    get_market_data,
    save_market_analysis
)

async def _fetch_all_quotes(symbols, yfinance_service):
    sem = asyncio.Semaphore(15)
    async def fetch(symbol):
        async with sem:
            return symbol, await yfinance_service.get_stock_quote(symbol)
    
    tasks = [fetch(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_results = {}
    for res in results:
        if isinstance(res, tuple) and len(res) == 2:
            if isinstance(res[1], Exception):
                print(f"Error fetching real data for {res[0]}: {res[1]}")
            else:
                valid_results[res[0]] = res[1]
    return valid_results

@celery_app.task
def update_market_price():
    # Initialize Yahoo Finance Service
    yfinance_service = YFinanceService()
    
    # Grab all the stocks from your YFinanceService WATCHLIST
    symbols = yfinance_service.WATCHLIST
    
    gainers = []
    losers = []
    
    # Fetch all quotes concurrently (much faster!)
    quotes_map = asyncio.run(_fetch_all_quotes(symbols, yfinance_service))

    for symbol in symbols:
        if symbol not in quotes_map:
            continue
            
        # Get old price from Redis
        old_data = get_market_data(symbol)
        old_price = old_data.get("price") if old_data else None

        # Process the newly fetched price
        try:
            quote = quotes_map[symbol]
            new_price = quote.current_price
            
            new_data = {
                "symbol": symbol,
                "price": new_price,
                "timestamp": datetime.utcnow().isoformat(),
                "previous_close": quote.previous_close,
                "currency": quote.currency
            }

            # Save new price to Redis
            save_market_data(symbol, new_data)

            # Compare and categorize based on daily previous close
            if quote.previous_close is not None and quote.previous_close > 0:
                percent_change = ((new_price - quote.previous_close) / quote.previous_close) * 100
                stock_data = {
                    "symbol": symbol,
                    "price": round(new_price, 5),
                    "percent_change": round(percent_change, 2),
                    "currency": quote.currency
                }

                if new_price > quote.previous_close:
                    gainers.append(stock_data)
                elif new_price < quote.previous_close:
                    losers.append(stock_data)
                
            print(f"Updated REAL {symbol}: {new_data}")
        
        except Exception as e:
            print(f"Error processing real data for {symbol}: {e}")

    # Print Gainers and Losers Analysis
    print("=" * 30)
    print("MARKET ANALYSIS (GAINERS & LOSERS)")
    print("=" * 30)
    if gainers:
        print("📈 GAINERS:")
        for g in gainers:
            print(f"  - {g['symbol']} (↑ ${g['price']} / +{g['percent_change']}%)")
    else:
        print("📈 GAINERS: None")
        
    if losers:
        print("📉 LOSERS:")
        for l in losers:
            print(f"  - {l['symbol']} (↓ ${l['price']} / {l['percent_change']}%)")
    else:
        print("📉 LOSERS: None")
    print("=" * 30)
    save_market_analysis(gainers, losers)
    
    return "Market Updated"