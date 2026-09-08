from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Smart Hospital OPD"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:port/db

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # OPD queue SLA policy, in minutes.
    QUEUE_SLA_NURSE_MINUTES: int = 15
    QUEUE_SLA_DOCTOR_MINUTES: int = 20
    SCHEDULE_MAX_CAPACITY: int = 100
    PHARMACY_RESERVATION_TTL_MINUTES: int = 15

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Tenant-scoped provider integrations are stored encrypted and resolved by
    # tenant context rather than a single global credential set.
    INTEGRATION_MASTER_KEY_FILE: str | None = None
    INTEGRATION_MASTER_KEY: str | None = None
    INTEGRATION_MASTER_KEY_TEST_ONLY: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
