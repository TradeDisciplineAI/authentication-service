from celery import Celery
from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_trading_discipline_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.update(
    imports=["ai_trading_discipline_copilot.tasks.market_tasks"]
)

from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "update-market-price-every-minute": {
        "task": "ai_trading_discipline_copilot.tasks.market_tasks.update_market_price",
        "schedule": 60.0, # Runs every 60 seconds
    },
}