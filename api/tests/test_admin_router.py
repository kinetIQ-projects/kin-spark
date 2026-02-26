"""Tests for admin router endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.routers.admin import _sanitize_csv


def _mock_supabase() -> MagicMock:
    """Create a MagicMock Supabase client with async .execute()."""
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute = AsyncMock()
    sb.table.return_value.insert.return_value.execute = AsyncMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = (
        AsyncMock()
    )
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute = (
        AsyncMock()
    )
    return sb


# =============================================================================
# CSV SANITIZATION
# =============================================================================


class TestCsvSanitization:
    """CSV injection protection tests."""

    def test_normal_string_unchanged(self) -> None:
        assert _sanitize_csv("hello world") == "hello world"

    def test_empty_string(self) -> None:
        assert _sanitize_csv("") == ""

    def test_equals_prefix(self) -> None:
        assert _sanitize_csv("=SUM(A1:A10)") == "'=SUM(A1:A10)"

    def test_plus_prefix(self) -> None:
        assert _sanitize_csv("+cmd('calc')") == "'+cmd('calc')"

    def test_minus_prefix(self) -> None:
        assert _sanitize_csv("-cmd('calc')") == "'-cmd('calc')"

    def test_at_prefix(self) -> None:
        assert _sanitize_csv("@SUM(A1)") == "'@SUM(A1)"

    def test_tab_prefix(self) -> None:
        assert _sanitize_csv("\tdata") == "'\tdata"

    def test_carriage_return_prefix(self) -> None:
        assert _sanitize_csv("\rdata") == "'\rdata"

    def test_number_unchanged(self) -> None:
        assert _sanitize_csv("12345") == "12345"

    def test_email_unchanged(self) -> None:
        assert _sanitize_csv("user@example.com") == "user@example.com"


# =============================================================================
# OUTCOME WIRING (session.end_session)
# =============================================================================


class TestEndSessionOutcome:
    """Verify end_session writes outcome and ended_at."""

    @pytest.mark.asyncio
    async def test_end_session_with_outcome(self) -> None:
        from app.services.spark.session import end_session

        mock_sb = _mock_supabase()

        with patch(
            "app.services.spark.session.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            conv_id = uuid4()
            await end_session(conv_id, state="completed", outcome="completed")

        call_args = mock_sb.table.return_value.update.call_args[0][0]
        assert call_args["state"] == "completed"
        assert call_args["outcome"] == "completed"
        assert "ended_at" in call_args

    @pytest.mark.asyncio
    async def test_end_session_without_outcome(self) -> None:
        from app.services.spark.session import end_session

        mock_sb = _mock_supabase()

        with patch(
            "app.services.spark.session.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            conv_id = uuid4()
            await end_session(conv_id, state="completed")

        call_args = mock_sb.table.return_value.update.call_args[0][0]
        assert call_args["state"] == "completed"
        assert "outcome" not in call_args
        assert "ended_at" in call_args

    @pytest.mark.asyncio
    async def test_end_session_terminated(self) -> None:
        from app.services.spark.session import end_session

        mock_sb = _mock_supabase()

        with patch(
            "app.services.spark.session.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            conv_id = uuid4()
            await end_session(conv_id, state="terminated", outcome="terminated")

        call_args = mock_sb.table.return_value.update.call_args[0][0]
        assert call_args["outcome"] == "terminated"


# =============================================================================
# SESSION EXPIRY → ABANDONED OUTCOME
# =============================================================================


class TestSessionExpiryOutcome:
    """Verify expired sessions get outcome='abandoned'."""

    @pytest.mark.asyncio
    async def test_expired_session_sets_abandoned(self) -> None:
        from app.services.spark.session import get_session

        expired_time = "2020-01-01T00:00:00+00:00"
        mock_row = {
            "id": str(uuid4()),
            "ip_address": "1.2.3.4",
            "expires_at": expired_time,
            "state": "active",
        }

        mock_sb = _mock_supabase()

        with patch(
            "app.services.spark.session.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ), patch(
            "app.services.spark.session.get_first_or_none",
            new_callable=AsyncMock,
            return_value=mock_row,
        ):
            result = await get_session("token-123", "1.2.3.4")

        assert result is None
        call_args = mock_sb.table.return_value.update.call_args[0][0]
        assert call_args["state"] == "expired"
        assert call_args["outcome"] == "abandoned"
        assert "ended_at" in call_args


# =============================================================================
# LEAD CAPTURE → LEAD_CAPTURED OUTCOME
# =============================================================================


class TestLeadCaptureOutcome:
    """Verify lead capture sets outcome on conversation."""

    @pytest.mark.asyncio
    async def test_lead_capture_sets_outcome(self) -> None:
        from app.models.spark import SparkClient, SparkLeadCreate
        from app.routers.spark import spark_lead

        body = SparkLeadCreate(
            conversation_id=uuid4(),
            name="Test User",
            email="test@example.com",
        )
        client = SparkClient(
            id=uuid4(),
            name="Test Co",
            slug="test",
            api_key_hash="abc",
        )

        mock_sb = _mock_supabase()

        with patch(
            "app.routers.spark.get_supabase_client",
            new_callable=AsyncMock,
            return_value=mock_sb,
        ):
            result = await spark_lead(body, client)

        assert result == {"status": "captured"}
        # Verify outcome update was called
        update_calls = mock_sb.table.return_value.update.call_args_list
        assert any(
            call[0][0].get("outcome") == "lead_captured" for call in update_calls
        )
