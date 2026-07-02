"""Application entry point."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ai_trading_discipline_copilot import __version__

from .core.config import get_settings
from .core.exceptions import AppException
from .routers.auth import router as auth_router

settings = get_settings()

app = FastAPI(
    title="AI Trading Discipline Copilot",
    version=__version__,
    description="AI-powered trading discipline and psychology assistant.",
    # Disable interactive docs outside of development to avoid exposing
    # the full API schema to unauthenticated users in staging/production.
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
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
    return {"status": "ok", "version": __version__, "env": settings.app_env}


app.include_router(auth_router)
