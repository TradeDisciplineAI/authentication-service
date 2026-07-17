import asyncio
import yfinance as yf

from ai_trading_discipline_copilot.schemas.gainers import GainerStock
from ai_trading_discipline_copilot.schemas.stock import StockQuote


class YFinanceService:
    WATCHLIST = [
        # Indian Stocks (NSE)
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS",
        "AXISBANK.NS", "KOTAKBANK.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS",
        "HINDUNILVR.NS", "M&M.NS", "TATASTEEL.NS", "ASIANPAINT.NS", "WIPRO.NS",

        # US Stocks
        "AAPL", "MSFT", "NVDA", "TSLA", "META",
        "GOOGL", "AMZN", "AMD", "NFLX", "COIN"
    ]

    def __init__(self):
        pass

    def _fetch_quote_sync(self, symbol: str) -> StockQuote:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info

        current_price = info.last_price
        previous_close = info.previous_close

        change = current_price - previous_close if previous_close else 0.0
        percent_change = (change / previous_close) * 100 if previous_close else 0.0

        return StockQuote(
            symbol=symbol,
            current_price=current_price,
            change=change,
            percent_change=percent_change,
            high=getattr(info, "day_high", None),
            low=getattr(info, "day_low", None),
            open_price=getattr(info, "open", None),
            previous_close=previous_close,
            currency=getattr(info, "currency", "USD"),
        )

    async def get_stock_quote(self, symbol: str) -> StockQuote | None:
        try:
            return await asyncio.to_thread(self._fetch_quote_sync, symbol)
        except Exception as e:
            print(f"Failed to fetch quote data for {symbol}: {e}")
            return None

    def _fetch_gainers_sync(self) -> list[GainerStock]:
        gainers = []
        for symbol in self.WATCHLIST:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info
                current_price = info.last_price
                previous_close = info.previous_close
                change = current_price - previous_close if previous_close else 0.0
                percent_change = (change / previous_close) * 100 if previous_close else 0.0

                gainers.append(
                    GainerStock(
                        symbol=symbol,
                        current_price=current_price,
                        change=change,
                        percent_change=percent_change,
                    )
                )
            except Exception as e:
                print(f"Failed to fetch gainer data for {symbol}: {e}")

        gainers.sort(key=lambda stock: stock.percent_change, reverse=True)
        return gainers[:15]

    async def get_gainers(self) -> list[GainerStock]:
        return await asyncio.to_thread(self._fetch_gainers_sync)
