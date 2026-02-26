"""
Knowledge Models — Pydantic request/response models for knowledge item CRUD.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeCategory(str, Enum):
    """Valid knowledge item categories (matches DB CHECK constraint)."""

    company = "company"
    product = "product"
    competitor = "competitor"
    legal = "legal"
    team = "team"
    fun = "fun"


class AdminKnowledgeItem(BaseModel):
    """Full knowledge item returned by API."""

    id: UUID
    client_id: UUID
    title: str
    content: str
    category: KnowledgeCategory
    subcategory: str | None = None
    priority: int = 0
    active: bool = True
    embedding_model: str | None = None
    content_hash: str
    created_at: datetime
    updated_at: datetime


class AdminKnowledgeCreate(BaseModel):
    """Request body for creating a knowledge item."""

    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(
        ...,
        min_length=1,
        max_length=3000,
        description="Knowledge items should be focused chunks. "
        "For longer content, use document ingestion.",
    )
    category: KnowledgeCategory = KnowledgeCategory.company
    subcategory: str | None = None
    priority: int = Field(default=0, ge=0, le=100)
    active: bool = True


class AdminKnowledgeUpdate(BaseModel):
    """Request body for updating a knowledge item. All fields optional."""

    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = Field(
        None,
        min_length=1,
        max_length=3000,
        description="Knowledge items should be focused chunks. "
        "For longer content, use document ingestion.",
    )
    category: KnowledgeCategory | None = None
    subcategory: str | None = None
    priority: int | None = Field(None, ge=0, le=100)
    active: bool | None = None


class AdminKnowledgeStats(BaseModel):
    """Knowledge base statistics for admin header."""

    total_items: int
    active_items: int
    categories: dict[str, int] = Field(default_factory=dict)
