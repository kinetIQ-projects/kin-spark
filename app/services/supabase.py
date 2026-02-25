"""
Supabase Service — Spark's own Supabase instance.
"""

import logging
from typing import Any

from supabase import acreate_client, AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncClient | None = None


async def get_supabase_client() -> AsyncClient:
    """Get or create the async Supabase client."""
    global _client
    if _client is None:
        try:
            _client = await acreate_client(
                settings.supabase_url, settings.supabase_service_key
            )
        except Exception as e:
            logger.error("Failed to create Supabase client: %s", e)
            raise
    return _client


async def close_supabase() -> None:
    """Close the Supabase client (call on shutdown)."""
    global _client
    if _client is not None:
        _client = None


async def get_first_or_none(query: Any) -> dict[str, Any] | None:
    """Execute query and return first row or None."""
    result = await query.limit(1).execute()
    data: list[dict[str, Any]] = result.data or []
    return data[0] if data else None
