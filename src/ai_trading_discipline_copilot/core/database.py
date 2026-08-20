# ------------------ Database Configuration & Engine Feature -----------------------
"""
Async PostgreSQL database engine setup, connection pooling, session factory,
and declarative base class initialization for SQLAlchemy ORM models.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()

# ------------------ Async Database Engine Feature -----------------------
"""
Async SQLAlchemy Engine configured with connection pooling parameters, statement cache disabling
for compatibility with transaction poolers (PgBouncer/Supabase), and pool pre-ping connection liveness validation.
"""
engine = create_async_engine(
    settings.database_url.get_secret_value(),
    echo=settings.debug,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    connect_args={
        "statement_cache_size": 0,
    },
)

# ------------------ Async Session Factory Feature -----------------------
"""
Global async session factory bound to the async engine.
expire_on_commit=False ensures ORM instances remain accessible post-commit without trigger re-queries.
"""
AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ------------------ SQLAlchemy Declarative Base Class -----------------------
class Base(DeclarativeBase):
    """
    Abstract declarative base class inherited by all database ORM models in the service.
    """
    pass
