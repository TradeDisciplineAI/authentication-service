import asyncio
import websockets
import json
from ai_trading_discipline_copilot.core.config import get_settings

async def test():
    settings = get_settings()
    url = f"wss://ws.finnhub.io?token={settings.finnhub_api_key.get_secret_value()}"
    async with websockets.connect(url, open_timeout=30) as ws:
        await ws.send(json.dumps({"type": "subscribe", "symbol": "AAPL"}))
        await ws.send(json.dumps({"type": "subscribe", "symbol": "BINANCE:BTCUSDT"}))
        print("Subscribed. Listening...")

        # Read for 5 seconds
        async def listen():
            async for msg in ws:
                print("Received:", msg)

        t = asyncio.create_task(listen())
        await asyncio.sleep(5)
        t.cancel()

if __name__ == "__main__":
    asyncio.run(test())
