from pydantic import BaseModel


class GainerStock(BaseModel):
    symbol: str
    current_price: float
    change: float
    percent_change: float