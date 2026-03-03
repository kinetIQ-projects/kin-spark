"""
Ingestion Pipeline — Pydantic models for upload, paste, and pipeline endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ── Upload ──────────────────────────────────────────────────────────


class PresignRequest(BaseModel):
    """Request a presigned upload path."""

    filename: str = Field(..., min_length=1, max_length=255)
    mime_type: str
    file_size: int = Field(..., gt=0, le=50_000_000)


class PresignResponse(BaseModel):
    """Presigned upload details returned to the portal."""

    upload_id: UUID
    storage_path: str


class FileUploadOut(BaseModel):
    """Upload record returned to the portal."""

    id: UUID
    filename: str
    original_name: str
    mime_type: str
    file_size: int
    source_type: str
    status: str
    page_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Paste ───────────────────────────────────────────────────────────


class PasteItemCreate(BaseModel):
    """Submit pasted text for ingestion."""

    content: str = Field(..., min_length=1, max_length=50_000)
    title: str | None = Field(None, max_length=200)


class PasteItemOut(BaseModel):
    """Paste item record returned to the portal."""

    id: UUID
    content: str
    title: str | None = None
    created_at: datetime


# ── Website URL ─────────────────────────────────────────────────────


class WebsiteUrlUpdate(BaseModel):
    """Update the client's website URL for scraping."""

    website_url: str | None = Field(None, max_length=2000)


class WebsiteUrlOut(BaseModel):
    """Current website URL."""

    website_url: str | None = None


# ── Pipeline ────────────────────────────────────────────────────────


class PipelineTriggerRequest(BaseModel):
    """Request to trigger a pipeline run."""

    include_uploads: bool = True
    include_paste: bool = True
    include_questionnaire: bool = True
    include_scrape: bool = False
    trigger_type: str = Field(default="manual", pattern="^(manual|rerun)$")


class PipelineRunOut(BaseModel):
    """Pipeline run record returned to the portal."""

    id: UUID
    status: str
    trigger_type: str
    progress: dict[str, Any] | None = None
    source_summary: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


# ── Profiles ──────────────────────────────────────────────────────────


class ProfileOut(BaseModel):
    """Generated profile document returned to the portal."""

    id: UUID
    profile_type: str
    version: int
    content: str
    status: str
    client_feedback: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Update profile status (approve/reject)."""

    status: str = Field(..., pattern="^(approved|rejected|pending_review)$")


class ProfileChangeRequest(BaseModel):
    """Client requests changes to a profile."""

    feedback: str = Field(..., min_length=1, max_length=5000)
