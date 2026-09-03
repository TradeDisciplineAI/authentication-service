# ------------------ Authentication Service Entry Point Feature -----------------------
"""
Application entry point for the Authentication Microservice.
Initializes FastAPI, configures CORS and Trusted Host middleware, sets up rate limiters,
attaches custom exception handlers, and mounts authentication and subscription routers.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from prometheus_fastapi_instrumentator import Instrumentator

from .core.config import get_settings
from .core.exceptions import AppException
from .core.limiter import limiter
from .routers.auth import router as auth_router
from .routers.subscriptions import router as subscriptions_router

settings = get_settings()

# Initialize logging configuration
logging.basicConfig(
    level=settings.log_level,
    format=settings.log_format,
)

# ------------------ FastAPI App Initialization -----------------------
"""
FastAPI application instance configured with app settings, environment-aware documentation URLs,
CORS security middleware, and trusted host protections.
"""
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered trading discipline and psychology assistant.",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

# Instrument FastAPI HTTP metrics and expose GET /metrics endpoint
Instrumentator().instrument(app).expose(app)

# Attach rate limiter state and exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "Origin",
        "X-Requested-With",
        "X-Payment-Token",  # Required for /auth/subscribe CORS preflight — browser sends this custom header when upgrading subscription
    ],
)


# ------------------ Custom Application Exception Handler -----------------------
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Catches custom AppException instances across all routes and returns a standardized
    JSON response with HTTP status code and error details.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# ------------------ Root Endpoint -----------------------
@app.get("/")
async def root() -> dict[str, str]:
    """
    Root endpoint returning service status message verifying server execution.
    """
    return {"message": "AI Trading Discipline Copilot is running."}


# ------------------ Health Check Endpoint -----------------------
@app.get("/health")
async def health() -> dict[str, str]:
    """
    Health check endpoint returning service status, application version, and active environment mode.
    """
    return {"status": "ok", "version": settings.app_version, "env": settings.app_env}


# ------------------ Celery Worker Health Check Endpoint -----------------------
@app.get("/health/celery-ping")
async def celery_ping() -> dict[str, str]:
    """
    Health check endpoint for background Celery worker queue connectivity.
    """
    from ai_trading_discipline_copilot.tasks.system_tasks import ping_auth_worker

    task = ping_auth_worker.delay()
    return {"status": "enqueued", "task_id": task.id, "queue": "auth_queue"}


# ------------------ Mount API Routers -----------------------
app.include_router(auth_router)
app.include_router(subscriptions_router)
