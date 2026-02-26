"""
Spark Admin Router — Authenticated endpoints for the admin portal.

Endpoints:
  GET  /spark/admin/me                    — Client profile
  GET  /spark/admin/conversations         — List conversations (filterable)
  GET  /spark/admin/conversations/{id}    — Conversation detail + transcript
  GET  /spark/admin/leads                 — List leads (filterable)
  PATCH /spark/admin/leads/{id}           — Update lead status/notes
  GET  /spark/admin/leads/export          — CSV export
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.models.admin import (
    AdminClientProfile,
    AdminConversationDetail,
    AdminConversationListItem,
    AdminLeadListItem,
    AdminLeadSummary,
    AdminLeadUpdate,
    AdminTranscriptMessage,
    PaginatedResponse,
)
from app.models.spark import SparkClient
from app.services.spark.admin_auth import verify_admin_jwt
from app.services.spark.rate_limiter import get_rate_limiter
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# RATE LIMITING DEPENDENCY
# =============================================================================


async def _admin_rate_limit(request: Request) -> None:
    """Rate limit admin requests: 60 req/min per user."""
    from app.config import settings

    auth_header = request.headers.get("Authorization", "")
    # Use a stable key from the token — we extract sub in admin_auth
    # but here we just need a key for rate limiting. Use the token hash.
    import hashlib

    token_hash = hashlib.sha256(auth_header.encode()).hexdigest()[:16]

    limiter = get_rate_limiter()
    if not limiter.check(f"admin:{token_hash}", "admin", settings.admin_rate_limit_rpm):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


# =============================================================================
# PROFILE
# =============================================================================


@router.get("/me")
async def get_profile(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminClientProfile:
    """Get the authenticated client's profile."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_clients")
            .select("*")
            .eq("id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch client profile")
        raise HTTPException(status_code=500, detail="Failed to fetch profile")

    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    row = result.data[0]
    return AdminClientProfile(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        active=row.get("active", True),
        max_turns=row.get("max_turns", 20),
        rate_limit_rpm=row.get("rate_limit_rpm", 30),
        accent_color=row.get("accent_color"),
        widget_position=row.get("widget_position"),
        widget_title=row.get("widget_title"),
        widget_avatar_url=row.get("widget_avatar_url"),
        greeting_message=row.get("greeting_message"),
        notification_email=row.get("notification_email"),
        notifications_enabled=row.get("notifications_enabled", False),
        daily_conversation_cap=row.get("daily_conversation_cap"),
        sessions_per_visitor_per_day=row.get("sessions_per_visitor_per_day"),
        created_at=row.get("created_at"),
    )


# =============================================================================
# CONVERSATIONS
# =============================================================================


@router.get("/conversations")
async def list_conversations(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    outcome: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> PaginatedResponse:
    """List conversations with optional filters."""
    sb = await get_supabase_client()

    try:
        # Build query
        query = (
            sb.table("spark_conversations")
            .select("*", count="exact")
            .eq("client_id", str(client.id))
        )

        if outcome:
            query = query.eq("outcome", outcome)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = await query.execute()
    except Exception:
        logger.exception("Admin: failed to list conversations")
        raise HTTPException(status_code=500, detail="Failed to fetch conversations")

    conversations = result.data or []
    total = result.count if result.count is not None else len(conversations)

    # Fetch first message previews in bulk
    conv_ids = [c["id"] for c in conversations]
    previews: dict[str, str] = {}
    if conv_ids:
        try:
            msg_result = await (
                sb.table("spark_messages")
                .select("conversation_id, content")
                .in_("conversation_id", conv_ids)
                .eq("role", "user")
                .order("created_at", desc=False)
                .execute()
            )
            # Take only first user message per conversation
            for msg in msg_result.data or []:
                cid = msg["conversation_id"]
                if cid not in previews:
                    content = msg["content"] or ""
                    previews[cid] = content[:100] + (
                        "..." if len(content) > 100 else ""
                    )
        except Exception:
            logger.warning("Admin: failed to fetch message previews")

    items = []
    for conv in conversations:
        created = conv.get("created_at")
        ended = conv.get("ended_at")
        duration = None
        if created and ended:
            try:
                dt_created = datetime.fromisoformat(created)
                dt_ended = datetime.fromisoformat(ended)
                duration = int((dt_ended - dt_created).total_seconds())
            except (ValueError, TypeError):
                pass

        items.append(
            AdminConversationListItem(
                id=conv["id"],
                first_message_preview=previews.get(conv["id"]),
                turn_count=conv.get("turn_count", 0),
                state=conv.get("state", "active"),
                outcome=conv.get("outcome"),
                sentiment=conv.get("sentiment"),
                created_at=conv["created_at"],
                ended_at=conv.get("ended_at"),
                duration_seconds=duration,
            )
        )

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: UUID,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminConversationDetail:
    """Get full conversation detail with transcript and lead info."""
    sb = await get_supabase_client()

    try:
        # Fetch conversation
        conv_result = await (
            sb.table("spark_conversations")
            .select("*")
            .eq("id", str(conversation_id))
            .eq("client_id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch conversation detail")
        raise HTTPException(status_code=500, detail="Failed to fetch conversation")

    if not conv_result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = conv_result.data[0]

    # Fetch messages
    try:
        msg_result = await (
            sb.table("spark_messages")
            .select("*")
            .eq("conversation_id", str(conversation_id))
            .order("created_at", desc=False)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch conversation messages")
        raise HTTPException(status_code=500, detail="Failed to fetch messages")

    messages = [AdminTranscriptMessage(**msg) for msg in (msg_result.data or [])]

    # Fetch lead if captured
    lead = None
    try:
        lead_result = await (
            sb.table("spark_leads")
            .select("*")
            .eq("conversation_id", str(conversation_id))
            .limit(1)
            .execute()
        )
        if lead_result.data:
            ld = lead_result.data[0]
            lead = AdminLeadSummary(
                id=ld["id"],
                name=ld.get("name"),
                email=ld.get("email"),
                phone=ld.get("phone"),
                status=ld.get("status", "new"),
                created_at=ld["created_at"],
            )
    except Exception:
        logger.warning("Admin: failed to fetch lead for conversation")

    # Compute duration
    created = conv.get("created_at")
    ended = conv.get("ended_at")
    duration = None
    if created and ended:
        try:
            dt_created = datetime.fromisoformat(created)
            dt_ended = datetime.fromisoformat(ended)
            duration = int((dt_ended - dt_created).total_seconds())
        except (ValueError, TypeError):
            pass

    return AdminConversationDetail(
        id=conv["id"],
        client_id=conv["client_id"],
        turn_count=conv.get("turn_count", 0),
        state=conv.get("state", "active"),
        outcome=conv.get("outcome"),
        sentiment=conv.get("sentiment"),
        sentiment_score=conv.get("sentiment_score"),
        summary=conv.get("summary"),
        created_at=conv["created_at"],
        ended_at=conv.get("ended_at"),
        duration_seconds=duration,
        messages=messages,
        lead=lead,
    )


# =============================================================================
# LEADS
# =============================================================================


@router.get("/leads/export")
async def export_leads_csv(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> StreamingResponse:
    """Export leads as CSV with injection protection."""
    sb = await get_supabase_client()

    try:
        query = sb.table("spark_leads").select("*").eq("client_id", str(client.id))
        if status:
            query = query.eq("status", status)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        query = query.order("created_at", desc=True)
        result = await query.execute()
    except Exception:
        logger.exception("Admin: failed to export leads")
        raise HTTPException(status_code=500, detail="Failed to export leads")

    leads = result.data or []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["Name", "Email", "Phone", "Status", "Notes", "Captured At", "Conversation ID"]
    )

    for lead in leads:
        writer.writerow(
            [
                _sanitize_csv(lead.get("name") or ""),
                _sanitize_csv(lead.get("email") or ""),
                _sanitize_csv(lead.get("phone") or ""),
                _sanitize_csv(lead.get("status") or "new"),
                _sanitize_csv(lead.get("admin_notes") or lead.get("notes") or ""),
                lead.get("created_at", ""),
                lead.get("conversation_id", ""),
            ]
        )

    today = datetime.utcnow().strftime("%Y-%m-%d")
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="spark-leads-{today}.csv"'
        },
    )


@router.get("/leads")
async def list_leads(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> PaginatedResponse:
    """List leads with optional filters."""
    sb = await get_supabase_client()

    try:
        query = (
            sb.table("spark_leads")
            .select("*", count="exact")
            .eq("client_id", str(client.id))
        )

        if status:
            query = query.eq("status", status)
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        result = await query.execute()
    except Exception:
        logger.exception("Admin: failed to list leads")
        raise HTTPException(status_code=500, detail="Failed to fetch leads")

    leads = result.data or []
    total = result.count if result.count is not None else len(leads)

    items = [AdminLeadListItem(**lead) for lead in leads]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: UUID,
    body: AdminLeadUpdate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminLeadListItem:
    """Update a lead's status and/or admin notes."""
    sb = await get_supabase_client()

    # Verify ownership
    try:
        existing = await (
            sb.table("spark_leads")
            .select("*")
            .eq("id", str(lead_id))
            .eq("client_id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch lead for update")
        raise HTTPException(status_code=500, detail="Failed to fetch lead")

    if not existing.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Build update payload
    updates: dict[str, Any] = {}
    if body.status is not None:
        valid_statuses = {"new", "contacted", "converted", "lost"}
        if body.status not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}",
            )
        updates["status"] = body.status
    if body.admin_notes is not None:
        updates["admin_notes"] = body.admin_notes

    if not updates:
        return AdminLeadListItem(**existing.data[0])

    try:
        result = await (
            sb.table("spark_leads").update(updates).eq("id", str(lead_id)).execute()
        )
    except Exception:
        logger.exception("Admin: failed to update lead")
        raise HTTPException(status_code=500, detail="Failed to update lead")

    updated = result.data[0] if result.data else existing.data[0]
    return AdminLeadListItem(**updated)


# =============================================================================
# HELPERS
# =============================================================================

# Characters that could trigger CSV formula injection
_CSV_INJECTION_CHARS = {"=", "+", "-", "@", "\t", "\r"}


def _sanitize_csv(value: str) -> str:
    """Sanitize a cell value to prevent CSV injection.

    Prefixes cells starting with dangerous characters with a single quote.
    """
    if value and value[0] in _CSV_INJECTION_CHARS:
        return f"'{value}"
    return value
