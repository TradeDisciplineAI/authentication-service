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

    # Database
    database_url: PostgresDsn

    # AI Provider
    ai_provider: str = "openai"
    openai_api_key: SecretStr = SecretStr("")
    ai_model: str = "gpt-4o"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
