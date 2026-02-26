"""
Spark Admin Auth — JWT verification for the admin portal.

Admin users authenticate via Supabase Auth (email/password).
The portal sends the Supabase access token as a Bearer token.
We verify it using Supabase's JWKS endpoint (RS256).

The public key is fetched from:
  {SUPABASE_URL}/auth/v1/.well-known/jwks.json

Cached in-process with a 1-hour TTL to avoid hitting the endpoint on every request.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request

from app.config import settings
from app.models.spark import SparkClient
from app.services.supabase import get_first_or_none, get_supabase_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS client — cached singleton with 1-hour TTL
# ---------------------------------------------------------------------------

_jwks_client: PyJWKClient | None = None
_jwks_client_created_at: float = 0
_JWKS_TTL_SECONDS = 3600  # Refresh JWKS client every hour


def _get_jwks_client() -> PyJWKClient:
    """Get or create the JWKS client (cached with TTL)."""
    global _jwks_client, _jwks_client_created_at
    now = time.monotonic()

    if _jwks_client is None or (now - _jwks_client_created_at) > _JWKS_TTL_SECONDS:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        _jwks_client_created_at = now
        logger.info("JWKS client initialized: %s", jwks_url)

    return _jwks_client


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_admin_jwt(request: Request) -> SparkClient:
    """FastAPI dependency: verify Supabase JWT and return the client.

    Extracts Bearer token from Authorization header, fetches the signing
    key from Supabase's JWKS endpoint, verifies the JWT (RS256), then
    looks up spark_clients where user_id matches the JWT subject.

    Raises 401 on missing/invalid token, 403 on no matching client.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization token")

    token = auth_header[7:]  # Strip "Bearer "

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("Admin auth: invalid token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error("Admin auth: JWKS verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Token verification failed")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no subject")

    try:
        sb = await get_supabase_client()
        row = await get_first_or_none(
            sb.table("spark_clients").select("*").eq("user_id", user_id)
        )
    except Exception:
        logger.exception("Admin auth: database error during client lookup")
        raise HTTPException(status_code=500, detail="Internal error")

    if row is None:
        raise HTTPException(
            status_code=403, detail="No Spark client linked to this account"
        )

    client = SparkClient(**row)

    if not client.active:
        raise HTTPException(status_code=403, detail="Client deactivated")

    return client
