import asyncio
import logging
from datetime import UTC, datetime

from ai_trading_discipline_copilot.core.celery import celery_app
from ai_trading_discipline_copilot.core.redis import (
    get_market_data,
    save_market_analysis,
    save_market_data,
)
from ai_trading_discipline_copilot.services.yfinance_service import YFinanceService

logger = logging.getLogger(__name__)


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
                logger.error("Error fetching real data for %s: %s", res[0], res[1])
            else:
                valid_results[res[0]] = res[1]
    return valid_results


async def _update_market_price_async():
    yfinance_service = YFinanceService()
    symbols = yfinance_service.WATCHLIST

    gainers = []
    losers = []

    quotes_map = await _fetch_all_quotes(symbols, yfinance_service)

    for symbol in symbols:
        if symbol not in quotes_map:
            continue

        try:
            quote = quotes_map[symbol]
            new_price = quote.current_price

            new_data = {
                "symbol": symbol,
                "price": new_price,
                "timestamp": datetime.now(UTC).isoformat(),
                "previous_close": quote.previous_close,
                "currency": quote.currency
            }

            await save_market_data(symbol, new_data)

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

            logger.info("Updated REAL %s: %s", symbol, new_data)

        except Exception:
            logger.exception("Error processing real data for %s", symbol)

    logger.info("=" * 30)
    logger.info("MARKET ANALYSIS (GAINERS & LOSERS)")
    logger.info("=" * 30)
    if gainers:
        logger.info("📈 GAINERS:")
        for g in gainers:
            logger.info("  - %s (↑ $%s / +%s%%)", g["symbol"], g["price"], g["percent_change"])
    else:
        logger.info("📈 GAINERS: None")

    if losers:
        logger.info("📉 LOSERS:")
        for item in losers:
            logger.info("  - %s (↓ $%s / %s%%)", item["symbol"], item["price"], item["percent_change"])
    else:
        logger.info("📉 LOSERS: None")
    logger.info("=" * 30)

    await save_market_analysis(gainers, losers)
    return "Market Updated"


@celery_app.task
def update_market_price():
    return asyncio.run(_update_market_price_async())
