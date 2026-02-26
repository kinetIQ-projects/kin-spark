"""
Spark Admin Router — Authenticated endpoints for the admin portal.

Endpoints:
  GET  /spark/admin/me                    — Client profile
  PATCH /spark/admin/settings             — Update settings (timezone, etc.)
  GET  /spark/admin/onboarding            — Get questionnaire responses
  PATCH /spark/admin/onboarding           — Save partial/complete questionnaire
  GET  /spark/admin/orientation           — Get client orientation text
  PUT  /spark/admin/orientation           — Set client orientation text
  GET  /spark/admin/conversations         — List conversations (filterable)
  GET  /spark/admin/conversations/{id}    — Conversation detail + transcript
  GET  /spark/admin/leads                 — List leads (filterable)
  PATCH /spark/admin/leads/{id}           — Update lead status/notes
  GET  /spark/admin/leads/export          — CSV export
  GET  /spark/admin/knowledge             — List knowledge items (filterable)
  GET  /spark/admin/knowledge/stats       — Knowledge base stats
  POST /spark/admin/knowledge             — Create knowledge item
  GET  /spark/admin/knowledge/{id}        — Single knowledge item
  PATCH /spark/admin/knowledge/{id}       — Update knowledge item
  DELETE /spark/admin/knowledge/{id}      — Delete knowledge item
  GET  /spark/admin/metrics/summary       — Dashboard KPI summary
  GET  /spark/admin/metrics/timeseries    — Dashboard charts data
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
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
    AdminSettingsUpdate,
    AdminTranscriptMessage,
    OnboardingUpdate,
    OrientationResponse,
    OrientationUpdate,
    PaginatedResponse,
)
from app.models.dashboard import (
    DashboardSummary,
    DashboardTimeseries,
    OutcomeBucket,
    SentimentBucket,
    TimeseriesPoint,
)
from app.models.knowledge import (
    AdminKnowledgeCreate,
    AdminKnowledgeItem,
    AdminKnowledgeStats,
    AdminKnowledgeUpdate,
)
from app.models.spark import SparkClient
from app.services.spark.admin_auth import verify_admin_jwt
from app.services.spark import knowledge as knowledge_svc
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
        settling_config=row.get("settling_config") or {},
        onboarding_data=row.get("onboarding_data") or {},
        client_orientation=row.get("client_orientation"),
        created_at=row.get("created_at"),
    )


@router.patch("/settings")
async def update_settings(
    body: AdminSettingsUpdate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminClientProfile:
    """Update settling_config fields (merges into existing JSONB)."""
    from zoneinfo import available_timezones

    sb = await get_supabase_client()

    # Build partial config from non-None fields
    updates: dict[str, Any] = {}
    if body.timezone is not None:
        if body.timezone not in available_timezones():
            raise HTTPException(
                status_code=422,
                detail=f"Invalid timezone: {body.timezone}",
            )
        updates["timezone"] = body.timezone

    if not updates:
        # Nothing to change — return current profile
        result = await (
            sb.table("spark_clients")
            .select("*")
            .eq("id", str(client.id))
            .limit(1)
            .execute()
        )
        row = result.data[0]
    else:
        # Fetch current settling_config, merge, write back
        try:
            current = await (
                sb.table("spark_clients")
                .select("settling_config")
                .eq("id", str(client.id))
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception("Admin: failed to fetch settling_config")
            raise HTTPException(status_code=500, detail="Failed to fetch settings")

        existing_config: dict[str, Any] = (current.data[0].get("settling_config") or {}) if current.data else {}
        merged = {**existing_config, **updates}

        try:
            result = await (
                sb.table("spark_clients")
                .update({"settling_config": merged})
                .eq("id", str(client.id))
                .execute()
            )
        except Exception:
            logger.exception("Admin: failed to update settling_config")
            raise HTTPException(status_code=500, detail="Failed to update settings")

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
        settling_config=row.get("settling_config") or {},
        onboarding_data=row.get("onboarding_data") or {},
        client_orientation=row.get("client_orientation"),
        created_at=row.get("created_at"),
    )


# =============================================================================
# ONBOARDING
# =============================================================================


@router.get("/onboarding")
async def get_onboarding(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    """Get current questionnaire responses."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_clients")
            .select("onboarding_data")
            .eq("id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch onboarding data")
        raise HTTPException(status_code=500, detail="Failed to fetch onboarding data")

    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    row = result.data[0]
    return {"onboarding_data": row.get("onboarding_data") or {}}


@router.patch("/onboarding")
async def update_onboarding(
    body: OnboardingUpdate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> dict[str, Any]:
    """Save partial or complete questionnaire responses."""
    sb = await get_supabase_client()

    # Fetch current onboarding_data
    try:
        current_result = await (
            sb.table("spark_clients")
            .select("onboarding_data")
            .eq("id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch onboarding data for update")
        raise HTTPException(status_code=500, detail="Failed to fetch onboarding data")

    if not current_result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    current: dict[str, Any] = current_result.data[0].get("onboarding_data") or {}

    # Shallow merge: only non-None fields from the request body
    update_dict = body.model_dump(exclude_none=True)
    for key, value in update_dict.items():
        current[key] = value
    current["last_saved_at"] = datetime.now(timezone.utc).isoformat()

    # Write merged data back
    try:
        result = await (
            sb.table("spark_clients")
            .update({"onboarding_data": current})
            .eq("id", str(client.id))
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to update onboarding data")
        raise HTTPException(status_code=500, detail="Failed to update onboarding data")

    return {"onboarding_data": current}


# =============================================================================
# ORIENTATION
# =============================================================================


@router.get("/orientation")
async def get_orientation(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> OrientationResponse:
    """Get client's current orientation text."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_clients")
            .select("client_orientation, settling_config")
            .eq("id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch orientation")
        raise HTTPException(status_code=500, detail="Failed to fetch orientation")

    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    row = result.data[0]
    settling_config: dict[str, Any] = row.get("settling_config") or {}
    return OrientationResponse(
        orientation=row.get("client_orientation"),
        template_name=settling_config.get("orientation_template", "core"),
    )


@router.put("/orientation")
async def set_orientation(
    body: OrientationUpdate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> OrientationResponse:
    """Set client's orientation text."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_clients")
            .update({"client_orientation": body.orientation})
            .eq("id", str(client.id))
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to update orientation")
        raise HTTPException(status_code=500, detail="Failed to update orientation")

    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")

    row = result.data[0]
    settling_config: dict[str, Any] = row.get("settling_config") or {}
    return OrientationResponse(
        orientation=body.orientation,
        template_name=settling_config.get("orientation_template", "core"),
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
# KNOWLEDGE
# =============================================================================

_KNOWLEDGE_SORT_FIELDS = {"priority", "updated_at", "title", "category"}


@router.get("/knowledge")
async def list_knowledge(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    category: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    sort: str | None = Query(default=None),
) -> PaginatedResponse:
    """List knowledge items with optional filters.

    Default sort: priority DESC, updated_at DESC.
    Override via sort param (priority, updated_at, title, category).
    """
    sb = await get_supabase_client()

    try:
        query = (
            sb.table("spark_knowledge_items")
            .select("*", count="exact")
            .eq("client_id", str(client.id))
        )

        if category:
            query = query.eq("category", category)
        if active is not None:
            query = query.eq("active", active)
        if search:
            query = query.ilike("title", f"%{search}%")

        # Sorting
        if sort and sort in _KNOWLEDGE_SORT_FIELDS:
            desc = sort in ("priority", "updated_at")
            query = query.order(sort, desc=desc)
        else:
            query = query.order("priority", desc=True).order("updated_at", desc=True)

        query = query.range(offset, offset + limit - 1)
        result = await query.execute()
    except Exception:
        logger.exception("Admin: failed to list knowledge items")
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge items")

    items = result.data or []
    total = result.count if result.count is not None else len(items)

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/knowledge/stats")
async def get_knowledge_stats(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminKnowledgeStats:
    """Category counts for admin header."""
    stats = await knowledge_svc.get_knowledge_stats(client.id)
    return AdminKnowledgeStats(**stats)


@router.post("/knowledge", status_code=201)
async def create_knowledge(
    body: AdminKnowledgeCreate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminKnowledgeItem:
    """Create a knowledge item, embed content, return 201."""
    row = await knowledge_svc.create_knowledge_item(
        client_id=client.id,
        title=body.title,
        content=body.content,
        category=body.category.value,
        subcategory=body.subcategory,
        priority=body.priority,
        active=body.active,
    )
    return AdminKnowledgeItem(**row)


@router.get("/knowledge/{item_id}")
async def get_knowledge_item(
    item_id: UUID,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminKnowledgeItem:
    """Get a single knowledge item."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_knowledge_items")
            .select("*")
            .eq("id", str(item_id))
            .eq("client_id", str(client.id))
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("Admin: failed to fetch knowledge item")
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge item")

    if not result.data:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    return AdminKnowledgeItem(**result.data[0])


@router.patch("/knowledge/{item_id}")
async def update_knowledge(
    item_id: UUID,
    body: AdminKnowledgeUpdate,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> AdminKnowledgeItem:
    """Update a knowledge item (re-embeds if content changed)."""
    updates: dict[str, Any] = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.content is not None:
        updates["content"] = body.content
    if body.category is not None:
        updates["category"] = body.category.value
    if body.subcategory is not None:
        updates["subcategory"] = body.subcategory
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.active is not None:
        updates["active"] = body.active

    row = await knowledge_svc.update_knowledge_item(item_id, client.id, updates)
    return AdminKnowledgeItem(**row)


@router.delete("/knowledge/{item_id}", status_code=204)
async def delete_knowledge(
    item_id: UUID,
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> None:
    """Hard delete a knowledge item."""
    await knowledge_svc.delete_knowledge_item(item_id, client.id)


# =============================================================================
# METRICS
# =============================================================================

_TRUNCATION_LIMIT = 10000


@router.get("/metrics/summary")
async def metrics_summary(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    days: int = Query(default=7, ge=1, le=90),
) -> DashboardSummary:
    """Dashboard KPI summary: totals, conversion rate, averages."""
    sb = await get_supabase_client()
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        conv_result, lead_result = await asyncio.gather(
            sb.table("spark_conversations")
            .select("turn_count,created_at,ended_at", count="exact")
            .eq("client_id", str(client.id))
            .gte("created_at", since_iso)
            .limit(_TRUNCATION_LIMIT)
            .execute(),
            sb.table("spark_leads")
            .select("id", count="exact")
            .eq("client_id", str(client.id))
            .gte("created_at", since_iso)
            .limit(_TRUNCATION_LIMIT)
            .execute(),
        )
    except Exception:
        logger.exception("Admin: failed to fetch summary metrics")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")

    conversations = conv_result.data or []
    total_conversations = (
        conv_result.count if conv_result.count is not None else len(conversations)
    )
    total_leads = (
        lead_result.count
        if lead_result.count is not None
        else len(lead_result.data or [])
    )

    # Truncation detection
    if len(conversations) < total_conversations:
        logger.warning(
            "Admin metrics: conversation rows truncated for client %s "
            "(fetched=%d, total=%d)",
            client.id,
            len(conversations),
            total_conversations,
        )
    if len(lead_result.data or []) < total_leads:
        logger.warning(
            "Admin metrics: lead rows truncated for client %s "
            "(fetched=%d, total=%d)",
            client.id,
            len(lead_result.data or []),
            total_leads,
        )

    # Conversion rate
    conversion_rate = (
        total_leads / total_conversations if total_conversations > 0 else 0.0
    )

    # Average turns (from fetched rows — accurate unless truncated)
    turn_counts = [row.get("turn_count", 0) for row in conversations]
    avg_turns = sum(turn_counts) / len(turn_counts) if turn_counts else 0.0

    # Average duration (only rows with both timestamps)
    durations: list[float] = []
    for row in conversations:
        created = row.get("created_at")
        ended = row.get("ended_at")
        if created and ended:
            try:
                dt_created = datetime.fromisoformat(created)
                dt_ended = datetime.fromisoformat(ended)
                durations.append((dt_ended - dt_created).total_seconds())
            except (ValueError, TypeError):
                pass

    avg_duration = sum(durations) / len(durations) if durations else None

    return DashboardSummary(
        total_conversations=total_conversations,
        total_leads=total_leads,
        conversion_rate=round(conversion_rate, 4),
        avg_turns=round(avg_turns, 1),
        avg_duration_seconds=(
            round(avg_duration, 1) if avg_duration is not None else None
        ),
        conversations_with_duration=len(durations),
    )


@router.get("/metrics/timeseries")
async def metrics_timeseries(
    request: Request,
    _rate: None = Depends(_admin_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
    days: int = Query(default=7, ge=1, le=90),
) -> DashboardTimeseries:
    """Dashboard timeseries: daily counts, outcome and sentiment distributions."""
    sb = await get_supabase_client()
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        conv_result, lead_result = await asyncio.gather(
            sb.table("spark_conversations")
            .select("created_at,outcome,sentiment", count="exact")
            .eq("client_id", str(client.id))
            .gte("created_at", since_iso)
            .limit(_TRUNCATION_LIMIT)
            .execute(),
            sb.table("spark_leads")
            .select("created_at", count="exact")
            .eq("client_id", str(client.id))
            .gte("created_at", since_iso)
            .limit(_TRUNCATION_LIMIT)
            .execute(),
        )
    except Exception:
        logger.exception("Admin: failed to fetch timeseries metrics")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")

    conversations = conv_result.data or []
    leads = lead_result.data or []

    # Truncation detection
    conv_total = (
        conv_result.count if conv_result.count is not None else len(conversations)
    )
    lead_total = lead_result.count if lead_result.count is not None else len(leads)
    if len(conversations) < conv_total:
        logger.warning(
            "Admin timeseries: conversation rows truncated for client %s "
            "(fetched=%d, total=%d)",
            client.id,
            len(conversations),
            conv_total,
        )
    if len(leads) < lead_total:
        logger.warning(
            "Admin timeseries: lead rows truncated for client %s "
            "(fetched=%d, total=%d)",
            client.id,
            len(leads),
            lead_total,
        )

    # Build date range (full range, gap-filled with zeros)
    # NOTE: UTC date boundaries (v1) — no timezone adjustment
    today = datetime.now(timezone.utc).date()
    date_range = [
        (today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)
    ]

    # Bucket conversations by date
    conv_by_date: Counter[str] = Counter()
    for row in conversations:
        created = row.get("created_at")
        if created:
            try:
                conv_by_date[datetime.fromisoformat(created).date().isoformat()] += 1
            except (ValueError, TypeError):
                pass

    # Bucket leads by date
    lead_by_date: Counter[str] = Counter()
    for row in leads:
        created = row.get("created_at")
        if created:
            try:
                lead_by_date[datetime.fromisoformat(created).date().isoformat()] += 1
            except (ValueError, TypeError):
                pass

    daily = [
        TimeseriesPoint(
            date=d,
            conversations=conv_by_date.get(d, 0),
            leads=lead_by_date.get(d, 0),
        )
        for d in date_range
    ]

    # Outcome distribution (exclude None/null)
    outcome_counts: Counter[str] = Counter()
    for row in conversations:
        outcome = row.get("outcome")
        if outcome:
            outcome_counts[outcome] += 1

    outcomes = [
        OutcomeBucket(outcome=k, count=v) for k, v in outcome_counts.most_common()
    ]

    # Sentiment distribution (exclude None/null)
    sentiment_counts: Counter[str] = Counter()
    for row in conversations:
        sentiment = row.get("sentiment")
        if sentiment:
            sentiment_counts[sentiment] += 1

    sentiments = [
        SentimentBucket(sentiment=k, count=v) for k, v in sentiment_counts.most_common()
    ]

    return DashboardTimeseries(daily=daily, outcomes=outcomes, sentiments=sentiments)


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
