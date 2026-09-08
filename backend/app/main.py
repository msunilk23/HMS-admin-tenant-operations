from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.secret_store import initialize_secret_store
from app.core.uploads import get_uploads_dir
from app.db.engine import init_db
from app.middleware.tenant import TenantMiddleware
from app.middleware.audit import AuditLogMiddleware
from app.websocket.manager import ws_manager
from app.websocket.redis_bridge import start_redis_subscriber, stop_redis_subscriber
from app.api.v1.router import api_router
from app.services.routing_expiry_worker import routing_expiry_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    initialize_secret_store()
    logger.info("=" * 80)
    logger.info("🚀 HOSPITAL API STARTING UP")
    logger.info("=" * 80)
    logger.info("Environment: %s", settings.ENVIRONMENT)
    logger.info("Debug: %s", settings.DEBUG)
    logger.info("Integration secret store: %s", "configured" if settings.INTEGRATION_MASTER_KEY_FILE or settings.INTEGRATION_MASTER_KEY else "not configured")
    logger.info("=" * 80)
    
    await init_db()
    await start_redis_subscriber(ws_manager)
    expiry_stop = __import__("asyncio").Event()
    expiry_task = __import__("asyncio").create_task(routing_expiry_loop(expiry_stop))
    yield
    expiry_stop.set()
    await expiry_task
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
app.mount("/uploads", StaticFiles(directory=str(get_uploads_dir())), name="uploads")


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
