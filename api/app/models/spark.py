"""
Spark Models — Pydantic request/response models for Kin Spark.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# REQUEST MODELS
# =============================================================================


class SparkChatRequest(BaseModel):
    """Incoming chat message from widget."""

    message: str = Field(..., min_length=1, max_length=4000)
    session_token: str | None = None
    fingerprint: str | None = None


class SparkLeadCreate(BaseModel):
    """Lead capture from widget."""

    conversation_id: UUID
    name: str | None = None
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=50)
    notes: str | None = None


class SparkIngestTextRequest(BaseModel):
    """Ingest raw text as knowledge."""

    content: str = Field(..., min_length=1)
    title: str | None = None
    source_type: str = "text"


class SparkIngestUrlRequest(BaseModel):
    """Ingest content from a URL."""

    url: str = Field(..., min_length=1)
    title: str | None = None


class SparkEventRequest(BaseModel):
    """Widget analytics event."""

    event_type: str = Field(..., min_length=1, max_length=100)
    conversation_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# RESPONSE / SSE MODELS
# =============================================================================


class SparkChatEvent(BaseModel):
    """SSE event sent back to widget."""

    event: Literal["session", "token", "wind_down", "done", "error"]
    data: dict[str, Any] = Field(default_factory=dict)


class SparkConversationSummary(BaseModel):
    """Conversation summary for admin endpoints."""

    id: UUID
    client_id: UUID
    session_token: str
    ip_address: str
    turn_count: int
    state: str
    created_at: datetime
    updated_at: datetime


class SparkMessageOut(BaseModel):
    """Message for admin transcript endpoint."""

    id: UUID
    role: str
    content: str
    created_at: datetime


class SparkLeadOut(BaseModel):
    """Lead for admin list endpoint."""

    id: UUID
    client_id: UUID
    conversation_id: UUID | None
    name: str | None
    email: str | None
    phone: str | None
    notes: str | None
    created_at: datetime


# =============================================================================
# INTERNAL MODELS
# =============================================================================


class SparkClient(BaseModel):
    """Client row from spark_clients table."""

    id: UUID
    name: str
    slug: str
    api_key_hash: str
    settling_config: dict[str, Any] = Field(default_factory=dict)
    max_turns: int = 20
    rate_limit_rpm: int = 30
    active: bool = True
    client_orientation: str | None = None

    class Config:
        from_attributes = True


class PreflightResult(BaseModel):
    """Result from pre-flight safety + retrieval."""

    safe: bool = True
    in_scope: bool = True
    rejection_tier: Literal["subtle", "firm", "terminate"] | None = None
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    conversation_state: str = "active"
