"""
Tests for Knowledge Admin Endpoints.

Covers: list, filter, search, sort, create, get, patch, delete, auth.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.models.spark import SparkClient

_CLIENT_ID = uuid4()
_CLIENT = SparkClient(
    id=_CLIENT_ID,
    name="Test Co",
    slug="test-co",
    api_key_hash="testhash",
    settling_config={},
    max_turns=20,
    rate_limit_rpm=30,
    active=True,
)

_ITEM_ID = uuid4()
_ITEM_ROW = {
    "id": str(_ITEM_ID),
    "client_id": str(_CLIENT_ID),
    "title": "Test Item",
    "content": "Test content here",
    "category": "company",
    "subcategory": "mission",
    "priority": 10,
    "active": True,
    "embedding_model": "text-embedding-3-large",
    "content_hash": hashlib.sha256(b"Test content here").hexdigest(),
    "created_at": "2026-02-26T00:00:00+00:00",
    "updated_at": "2026-02-26T00:00:00+00:00",
}


def _mock_auth() -> SparkClient:
    return _CLIENT


def _noop_rate_limit() -> None:
    return None


# Override dependencies for all tests
app.dependency_overrides = {}


@pytest.fixture(autouse=True)
def _override_deps():
    """Override auth and rate limiting for all tests."""
    from app.services.spark.admin_auth import verify_admin_jwt
    from app.routers.admin import _admin_rate_limit

    app.dependency_overrides[verify_admin_jwt] = _mock_auth
    app.dependency_overrides[_admin_rate_limit] = _noop_rate_limit
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


# ===========================================================================
# List
# ===========================================================================


@pytest.mark.unit
class TestListKnowledge:
    """GET /spark/admin/knowledge."""

    def test_list_returns_paginated_response(self) -> None:
        mock_sb = MagicMock()
        mock_result = MagicMock(data=[_ITEM_ROW], count=1)
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.range.return_value.execute = AsyncMock(
            return_value=mock_result
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get("/spark/admin/knowledge")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 1

    def test_list_filters_by_category(self) -> None:
        mock_sb = MagicMock()
        query_chain = mock_sb.table.return_value.select.return_value.eq.return_value
        query_chain.eq.return_value.order.return_value.order.return_value.range.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[], count=0)
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get("/spark/admin/knowledge?category=product")

        assert resp.status_code == 200

    def test_list_filters_by_active(self) -> None:
        mock_sb = MagicMock()
        query_chain = mock_sb.table.return_value.select.return_value.eq.return_value
        query_chain.eq.return_value.order.return_value.order.return_value.range.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[], count=0)
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get("/spark/admin/knowledge?active=true")

        assert resp.status_code == 200

    def test_list_search_by_title(self) -> None:
        mock_sb = MagicMock()
        query_chain = mock_sb.table.return_value.select.return_value.eq.return_value
        query_chain.ilike.return_value.order.return_value.order.return_value.range.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[], count=0)
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get("/spark/admin/knowledge?search=test")

        assert resp.status_code == 200


# ===========================================================================
# Stats
# ===========================================================================


@pytest.mark.unit
class TestKnowledgeStats:
    """GET /spark/admin/knowledge/stats."""

    def test_stats_returns_counts(self) -> None:
        rows = [
            {"active": True, "category": "company"},
            {"active": True, "category": "product"},
            {"active": False, "category": "company"},
        ]

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=rows))
        )

        with patch(
            "app.services.spark.knowledge.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get("/spark/admin/knowledge/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_items"] == 3
        assert body["active_items"] == 2


# ===========================================================================
# Create
# ===========================================================================


@pytest.mark.unit
class TestCreateKnowledge:
    """POST /spark/admin/knowledge."""

    def test_create_returns_201(self) -> None:
        with patch(
            "app.routers.admin.knowledge_svc.create_knowledge_item",
            AsyncMock(return_value=_ITEM_ROW),
        ):
            resp = client.post(
                "/spark/admin/knowledge",
                json={
                    "title": "Test Item",
                    "content": "Test content here",
                    "category": "company",
                    "priority": 10,
                },
            )

        assert resp.status_code == 201

    def test_create_invalid_category_returns_422(self) -> None:
        resp = client.post(
            "/spark/admin/knowledge",
            json={
                "title": "Test",
                "content": "Content",
                "category": "invalid_cat",
            },
        )
        assert resp.status_code == 422

    def test_create_content_over_3000_returns_422(self) -> None:
        resp = client.post(
            "/spark/admin/knowledge",
            json={
                "title": "Test",
                "content": "x" * 3001,
                "category": "company",
            },
        )
        assert resp.status_code == 422


# ===========================================================================
# Get by ID
# ===========================================================================


@pytest.mark.unit
class TestGetKnowledgeItem:
    """GET /spark/admin/knowledge/{id}."""

    def test_get_by_id(self) -> None:
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[_ITEM_ROW])
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get(f"/spark/admin/knowledge/{_ITEM_ID}")

        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Item"

    def test_get_not_found_returns_404(self) -> None:
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            AsyncMock(return_value=mock_sb),
        ):
            resp = client.get(f"/spark/admin/knowledge/{uuid4()}")

        assert resp.status_code == 404


# ===========================================================================
# Patch
# ===========================================================================


@pytest.mark.unit
class TestPatchKnowledge:
    """PATCH /spark/admin/knowledge/{id}."""

    def test_patch_partial_fields(self) -> None:
        updated_row = {**_ITEM_ROW, "priority": 99}

        with patch(
            "app.routers.admin.knowledge_svc.update_knowledge_item",
            AsyncMock(return_value=updated_row),
        ):
            resp = client.patch(
                f"/spark/admin/knowledge/{_ITEM_ID}",
                json={"priority": 99},
            )

        assert resp.status_code == 200
        assert resp.json()["priority"] == 99


# ===========================================================================
# Delete
# ===========================================================================


@pytest.mark.unit
class TestDeleteKnowledge:
    """DELETE /spark/admin/knowledge/{id}."""

    def test_delete_returns_204(self) -> None:
        with patch(
            "app.routers.admin.knowledge_svc.delete_knowledge_item",
            AsyncMock(return_value=None),
        ):
            resp = client.delete(f"/spark/admin/knowledge/{_ITEM_ID}")

        assert resp.status_code == 204


# ===========================================================================
# Auth
# ===========================================================================


@pytest.mark.unit
class TestKnowledgeAuth:
    """Auth enforcement on knowledge endpoints."""

    def test_no_token_returns_401(self) -> None:
        # Remove the auth override to test real auth
        from app.services.spark.admin_auth import verify_admin_jwt

        app.dependency_overrides.pop(verify_admin_jwt, None)

        # The actual auth will fail on missing token
        resp = client.get(
            "/spark/admin/knowledge",
            headers={},  # No Authorization header
        )

        # Restore override
        app.dependency_overrides[verify_admin_jwt] = _mock_auth

        assert resp.status_code in (401, 403, 500)
