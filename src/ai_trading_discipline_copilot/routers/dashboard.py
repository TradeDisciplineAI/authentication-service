import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ai_trading_discipline_copilot.core.redis import get_market_analysis
from ai_trading_discipline_copilot.core.websocket_manager import manager
from ai_trading_discipline_copilot.schemas.gainers import GainerStock
from ai_trading_discipline_copilot.schemas.stock import StockQuote
from ai_trading_discipline_copilot.services.yfinance_service import YFinanceService

logger = logging.getLogger(__name__)

service = YFinanceService()
router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
)


@router.get("/quote/{symbol}", response_model=StockQuote)
async def get_stock_quote(symbol: str):
    return await service.get_stock_quote(symbol)


@router.get(
    "/gainers",
    response_model=list[GainerStock],
)
async def get_gainers():

    return await service.get_gainers()

@router.get("/analysis")
async def get_market_analysis_endpoint():
    """
    Returns the latest Gainers and Losers calculated by the Celery background worker.
    """
    return await get_market_analysis()

@router.websocket("/ws/market")
async def websocket_market_endpoint(websocket: WebSocket):
    """
    Real-time WebSocket endpoint that streams Gainers and Losers directly to the React frontend.
    """
    await manager.connect(websocket)
    try:
        # Instantly send the current state upon connection
        await websocket.send_json(await get_market_analysis())

        # Keep connection open infinitely
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
