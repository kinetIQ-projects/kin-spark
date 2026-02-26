"""
Tests for Knowledge Service — CRUD + embedding logic.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.spark import knowledge as knowledge_svc

_CLIENT_ID = uuid4()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ===========================================================================
# Create
# ===========================================================================


@pytest.mark.unit
class TestCreateKnowledgeItem:
    """Creating knowledge items: hash, embed, insert."""

    @pytest.mark.asyncio
    async def test_create_embeds_and_inserts(self) -> None:
        fake_embedding = [0.1] * 2000
        fake_row = {
            "id": str(uuid4()),
            "client_id": str(_CLIENT_ID),
            "title": "Test",
            "content": "Test content",
            "category": "company",
            "subcategory": None,
            "priority": 5,
            "active": True,
            "embedding_model": "text-embedding-3-large",
            "content_hash": _content_hash("Test content"),
            "created_at": "2026-02-26T00:00:00Z",
            "updated_at": "2026-02-26T00:00:00Z",
        }

        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[fake_row])
        )

        mock_embed = AsyncMock(return_value=fake_embedding)

        with patch.object(knowledge_svc, "create_embedding", mock_embed), patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            result = await knowledge_svc.create_knowledge_item(
                client_id=_CLIENT_ID,
                title="Test",
                content="Test content",
                category="company",
                priority=5,
            )

        assert result["title"] == "Test"
        assert result["content_hash"] == _content_hash("Test content")

        # Verify embedding was called
        mock_embed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_content_hash_returns_409(self) -> None:
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute = AsyncMock(
            side_effect=Exception("duplicate key value violates unique constraint")
        )

        with patch.object(
            knowledge_svc, "create_embedding", AsyncMock(return_value=[0.1] * 2000)
        ), patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await knowledge_svc.create_knowledge_item(
                    client_id=_CLIENT_ID,
                    title="Dup",
                    content="Same content",
                )

        assert exc_info.value.status_code == 409
        assert "already exists" in exc_info.value.detail


# ===========================================================================
# Update
# ===========================================================================


@pytest.mark.unit
class TestUpdateKnowledgeItem:
    """Updating knowledge items: conditional re-embed."""

    @pytest.mark.asyncio
    async def test_content_change_triggers_re_embed(self) -> None:
        item_id = uuid4()
        old_row = {
            "id": str(item_id),
            "client_id": str(_CLIENT_ID),
            "title": "Old Title",
            "content": "Old content",
            "category": "company",
            "subcategory": None,
            "priority": 0,
            "active": True,
            "embedding_model": "text-embedding-3-large",
            "content_hash": _content_hash("Old content"),
            "created_at": "2026-02-26T00:00:00Z",
            "updated_at": "2026-02-26T00:00:00Z",
        }
        updated_row = {**old_row, "content": "New content"}

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[old_row])
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[updated_row])
        )

        mock_embed = AsyncMock(return_value=[0.2] * 2000)

        with patch.object(knowledge_svc, "create_embedding", mock_embed), patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            result = await knowledge_svc.update_knowledge_item(
                item_id=item_id,
                client_id=_CLIENT_ID,
                updates={"content": "New content"},
            )

        # Re-embed was called for new content
        mock_embed.assert_awaited_once()
        assert result["content"] == "New content"

    @pytest.mark.asyncio
    async def test_metadata_only_skips_embedding(self) -> None:
        item_id = uuid4()
        old_row = {
            "id": str(item_id),
            "client_id": str(_CLIENT_ID),
            "title": "Title",
            "content": "Content stays the same",
            "category": "company",
            "subcategory": None,
            "priority": 0,
            "active": True,
            "embedding_model": "text-embedding-3-large",
            "content_hash": _content_hash("Content stays the same"),
            "created_at": "2026-02-26T00:00:00Z",
            "updated_at": "2026-02-26T00:00:00Z",
        }
        updated_row = {**old_row, "priority": 10}

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[old_row])
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[updated_row])
        )

        mock_embed = AsyncMock(return_value=[0.2] * 2000)

        with patch.object(knowledge_svc, "create_embedding", mock_embed), patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            await knowledge_svc.update_knowledge_item(
                item_id=item_id,
                client_id=_CLIENT_ID,
                updates={"priority": 10},
            )

        # Embedding was NOT called — metadata-only change
        mock_embed.assert_not_awaited()


# ===========================================================================
# Delete
# ===========================================================================


@pytest.mark.unit
class TestDeleteKnowledgeItem:
    """Hard delete of knowledge items."""

    @pytest.mark.asyncio
    async def test_delete_removes_row(self) -> None:
        item_id = uuid4()

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[{"id": str(item_id)}])
        )
        mock_sb.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        with patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            await knowledge_svc.delete_knowledge_item(item_id, _CLIENT_ID)

        # Verify delete was called
        mock_sb.table.return_value.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self) -> None:
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        with patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await knowledge_svc.delete_knowledge_item(uuid4(), _CLIENT_ID)

        assert exc_info.value.status_code == 404


# ===========================================================================
# Stats
# ===========================================================================


@pytest.mark.unit
class TestGetKnowledgeStats:
    """Knowledge base statistics."""

    @pytest.mark.asyncio
    async def test_stats_returns_correct_counts(self) -> None:
        rows = [
            {"active": True, "category": "company"},
            {"active": True, "category": "company"},
            {"active": False, "category": "product"},
            {"active": True, "category": "legal"},
        ]

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=rows))
        )

        with patch.object(
            knowledge_svc, "get_supabase_client", AsyncMock(return_value=mock_sb)
        ):
            stats = await knowledge_svc.get_knowledge_stats(_CLIENT_ID)

        assert stats["total_items"] == 4
        assert stats["active_items"] == 3
        assert stats["categories"] == {"company": 2, "product": 1, "legal": 1}
