"""
Spark Auth — API key verification for Spark endpoints.

Spark API keys are publishable keys (visible in page source by design).
Security is enforced by: rate limiting, session IP binding, and
complete isolation from Kin's /api/* auth path.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import Header, HTTPException, Request

from app.models.spark import SparkClient
from app.services.supabase import get_supabase_client, get_first_or_none

logger = logging.getLogger(__name__)


def _hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key for storage/lookup."""
    return hashlib.sha256(key.encode()).hexdigest()


def _extract_api_key(request: Request) -> str:
    """Extract API key from Authorization header or X-Spark-Key header."""
    # Check Authorization: Bearer first (standard pattern)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Fall back to X-Spark-Key header
    spark_key = request.headers.get("X-Spark-Key")
    if spark_key:
        return spark_key

    raise HTTPException(status_code=401, detail="Missing API key")


async def verify_spark_api_key(request: Request) -> SparkClient:
    """FastAPI dependency: verify Spark API key and return client.

    Accepts API key via Authorization: Bearer or X-Spark-Key header.
    Raises 401 on invalid/missing key, 403 on inactive client.
    """
    key_hash = _hash_api_key(_extract_api_key(request))

    try:
        sb = await get_supabase_client()
        row = await get_first_or_none(
            sb.table("spark_clients").select("*").eq("api_key_hash", key_hash)
        )
    except Exception:
        logger.exception("Spark auth: database error during key lookup")
        raise HTTPException(status_code=500, detail="Internal error")

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    client = SparkClient(**row)

    if not client.active:
        raise HTTPException(status_code=403, detail="Client deactivated")

    return client
