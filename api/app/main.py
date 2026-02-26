"""
Kin Spark — AI Rep API

Standalone FastAPI application for the Spark chat widget product.
Includes admin portal endpoints at /spark/admin/*.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import settings
from app.routers import spark
from app.routers import admin as admin_router

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
    description="Kin Spark — AI Rep chat widget API + admin portal",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# =============================================================================
# MIDDLEWARE — Path-based CORS
# =============================================================================
# Admin endpoints: restricted origin (app.trykin.ai) with credentials
# Widget endpoints: wildcard origin, no credentials


class PathBasedCORSMiddleware(BaseHTTPMiddleware):
    """Apply different CORS policies based on request path.

    /spark/admin/* → restricted origin (admin portal) with credentials
    Everything else → wildcard origin (widget embeds anywhere)
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.admin_origins = [
            o.strip() for o in settings.admin_cors_origins.split(",") if o.strip()
        ]

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def, override]
        origin = request.headers.get("origin", "")
        path = request.url.path

        # Handle preflight
        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        if path.startswith("/spark/admin"):
            # Admin: restricted origins with credentials
            if origin in self.admin_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = (
                    "GET, POST, PATCH, DELETE, OPTIONS"
                )
                response.headers["Access-Control-Allow-Headers"] = (
                    "Authorization, Content-Type"
                )
                response.headers["Access-Control-Max-Age"] = "86400"
        else:
            # Widget: wildcard
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = (
                "X-Spark-Key, Content-Type"
            )

        return response


# Replace the default CORSMiddleware with our path-based version
app.add_middleware(PathBasedCORSMiddleware)


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
app.include_router(admin_router.router, prefix="/spark/admin", tags=["Admin"])

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
