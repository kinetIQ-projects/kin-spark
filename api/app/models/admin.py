"""
Admin Portal Models — Pydantic request/response models for admin endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# CONVERSATION MODELS
# =============================================================================


class AdminConversationListItem(BaseModel):
    """Single conversation in the admin list view."""

    id: UUID
    first_message_preview: str | None = None
    turn_count: int
    state: str
    outcome: str | None = None
    sentiment: str | None = None
    created_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None


class AdminTranscriptMessage(BaseModel):
    """A single message in a conversation transcript."""

    id: UUID
    role: str
    content: str
    created_at: datetime


class AdminConversationDetail(BaseModel):
    """Full conversation detail for admin view."""

    id: UUID
    client_id: UUID
    turn_count: int
    state: str
    outcome: str | None = None
    sentiment: str | None = None
    sentiment_score: float | None = None
    summary: str | None = None
    created_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    messages: list[AdminTranscriptMessage] = Field(default_factory=list)
    lead: AdminLeadSummary | None = None


class AdminLeadSummary(BaseModel):
    """Lead info embedded in conversation detail."""

    id: UUID
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: str = "new"
    created_at: datetime


# =============================================================================
# LEAD MODELS
# =============================================================================


class AdminLeadListItem(BaseModel):
    """Single lead in the admin list view."""

    id: UUID
    client_id: UUID
    conversation_id: UUID | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    status: str = "new"
    admin_notes: str | None = None
    created_at: datetime


class AdminLeadUpdate(BaseModel):
    """Request body for updating a lead."""

    status: str | None = None
    admin_notes: str | None = None


# =============================================================================
# CLIENT / PROFILE MODELS
# =============================================================================


class AdminClientProfile(BaseModel):
    """Client profile returned by GET /me."""

    id: UUID
    name: str
    slug: str
    active: bool
    max_turns: int
    rate_limit_rpm: int
    accent_color: str | None = None
    widget_position: str | None = None
    widget_title: str | None = None
    widget_avatar_url: str | None = None
    greeting_message: str | None = None
    notification_email: str | None = None
    notifications_enabled: bool = False
    daily_conversation_cap: int | None = None
    sessions_per_visitor_per_day: int | None = None
    settling_config: dict[str, Any] = Field(default_factory=dict)
    onboarding_data: dict[str, Any] = Field(default_factory=dict)
    client_orientation: str | None = None
    created_at: datetime | None = None


class AdminSettingsUpdate(BaseModel):
    """Request body for PATCH /settings — partial settling_config update."""

    timezone: str | None = None


# =============================================================================
# PAGINATION
# =============================================================================


class PaginatedResponse(BaseModel):
    """Wrapper for paginated list responses."""

    items: list[Any]
    total: int
    limit: int
    offset: int


# =============================================================================
# ONBOARDING MODELS
# =============================================================================


class OnboardingCustomerProfile(BaseModel):
    """Single ICP entry in the questionnaire."""

    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    signals: str = Field(default="", max_length=1000)
    needs: str = Field(default="", max_length=1000)


class OnboardingUpdate(BaseModel):
    """Partial update to questionnaire responses.

    All fields optional — allows saving one section at a time.
    Shallow merge: PATCH replaces entire sections, not individual fields within.
    """

    purpose_story: dict[str, str] | None = None
    values_culture: dict[str, str] | None = None
    brand_voice: dict[str, str | list[str]] | None = None
    customers: list[OnboardingCustomerProfile] | None = Field(default=None, max_length=50)
    procedures_policies: dict[str, str] | None = None
    additional_context: str | None = Field(default=None, max_length=5000)
    completed_at: str | None = None


class OrientationUpdate(BaseModel):
    """Set client orientation text."""

    orientation: str = Field(..., max_length=20000)


class OrientationResponse(BaseModel):
    """Response for orientation GET."""

    orientation: str | None = None
    template_name: str = "core"
