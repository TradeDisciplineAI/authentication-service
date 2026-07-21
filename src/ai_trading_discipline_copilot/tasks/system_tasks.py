import logging

from ai_trading_discipline_copilot.core.celery import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="auth_service.tasks.ping_auth_worker")
def ping_auth_worker() -> dict[str, str]:
    """Infrastructure verification ping task for authentication-service worker."""
    logger.info("Executing auth worker infrastructure ping task")
    return {"status": "pong", "service": "authentication-service"}
