"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "AI Trading Discipline Copilot"
    app_version: str = "0.1.0"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # Security
    secret_key: SecretStr
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = 12
    cookie_name: str = "refresh_token"

    # Defaults True so cookies always require HTTPS outside local dev.
    # Override with COOKIE_SECURE=false in .env for local development only.
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    cookie_path: str = "/auth"

    # Account lockout — brute-force protection
    max_login_attempts: int = 10
    lockout_duration_minutes: int = 15

    # Database
    database_url: SecretStr
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800

    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Hosts
    # Restrict to known safe hosts by default — wildcard defeats TrustedHostMiddleware.
    # In production set ALLOWED_HOSTS=["yourdomain.com"] via environment variable.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]

    # AI Provider
    ai_provider: str = "openai"
    openai_api_key: SecretStr = SecretStr("")
    ai_model: str = "gpt-4o"

    # Google OAuth2
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Email
    resend_api_key: SecretStr
    email_from: str
    frontend_url: str

    # CORS
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: SecretStr) -> SecretStr:
        url_str = v.get_secret_value()

        if not url_str.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must start with 'postgresql+asyncpg://'")

        from pydantic import TypeAdapter

        try:
            TypeAdapter(PostgresDsn).validate_python(url_str)
        except Exception as e:
            raise ValueError(f"Invalid database URL format: {e}") from None

        return v

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(
        cls,
        v: list[str],
    ) -> list[str]:
        if "*" in v:
            raise ValueError(
                "Wildcard '*' is not allowed in allowed_origins "
                "when credentials are enabled"
            )

        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
