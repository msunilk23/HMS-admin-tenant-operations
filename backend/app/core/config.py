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

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Razorpay (optional — for online payments)
    RAZORPAY_KEY_ID: str = ""               # rzp_test_... or rzp_live_...
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""       # set in Razorpay dashboard webhook settings

    # Cloudinary (optional — for lab report file storage)
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # Notifications (optional)
    # Twilio (optional — used for SMS / WhatsApp notifications)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_SMS_FROM_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = ""          # e.g. whatsapp:+14155238886

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
