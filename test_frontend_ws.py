import asyncio
import websockets

async def test():
    try:
        async with websockets.connect('ws://localhost:8000/dashboard/ws/market') as ws:
            print("Connected! Waiting for message...")
            msg = await ws.recv()
            print("Received length:", len(msg))
    except Exception as e:
        print("Failed to connect:", e)

if __name__ == "__main__":
    asyncio.run(test())
