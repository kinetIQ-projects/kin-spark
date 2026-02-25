"""
Spark Session Manager — Create, validate, and manage conversation sessions.

Sessions are IP-bound and expire after 30 minutes of inactivity.
Session tokens: secrets.token_urlsafe(32) — 256 bits of entropy.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.config import settings
from app.services.supabase import get_supabase_client, get_first_or_none

logger = logging.getLogger(__name__)


async def create_session(
    client_id: UUID,
    ip_address: str,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create a new Spark conversation session.

    Returns the full conversation row.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.spark_session_timeout_minutes
    )

    sb = await get_supabase_client()
    result = (
        await sb.table("spark_conversations")
        .insert(
            {
                "client_id": str(client_id),
                "session_token": token,
                "ip_address": ip_address,
                "visitor_fingerprint": fingerprint,
                "turn_count": 0,
                "state": "active",
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
    )

    row = result.data[0]
    logger.info("Spark session created: %s (client=%s)", row["id"], client_id)
    return row


async def get_session(
    session_token: str,
    ip_address: str,
) -> dict[str, Any] | None:
    """Get a session by token, validating IP and expiry.

    Returns None if session doesn't exist, IP doesn't match,
    or session has expired.
    """
    sb = await get_supabase_client()
    row = await get_first_or_none(
        sb.table("spark_conversations")
        .select("*")
        .eq("session_token", session_token)
        .eq("state", "active")
    )

    if row is None:
        return None

    # IP binding check
    if row["ip_address"] != ip_address:
        logger.warning(
            "Spark session IP mismatch: session=%s expected=%s got=%s",
            row["id"],
            row["ip_address"],
            ip_address,
        )
        return None

    # Expiry check
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        logger.info("Spark session expired: %s", row["id"])
        # Mark as expired
        await sb.table("spark_conversations").update({"state": "expired"}).eq(
            "id", row["id"]
        ).execute()
        return None

    return row


async def increment_turn(conversation_id: UUID) -> int:
    """Increment turn count and refresh expiry. Returns new turn count."""
    sb = await get_supabase_client()
    new_expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.spark_session_timeout_minutes
    )

    result = await (
        sb.table("spark_conversations")
        .update(
            {
                "turn_count": "turn_count",  # Placeholder — we read-modify-write below
                "expires_at": new_expires.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", str(conversation_id))
        .execute()
    )

    # Supabase doesn't support increment in update, so fetch + update
    row = await get_first_or_none(
        sb.table("spark_conversations")
        .select("turn_count")
        .eq("id", str(conversation_id))
    )
    if row is None:
        return 0

    new_count = row["turn_count"] + 1
    await (
        sb.table("spark_conversations")
        .update(
            {
                "turn_count": new_count,
                "expires_at": new_expires.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", str(conversation_id))
        .execute()
    )

    return new_count


async def get_history(
    conversation_id: UUID,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Get message history for a conversation (oldest first).

    If limit is provided, returns only the last `limit` turns
    (a turn = one user + one assistant message = 2 rows).
    """
    effective_limit = limit or settings.spark_context_turns
    # Each turn is 2 messages (user + assistant), fetch 2x
    row_limit = effective_limit * 2

    sb = await get_supabase_client()
    result = await (
        sb.table("spark_messages")
        .select("role, content, created_at")
        .eq("conversation_id", str(conversation_id))
        .order("created_at", desc=True)
        .limit(row_limit)
        .execute()
    )

    # Reverse to get chronological order
    messages = list(reversed(result.data or []))
    return messages


async def store_message(
    conversation_id: UUID,
    role: str,
    content: str,
) -> dict[str, Any]:
    """Store a message in the conversation."""
    sb = await get_supabase_client()
    result = (
        await sb.table("spark_messages")
        .insert(
            {
                "conversation_id": str(conversation_id),
                "role": role,
                "content": content,
            }
        )
        .execute()
    )

    return result.data[0]


async def end_session(conversation_id: UUID, state: str = "completed") -> None:
    """Mark a conversation as completed or abandoned."""
    sb = await get_supabase_client()
    await (
        sb.table("spark_conversations")
        .update(
            {
                "state": state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", str(conversation_id))
        .execute()
    )
    logger.info("Spark session ended: %s (%s)", conversation_id, state)
