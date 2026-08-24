from contextlib import asynccontextmanager
from pathlib import Path
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.db.engine import init_db
from app.middleware.tenant import TenantMiddleware
from app.middleware.audit import AuditLogMiddleware
from app.websocket.manager import ws_manager
from app.websocket.redis_bridge import start_redis_subscriber, stop_redis_subscriber
from app.api.v1.router import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("=" * 80)
    logger.info("🚀 HOSPITAL API STARTING UP")
    logger.info("=" * 80)
    logger.info("Environment: %s", settings.ENVIRONMENT)
    logger.info("Debug: %s", settings.DEBUG)
    logger.info("RAZORPAY_KEY_ID: %s", settings.RAZORPAY_KEY_ID[:20] + "..." if settings.RAZORPAY_KEY_ID else "❌ NOT SET")
    logger.info("RAZORPAY_WEBHOOK_SECRET: %s", "✓ SET" if settings.RAZORPAY_WEBHOOK_SECRET else "❌ NOT SET")
    logger.info("=" * 80)
    
    await init_db()
    await start_redis_subscriber(ws_manager)
    yield
    await stop_redis_subscriber()


app = FastAPI(
    title="Smart Hospital — OPD API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tenant resolution middleware (must come after CORS)
app.add_middleware(TenantMiddleware)

# Audit log middleware — writes to public.audit_log for every mutating request
app.add_middleware(AuditLogMiddleware)

# API routes
app.include_router(api_router, prefix="/api/v1")

# WebSocket endpoint
from app.websocket.router import ws_router  # noqa: E402
app.include_router(ws_router)

# Serve uploaded lab reports (and any future uploads)
_uploads_dir = Path(os.getenv("UPLOADS_DIR", "/app/uploads"))
if not _uploads_dir.parent.exists() or not os.access(_uploads_dir.parent, os.W_OK):
    _uploads_dir = Path(__file__).resolve().parents[2] / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "hospital-opd-api"}


@app.get("/api/v1/billing/config", tags=["billing"])
async def get_billing_config():
    """Returns billing configuration including Razorpay key (needed by frontend)."""
    return {
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "razorpay_configured": bool(settings.RAZORPAY_KEY_ID),
    }
