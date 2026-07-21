from celery import Celery

from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "auth_service",
    broker=settings.redis_url,
)

celery_app.conf.update(
    # Queue & Worker Configuration
    task_default_queue="auth_queue",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result Backend Optimization (Fire & Forget)
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Time limits (soft: 60s, hard: 120s)
    task_soft_time_limit=60,
    task_time_limit=120,
    # Task Imports
    imports=[
        "ai_trading_discipline_copilot.tasks.system_tasks",
    ],
)
