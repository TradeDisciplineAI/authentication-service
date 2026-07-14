"""Application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .core.config import get_settings
from .core.exceptions import AppException
from .core.limiter import limiter
from .routers.auth import router as auth_router
from .routers.dashboard import router as dashboard_router
from contextlib import asynccontextmanager
import asyncio
from ai_trading_discipline_copilot.services.yfinance_ws_service import YFinanceWebSocketService

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create the background task to listen to the simulated WebSocket
    ws_service = YFinanceWebSocketService()
    # Start the websocket listener in the background
    task = asyncio.create_task(ws_service.connect_and_listen())
    yield
    # Cancel the task on shutdown
    task.cancel()
settings = get_settings()


# Initialize logging configuration
logging.basicConfig(
    level=settings.log_level,
    format=settings.log_format,
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered trading discipline and psychology assistant.",
    # Disable interactive docs outside of development to avoid exposing
    # the full API schema to unauthenticated users in staging/production.
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    lifespan=lifespan,
)

# Attach limiter state and exception handler
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
    ],
)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "AI Trading Discipline Copilot is running."}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version, "env": settings.app_env}


app.include_router(auth_router)
app.include_router(dashboard_router)
