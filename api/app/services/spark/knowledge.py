"""
Knowledge Service — CRUD + embedding for admin-managed knowledge items.

Each item = 1 row, embedded directly (no chunking). Content capped at 3000 chars.
Dedup via SHA-256 content_hash per client.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.config import settings
from app.services.embeddings import create_embedding
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    """SHA-256 hash of content for deduplication."""
    return hashlib.sha256(content.encode()).hexdigest()


async def create_knowledge_item(
    client_id: UUID,
    title: str,
    content: str,
    category: str = "company",
    subcategory: str | None = None,
    priority: int = 0,
    active: bool = True,
) -> dict[str, Any]:
    """Create a knowledge item: hash, embed, insert.

    Raises HTTPException(409) on duplicate content_hash.
    """
    content_h = _content_hash(content)

    # Embed
    embedding = await create_embedding(content, input_type="document")

    row = {
        "client_id": str(client_id),
        "title": title,
        "content": content,
        "category": category,
        "subcategory": subcategory,
        "priority": priority,
        "active": active,
        "embedding": embedding,
        "embedding_model": settings.embedding_model,
        "content_hash": content_h,
    }

    sb = await get_supabase_client()

    try:
        result = await sb.table("spark_knowledge_items").insert(row).execute()
    except Exception as e:
        # Check for unique violation (content_hash)
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str or "23505" in err_str:
            raise HTTPException(
                status_code=409,
                detail="A knowledge item with this exact content already exists.",
            )
        logger.exception("Knowledge: failed to insert item")
        raise HTTPException(status_code=500, detail="Failed to create knowledge item")

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create knowledge item")

    return result.data[0]


async def update_knowledge_item(
    item_id: UUID,
    client_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update a knowledge item. Re-embeds only if content changed."""
    sb = await get_supabase_client()

    # Verify ownership
    existing = await (
        sb.table("spark_knowledge_items")
        .select("*")
        .eq("id", str(item_id))
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    old_row = existing.data[0]

    # Build update payload (only non-None fields)
    payload: dict[str, Any] = {}
    for key in ("title", "category", "subcategory", "priority", "active"):
        if key in updates and updates[key] is not None:
            payload[key] = updates[key]

    # If content changed, re-embed
    new_content = updates.get("content")
    if new_content is not None and new_content != old_row["content"]:
        new_hash = _content_hash(new_content)
        embedding = await create_embedding(new_content, input_type="document")
        payload["content"] = new_content
        payload["content_hash"] = new_hash
        payload["embedding"] = embedding
        payload["embedding_model"] = settings.embedding_model

    if not payload:
        return old_row

    try:
        result = await (
            sb.table("spark_knowledge_items")
            .update(payload)
            .eq("id", str(item_id))
            .eq("client_id", str(client_id))
            .execute()
        )
    except Exception as e:
        err_str = str(e).lower()
        if "unique" in err_str or "duplicate" in err_str or "23505" in err_str:
            raise HTTPException(
                status_code=409,
                detail="A knowledge item with this exact content already exists.",
            )
        logger.exception("Knowledge: failed to update item")
        raise HTTPException(status_code=500, detail="Failed to update knowledge item")

    return result.data[0] if result.data else old_row


async def delete_knowledge_item(
    item_id: UUID,
    client_id: UUID,
) -> None:
    """Hard delete a knowledge item (admin-managed, not user data)."""
    sb = await get_supabase_client()

    # Verify ownership
    existing = await (
        sb.table("spark_knowledge_items")
        .select("id")
        .eq("id", str(item_id))
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Knowledge item not found")

    try:
        await (
            sb.table("spark_knowledge_items")
            .delete()
            .eq("id", str(item_id))
            .eq("client_id", str(client_id))
            .execute()
        )
    except Exception:
        logger.exception("Knowledge: failed to delete item")
        raise HTTPException(status_code=500, detail="Failed to delete knowledge item")


async def get_knowledge_stats(client_id: UUID) -> dict[str, Any]:
    """Return knowledge base stats: total, active, by category."""
    sb = await get_supabase_client()

    try:
        result = await (
            sb.table("spark_knowledge_items")
            .select("active, category")
            .eq("client_id", str(client_id))
            .execute()
        )
    except Exception:
        logger.exception("Knowledge: failed to fetch stats")
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge stats")

    rows = result.data or []
    total = len(rows)
    active = sum(1 for r in rows if r.get("active", True))

    categories: dict[str, int] = {}
    for r in rows:
        cat = r.get("category", "company")
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "total_items": total,
        "active_items": active,
        "categories": categories,
    }
