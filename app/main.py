"""
Kin Spark — AI Rep API

Standalone FastAPI application for the Spark chat widget product.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import spark

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Application lifespan handler."""
    logger.info("Starting %s in %s mode", settings.app_name, settings.environment)
    logger.info("Primary model: %s", settings.spark_primary_model)
    yield
    logger.info("Shutting down %s", settings.app_name)
    from app.services.supabase import close_supabase

    await close_supabase()


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title=settings.app_name,
    description="Kin Spark — AI Rep chat widget API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# =============================================================================
# MIDDLEWARE
# =============================================================================

# Wildcard CORS — Spark uses publishable API keys, widget embeds on any domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["X-Spark-Key", "Content-Type"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Log all requests for debugging."""
    logger.debug("%s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


# =============================================================================
# EXCEPTION HANDLERS
# =============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# =============================================================================
# ROUTERS
# =============================================================================

app.include_router(spark.router, prefix="/spark", tags=["Spark"])

# Serve widget static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# =============================================================================
# ROOT / HEALTH
# =============================================================================


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"service": "Kin Spark", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "healthy", "service": settings.app_name}
