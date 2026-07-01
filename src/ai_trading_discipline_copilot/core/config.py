from functools import lru_cache

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
    app_env: str = "development"
    debug: bool = True

    # Security
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database
    database_url: str

    # AI Provider
    ai_provider: str = "openai"
    openai_api_key: str = ""
    ai_model: str = "gpt-4o"

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
