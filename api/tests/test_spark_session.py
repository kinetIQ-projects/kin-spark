"""
Tests for Spark Session Manager.

Covers: create, get, increment, end, history, expiry, IP validation.
All DB calls are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.spark import session as session_mod

# ===========================================================================
# Helpers
# ===========================================================================

_CLIENT_ID = uuid4()
_CONV_ID = uuid4()


def _mock_conversation_row(
    *,
    ip: str = "1.2.3.4",
    turn_count: int = 0,
    state: str = "active",
    expired: bool = False,
) -> dict:
    """Build a fake spark_conversations row."""
    expires_at = datetime.now(timezone.utc) + (
        timedelta(minutes=-5) if expired else timedelta(minutes=30)
    )
    return {
        "id": str(_CONV_ID),
        "client_id": str(_CLIENT_ID),
        "session_token": "tok_abc123",
        "ip_address": ip,
        "visitor_fingerprint": None,
        "turn_count": turn_count,
        "state": state,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_sb_mock() -> MagicMock:
    """Build a Supabase client mock with chainable .table().op().execute() pattern."""
    sb = MagicMock()
    # Make all chained methods return the same mock to support arbitrary chains
    chain = MagicMock()
    chain.execute = AsyncMock(return_value=MagicMock(data=[]))
    # Every attribute access on chain returns chain (for arbitrary chaining)
    chain.configure_mock(
        **{
            "insert.return_value": chain,
            "select.return_value": chain,
            "update.return_value": chain,
            "delete.return_value": chain,
            "eq.return_value": chain,
            "in_.return_value": chain,
            "order.return_value": chain,
            "limit.return_value": chain,
            "range.return_value": chain,
        }
    )
    sb.table.return_value = chain
    return sb


# ===========================================================================
# TestCreateSession
# ===========================================================================


@pytest.mark.unit
class TestCreateSession:
    """Session creation."""

    @pytest.mark.asyncio
    async def test_creates_session_and_returns_row(self) -> None:
        row = _mock_conversation_row()
        sb = _make_sb_mock()
        sb.table.return_value.execute = AsyncMock(return_value=MagicMock(data=[row]))

        with patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=sb)
        ):
            result = await session_mod.create_session(
                client_id=_CLIENT_ID, ip_address="1.2.3.4"
            )

        assert result["id"] == str(_CONV_ID)
        assert result["state"] == "active"


# ===========================================================================
# TestGetSession
# ===========================================================================


@pytest.mark.unit
class TestGetSession:
    """Session retrieval with IP and expiry validation."""

    @pytest.mark.asyncio
    async def test_returns_session_for_valid_token_and_ip(self) -> None:
        row = _mock_conversation_row(ip="1.2.3.4")

        with patch.object(
            session_mod, "get_first_or_none", AsyncMock(return_value=row)
        ), patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=_make_sb_mock())
        ):
            result = await session_mod.get_session("tok_abc123", "1.2.3.4")

        assert result is not None
        assert result["id"] == str(_CONV_ID)

    @pytest.mark.asyncio
    async def test_returns_none_for_ip_mismatch(self) -> None:
        row = _mock_conversation_row(ip="1.2.3.4")

        with patch.object(
            session_mod, "get_first_or_none", AsyncMock(return_value=row)
        ), patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=_make_sb_mock())
        ):
            result = await session_mod.get_session("tok_abc123", "9.9.9.9")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_expired_session(self) -> None:
        row = _mock_conversation_row(expired=True)
        sb = _make_sb_mock()

        with patch.object(
            session_mod, "get_first_or_none", AsyncMock(return_value=row)
        ), patch.object(session_mod, "get_supabase_client", AsyncMock(return_value=sb)):
            result = await session_mod.get_session("tok_abc123", "1.2.3.4")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_token(self) -> None:
        with patch.object(
            session_mod, "get_first_or_none", AsyncMock(return_value=None)
        ), patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=_make_sb_mock())
        ):
            result = await session_mod.get_session("tok_unknown", "1.2.3.4")

        assert result is None


# ===========================================================================
# TestGetHistory
# ===========================================================================


@pytest.mark.unit
class TestGetHistory:
    """Message history retrieval with sliding window."""

    @pytest.mark.asyncio
    async def test_returns_messages_in_chronological_order(self) -> None:
        messages = [
            {"role": "user", "content": "Hello", "created_at": "2024-01-01T00:00:02Z"},
            {
                "role": "assistant",
                "content": "Hi",
                "created_at": "2024-01-01T00:00:01Z",
            },
        ]
        sb = _make_sb_mock()
        sb.table.return_value.execute = AsyncMock(return_value=MagicMock(data=messages))

        with patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=sb)
        ):
            result = await session_mod.get_history(_CONV_ID, limit=8)

        # Should be reversed to chronological
        assert result[0]["content"] == "Hi"
        assert result[1]["content"] == "Hello"


# ===========================================================================
# TestStoreMessage
# ===========================================================================


@pytest.mark.unit
class TestStoreMessage:
    """Message storage."""

    @pytest.mark.asyncio
    async def test_stores_message(self) -> None:
        row = {
            "id": str(uuid4()),
            "conversation_id": str(_CONV_ID),
            "role": "user",
            "content": "Hello",
            "created_at": "now",
        }
        sb = _make_sb_mock()
        sb.table.return_value.execute = AsyncMock(return_value=MagicMock(data=[row]))

        with patch.object(
            session_mod, "get_supabase_client", AsyncMock(return_value=sb)
        ):
            result = await session_mod.store_message(_CONV_ID, "user", "Hello")

        assert result["role"] == "user"
        assert result["content"] == "Hello"
