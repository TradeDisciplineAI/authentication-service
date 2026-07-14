from typing import Optional
from pydantic import BaseModel


class StockQuote(BaseModel):
    symbol: str
    current_price: float
    change: Optional[float] = None
    percent_change: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open_price: Optional[float] = None
    previous_close: Optional[float] = None
    currency: Optional[str] = "USD"