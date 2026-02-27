"""
Spark Router — HTTP endpoints for Kin Spark AI Rep.

Endpoints:
  POST /spark/chat         — SSE streaming conversation
  POST /spark/lead         — Lead capture from widget
  GET  /spark/conversations — Admin: list conversations
  GET  /spark/conversations/{id}/messages — Admin: transcript
  GET  /spark/leads        — Admin: lead list
  POST /spark/ingest/text  — Ingest raw text
  POST /spark/ingest/url   — Scrape and ingest URL
  POST /spark/event        — Widget analytics event
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models.spark import (
    SparkChatRequest,
    SparkClient,
    SparkConversationSummary,
    SparkEventRequest,
    SparkIngestTextRequest,
    SparkIngestUrlRequest,
    SparkLeadCreate,
    SparkLeadOut,
    SparkMessageOut,
)
from app.services.spark.auth import verify_spark_api_key
from app.services.spark.core import process_message
from app.services.spark.rate_limiter import get_rate_limiter
from app.services.spark.session import create_session, end_session, get_session
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# CHAT (SSE Streaming)
# =============================================================================


@router.post("/chat")
async def spark_chat(
    body: SparkChatRequest,
    request: Request,
    client: SparkClient = Depends(verify_spark_api_key),
) -> StreamingResponse:
    """Main chat endpoint. Returns SSE stream."""
    ip = _get_client_ip(request)

    # Rate limit
    limiter = get_rate_limiter()
    if not limiter.check(str(client.id), ip, client.rate_limit_rpm):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Session management
    session: dict[str, Any] | None = None
    if body.session_token:
        session = await get_session(body.session_token, ip)

    if session is None:
        # Create new session
        session = await create_session(
            client_id=client.id,
            ip_address=ip,
            fingerprint=body.fingerprint,
        )

    conversation_id = UUID(session["id"])
    turn_count = session["turn_count"]

    # Build SSE generator
    async def event_stream():  # type: ignore[no-untyped-def]
        # First event: session info
        from app.services.spark.core import _sse_event

        yield _sse_event(
            "session",
            {
                "session_token": session["session_token"],
                "turns_remaining": client.max_turns - turn_count,
                "conversation_id": str(conversation_id),
            },
        )

        # Stream the response
        async for event in process_message(
            message=body.message,
            client_id=client.id,
            conversation_id=conversation_id,
            settling_config=client.settling_config,
            max_turns=client.max_turns,
            turn_count=turn_count,
            client_orientation=client.client_orientation,
        ):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# LEAD CAPTURE
# =============================================================================


@router.post("/lead")
async def spark_lead(
    body: SparkLeadCreate,
    client: SparkClient = Depends(verify_spark_api_key),
) -> dict[str, str]:
    """Capture a lead from the widget."""
    import asyncio

    from app.services.spark.crm import sync_lead

    sb = await get_supabase_client()

    lead_row = (
        await sb.table("spark_leads")
        .insert(
            {
                "client_id": str(client.id),
                "conversation_id": str(body.conversation_id),
                "name": body.name,
                "email": body.email,
                "phone": body.phone,
                "company_name": body.company_name,
                "notes": body.notes,
            }
        )
        .execute()
    )

    lead_id = lead_row.data[0]["id"] if lead_row.data else None

    # Set outcome on the conversation
    await (
        sb.table("spark_conversations")
        .update({"outcome": "lead_captured"})
        .eq("id", str(body.conversation_id))
        .execute()
    )

    # Analytics
    await sb.table("spark_events").insert(
        {
            "client_id": str(client.id),
            "conversation_id": str(body.conversation_id),
            "event_type": "lead_captured",
            "metadata": {
                "has_email": body.email is not None,
                "has_phone": body.phone is not None,
                "has_company": body.company_name is not None,
            },
        }
    ).execute()

    # CRM sync (fire-and-forget)
    if lead_id:
        try:
            from uuid import UUID as _UUID

            lead_data = {
                "email": body.email,
                "name": body.name,
                "phone": body.phone,
                "company_name": body.company_name,
                "notes": body.notes,
                "conversation_id": str(body.conversation_id),
            }
            asyncio.create_task(sync_lead(client.id, _UUID(str(lead_id)), lead_data))
        except (ValueError, TypeError):
            logger.warning("Could not parse lead_id for CRM sync: %s", lead_id)

    return {"status": "captured"}


# =============================================================================
# ANALYTICS EVENT
# =============================================================================


@router.post("/event")
async def spark_event(
    body: SparkEventRequest,
    client: SparkClient = Depends(verify_spark_api_key),
) -> dict[str, str]:
    """Record a widget analytics event."""
    sb = await get_supabase_client()

    await sb.table("spark_events").insert(
        {
            "client_id": str(client.id),
            "conversation_id": (
                str(body.conversation_id) if body.conversation_id else None
            ),
            "event_type": body.event_type,
            "metadata": body.metadata,
        }
    ).execute()

    return {"status": "recorded"}


# =============================================================================
# ADMIN: CONVERSATIONS
# =============================================================================


@router.get("/conversations")
async def list_conversations(
    client: SparkClient = Depends(verify_spark_api_key),
    limit: int = 50,
    offset: int = 0,
) -> list[SparkConversationSummary]:
    """List conversations for this client (admin)."""
    sb = await get_supabase_client()

    result = await (
        sb.table("spark_conversations")
        .select("*")
        .eq("client_id", str(client.id))
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [SparkConversationSummary(**row) for row in (result.data or [])]


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    client: SparkClient = Depends(verify_spark_api_key),
) -> list[SparkMessageOut]:
    """Get messages for a conversation (admin)."""
    sb = await get_supabase_client()

    # Verify conversation belongs to this client
    conv = (
        await sb.table("spark_conversations")
        .select("client_id")
        .eq("id", str(conversation_id))
        .execute()
    )

    if not conv.data or conv.data[0]["client_id"] != str(client.id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await (
        sb.table("spark_messages")
        .select("*")
        .eq("conversation_id", str(conversation_id))
        .order("created_at", desc=False)
        .execute()
    )

    return [SparkMessageOut(**row) for row in (result.data or [])]


# =============================================================================
# ADMIN: LEADS
# =============================================================================


@router.get("/leads")
async def list_leads(
    client: SparkClient = Depends(verify_spark_api_key),
    limit: int = 50,
    offset: int = 0,
) -> list[SparkLeadOut]:
    """List leads for this client (admin)."""
    sb = await get_supabase_client()

    result = await (
        sb.table("spark_leads")
        .select("*")
        .eq("client_id", str(client.id))
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return [SparkLeadOut(**row) for row in (result.data or [])]


# =============================================================================
# INGESTION
# =============================================================================


@router.post("/ingest/text")
async def ingest_text_endpoint(
    body: SparkIngestTextRequest,
    client: SparkClient = Depends(verify_spark_api_key),
) -> dict[str, Any]:
    """Ingest raw text as knowledge for this client."""
    from app.services.spark.ingestion import ingest_text

    count = await ingest_text(
        client_id=client.id,
        content=body.content,
        title=body.title,
        source_type=body.source_type,
    )

    return {"chunks_inserted": count}


@router.post("/ingest/url")
async def ingest_url_endpoint(
    body: SparkIngestUrlRequest,
    client: SparkClient = Depends(verify_spark_api_key),
) -> dict[str, Any]:
    """Scrape a URL and ingest its content."""
    from app.services.spark.ingestion import ingest_url

    try:
        count = await ingest_url(
            client_id=client.id,
            url=body.url,
            title=body.title,
        )
    except Exception as e:
        logger.error("Spark URL ingestion failed: %s", e)
        raise HTTPException(status_code=422, detail="Failed to fetch URL")

    return {"chunks_inserted": count}
