"""
Tests for Spark CRM Integration.

Covers: HubSpot upsert (success, 409 conflict, failure), webhook post
(success, timeout), crm_sync_status updates, skip when no config.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.services.spark import crm as crm_mod

_CLIENT_ID = uuid4()
_LEAD_ID = uuid4()


# ===========================================================================
# TestSplitName
# ===========================================================================


@pytest.mark.unit
class TestSplitName:
    """Name splitting into firstname/lastname."""

    def test_full_name(self) -> None:
        assert crm_mod._split_name("John Doe") == ("John", "Doe")

    def test_single_name(self) -> None:
        assert crm_mod._split_name("John") == ("John", "")

    def test_three_part_name(self) -> None:
        assert crm_mod._split_name("John Q Doe") == ("John", "Q Doe")

    def test_none_name(self) -> None:
        assert crm_mod._split_name(None) == ("", "")

    def test_empty_string(self) -> None:
        assert crm_mod._split_name("") == ("", "")


# ===========================================================================
# TestHubSpotUpsert
# ===========================================================================


@pytest.mark.unit
class TestHubSpotUpsert:
    """HubSpot contact upsert via API."""

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        """201 Created — new contact."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await crm_mod._hubspot_upsert_contact(
                "test-api-key",
                {"email": "test@example.com", "name": "Jane Doe"},
            )

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["properties"]["email"] == "test@example.com"
        assert call_kwargs[1]["json"]["properties"]["firstname"] == "Jane"
        assert call_kwargs[1]["json"]["properties"]["lastname"] == "Doe"

    @pytest.mark.asyncio
    async def test_409_conflict_updates_existing(self) -> None:
        """409 Conflict — extract ID and update."""
        conflict_response = MagicMock()
        conflict_response.status_code = 409
        conflict_response.json.return_value = {
            "message": "Contact already exists. Existing ID: 12345"
        }

        update_response = MagicMock()
        update_response.status_code = 200
        update_response.raise_for_status = MagicMock()

        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=conflict_response)
            mock_client.patch = AsyncMock(return_value=update_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await crm_mod._hubspot_upsert_contact(
                "test-api-key",
                {"email": "test@example.com", "name": "Jane Doe"},
            )

        # Should have called patch on the existing contact
        mock_client.patch.assert_called_once()
        patch_url = mock_client.patch.call_args[0][0]
        assert "12345" in patch_url

    @pytest.mark.asyncio
    async def test_api_failure_raises(self) -> None:
        """Non-409 error raises for caller to handle."""
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=error_response,
        )

        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=error_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await crm_mod._hubspot_upsert_contact(
                    "test-api-key",
                    {"email": "test@example.com"},
                )

    @pytest.mark.asyncio
    async def test_skip_when_no_email(self) -> None:
        """No email — skip HubSpot call entirely."""
        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await crm_mod._hubspot_upsert_contact(
                "test-api-key",
                {"name": "Jane Doe"},  # no email
            )

        # httpx client should never have been used
        # (function returns early before creating the client)


# ===========================================================================
# TestWebhookPost
# ===========================================================================


@pytest.mark.unit
class TestWebhookPost:
    """Webhook POST for lead sync."""

    @pytest.mark.asyncio
    async def test_webhook_success(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await crm_mod._webhook_post(
                "https://hooks.example.com/lead",
                {"email": "test@example.com"},
                conversation_id="conv-123",
            )

        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]
        assert payload["email"] == "test@example.com"
        assert payload["conversation_id"] == "conv-123"

    @pytest.mark.asyncio
    async def test_webhook_timeout_raises(self) -> None:
        with patch("app.services.spark.crm.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.TimeoutException("timeout")
            )
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.TimeoutException):
                await crm_mod._webhook_post(
                    "https://hooks.example.com/lead",
                    {"email": "test@example.com"},
                )


# ===========================================================================
# TestSyncLead
# ===========================================================================


@pytest.mark.unit
class TestSyncLead:
    """Full sync_lead orchestration."""

    @pytest.mark.asyncio
    async def test_no_config_marks_synced(self) -> None:
        """No HubSpot key or webhook → mark as synced (nothing to do)."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=[{"settling_config": {}}]))
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=[]))
        )

        with patch.object(crm_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)):
            await crm_mod.sync_lead(
                _CLIENT_ID,
                _LEAD_ID,
                {"email": "test@example.com"},
            )

        # Should update status to "synced"
        update_calls = mock_sb.table.return_value.update.call_args_list
        assert any(
            call[0][0].get("crm_sync_status") == "synced"
            for call in update_calls
        )

    @pytest.mark.asyncio
    async def test_hubspot_failure_marks_failed(self) -> None:
        """HubSpot error → crm_sync_status = failed."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute = (
            AsyncMock(
                return_value=MagicMock(
                    data=[{"settling_config": {"hubspot_api_key": "test-key"}}]
                )
            )
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=[]))
        )

        with patch.object(crm_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(
                 crm_mod,
                 "_hubspot_upsert_contact",
                 AsyncMock(side_effect=Exception("API down")),
             ):
            await crm_mod.sync_lead(
                _CLIENT_ID,
                _LEAD_ID,
                {"email": "test@example.com"},
            )

        # Should update status to "failed"
        update_calls = mock_sb.table.return_value.update.call_args_list
        assert any(
            call[0][0].get("crm_sync_status") == "failed"
            for call in update_calls
        )

    @pytest.mark.asyncio
    async def test_webhook_only_success(self) -> None:
        """Webhook configured (no HubSpot) → sync via webhook."""
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute = (
            AsyncMock(
                return_value=MagicMock(
                    data=[
                        {
                            "settling_config": {
                                "webhook_url": "https://hooks.example.com/lead"
                            }
                        }
                    ]
                )
            )
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.execute = (
            AsyncMock(return_value=MagicMock(data=[]))
        )

        with patch.object(crm_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(crm_mod, "_webhook_post", AsyncMock()) as mock_webhook:
            await crm_mod.sync_lead(
                _CLIENT_ID,
                _LEAD_ID,
                {"email": "test@example.com"},
            )

        mock_webhook.assert_called_once()
