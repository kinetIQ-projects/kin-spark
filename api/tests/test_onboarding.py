"""Tests for onboarding questionnaire CRUD endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.admin import OnboardingUpdate, OrientationUpdate
from app.models.spark import SparkClient


# =============================================================================
# HELPERS
# =============================================================================

_CLIENT = SparkClient(
    id=uuid4(),
    name="Test Co",
    slug="test",
    api_key_hash="abc",
)


class _FakeResult:
    """Minimal mock for supabase execute() result."""

    def __init__(self, data: list[dict[str, Any]], count: int | None = None) -> None:
        self.data = data
        self.count = count if count is not None else len(data)


def _mock_sb_select(data: list[dict[str, Any]]) -> MagicMock:
    """Create a mock Supabase client that returns data for a .select() chain."""
    sb = MagicMock()
    result = _FakeResult(data)
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = (
        AsyncMock(return_value=result)
    )
    return sb


def _mock_sb_select_and_update(
    select_data: list[dict[str, Any]],
    update_data: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Mock Supabase client for endpoints that read then write.

    select chain:  .table().select().eq().limit().execute()
    update chain:  .table().update().eq().execute()
    """
    sb = MagicMock()
    select_result = _FakeResult(select_data)
    update_result = _FakeResult(update_data or [])

    call_count = {"n": 0}

    def _table(name: str) -> MagicMock:
        chain = MagicMock()
        call_count["n"] += 1
        # First call is the select, second is the update
        if call_count["n"] == 1:
            chain.select.return_value.eq.return_value.limit.return_value.execute = (
                AsyncMock(return_value=select_result)
            )
        else:
            chain.update.return_value.eq.return_value.execute = AsyncMock(
                return_value=update_result
            )
        return chain

    sb.table = MagicMock(side_effect=_table)
    return sb


def _mock_sb_update(update_data: list[dict[str, Any]]) -> MagicMock:
    """Mock Supabase client for endpoints that only write."""
    sb = MagicMock()
    result = _FakeResult(update_data)
    sb.table.return_value.update.return_value.eq.return_value.execute = AsyncMock(
        return_value=result
    )
    return sb


# =============================================================================
# GET /onboarding
# =============================================================================


class TestGetOnboarding:
    """Tests for GET /spark/admin/onboarding."""

    @pytest.mark.asyncio
    async def test_get_onboarding_empty(self) -> None:
        """GET returns empty dict for new client."""
        from app.routers.admin import get_onboarding

        sb = _mock_sb_select([{"onboarding_data": {}}])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_onboarding(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result == {"onboarding_data": {}}

    @pytest.mark.asyncio
    async def test_get_onboarding_with_data(self) -> None:
        """GET returns existing questionnaire data."""
        from app.routers.admin import get_onboarding

        existing = {
            "purpose_story": {"mission": "Help people"},
            "last_saved_at": "2026-01-15T10:00:00+00:00",
        }
        sb = _mock_sb_select([{"onboarding_data": existing}])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_onboarding(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result == {"onboarding_data": existing}

    @pytest.mark.asyncio
    async def test_get_onboarding_null_returns_empty(self) -> None:
        """GET returns empty dict when onboarding_data is null."""
        from app.routers.admin import get_onboarding

        sb = _mock_sb_select([{"onboarding_data": None}])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_onboarding(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result == {"onboarding_data": {}}


# =============================================================================
# PATCH /onboarding
# =============================================================================


class TestPatchOnboarding:
    """Tests for PATCH /spark/admin/onboarding."""

    @pytest.mark.asyncio
    async def test_patch_onboarding_partial(self) -> None:
        """PATCH with one section updates only that section."""
        from app.routers.admin import update_onboarding

        sb = _mock_sb_select_and_update(
            select_data=[{"onboarding_data": {}}],
            update_data=[{"onboarding_data": {}}],
        )

        body = OnboardingUpdate(purpose_story={"mission": "Help people"})

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await update_onboarding(
                body=body, request=MagicMock(), _rate=None, client=_CLIENT
            )

        data = result["onboarding_data"]
        assert data["purpose_story"] == {"mission": "Help people"}
        assert "last_saved_at" in data

    @pytest.mark.asyncio
    async def test_patch_onboarding_full(self) -> None:
        """PATCH with all sections updates everything."""
        from app.routers.admin import update_onboarding

        sb = _mock_sb_select_and_update(
            select_data=[{"onboarding_data": {}}],
            update_data=[{"onboarding_data": {}}],
        )

        body = OnboardingUpdate(
            purpose_story={"mission": "Help people"},
            values_culture={"tone": "Friendly"},
            brand_voice={"style": "casual", "examples": ["Hey!", "Sure thing"]},
            customers=[],
            procedures_policies={"returns": "30 days"},
            additional_context="We are a small team.",
            completed_at="2026-01-15T10:00:00+00:00",
        )

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await update_onboarding(
                body=body, request=MagicMock(), _rate=None, client=_CLIENT
            )

        data = result["onboarding_data"]
        assert data["purpose_story"] == {"mission": "Help people"}
        assert data["values_culture"] == {"tone": "Friendly"}
        assert data["brand_voice"] == {"style": "casual", "examples": ["Hey!", "Sure thing"]}
        assert data["customers"] == []
        assert data["procedures_policies"] == {"returns": "30 days"}
        assert data["additional_context"] == "We are a small team."
        assert data["completed_at"] == "2026-01-15T10:00:00+00:00"

    @pytest.mark.asyncio
    async def test_patch_onboarding_merge(self) -> None:
        """PATCH preserves existing sections not in update."""
        from app.routers.admin import update_onboarding

        existing = {
            "purpose_story": {"mission": "Help people"},
            "values_culture": {"tone": "Friendly"},
            "last_saved_at": "2026-01-14T10:00:00+00:00",
        }
        sb = _mock_sb_select_and_update(
            select_data=[{"onboarding_data": existing}],
            update_data=[{"onboarding_data": {}}],
        )

        # Only update brand_voice — purpose_story and values_culture should survive
        body = OnboardingUpdate(brand_voice={"style": "professional"})

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await update_onboarding(
                body=body, request=MagicMock(), _rate=None, client=_CLIENT
            )

        data = result["onboarding_data"]
        assert data["purpose_story"] == {"mission": "Help people"}
        assert data["values_culture"] == {"tone": "Friendly"}
        assert data["brand_voice"] == {"style": "professional"}

    @pytest.mark.asyncio
    async def test_patch_onboarding_sets_timestamp(self) -> None:
        """PATCH sets last_saved_at to a valid ISO timestamp."""
        from app.routers.admin import update_onboarding

        sb = _mock_sb_select_and_update(
            select_data=[{"onboarding_data": {}}],
            update_data=[{"onboarding_data": {}}],
        )

        body = OnboardingUpdate(purpose_story={"mission": "Test"})

        before = datetime.now(timezone.utc)

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await update_onboarding(
                body=body, request=MagicMock(), _rate=None, client=_CLIENT
            )

        after = datetime.now(timezone.utc)

        saved_at = datetime.fromisoformat(result["onboarding_data"]["last_saved_at"])
        assert before <= saved_at <= after

    def test_patch_onboarding_additional_context_max_length(self) -> None:
        """additional_context over 5000 chars triggers validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OnboardingUpdate(additional_context="x" * 5001)

    def test_patch_onboarding_additional_context_at_limit(self) -> None:
        """additional_context at exactly 5000 chars is accepted."""
        body = OnboardingUpdate(additional_context="x" * 5000)
        assert body.additional_context == "x" * 5000


# =============================================================================
# GET /orientation
# =============================================================================


class TestGetOrientation:
    """Tests for GET /spark/admin/orientation."""

    @pytest.mark.asyncio
    async def test_get_orientation_null(self) -> None:
        """GET returns null when orientation not set."""
        from app.routers.admin import get_orientation

        sb = _mock_sb_select([{
            "client_orientation": None,
            "settling_config": {},
        }])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_orientation(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result.orientation is None
        assert result.template_name == "core"

    @pytest.mark.asyncio
    async def test_get_orientation_with_value(self) -> None:
        """GET returns orientation text and template name."""
        from app.routers.admin import get_orientation

        sb = _mock_sb_select([{
            "client_orientation": "You are a helpful assistant for a bakery.",
            "settling_config": {"orientation_template": "custom"},
        }])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_orientation(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result.orientation == "You are a helpful assistant for a bakery."
        assert result.template_name == "custom"

    @pytest.mark.asyncio
    async def test_get_orientation_default_template(self) -> None:
        """GET defaults to 'core' when no template in settling_config."""
        from app.routers.admin import get_orientation

        sb = _mock_sb_select([{
            "client_orientation": "Some text",
            "settling_config": None,
        }])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await get_orientation(
                request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result.template_name == "core"


# =============================================================================
# PUT /orientation
# =============================================================================


class TestSetOrientation:
    """Tests for PUT /spark/admin/orientation."""

    @pytest.mark.asyncio
    async def test_put_orientation(self) -> None:
        """PUT sets orientation text and returns it."""
        from app.routers.admin import set_orientation

        sb = _mock_sb_update([{
            "client_orientation": "New orientation text",
            "settling_config": {"orientation_template": "custom"},
        }])

        body = OrientationUpdate(orientation="New orientation text")

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await set_orientation(
                body=body, request=MagicMock(), _rate=None, client=_CLIENT
            )

        assert result.orientation == "New orientation text"
        assert result.template_name == "custom"

    def test_put_orientation_max_length(self) -> None:
        """orientation over 20000 chars triggers validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OrientationUpdate(orientation="x" * 20001)

    def test_put_orientation_at_limit(self) -> None:
        """orientation at exactly 20000 chars is accepted."""
        body = OrientationUpdate(orientation="x" * 20000)
        assert len(body.orientation) == 20000

    def test_put_orientation_required(self) -> None:
        """orientation is required — empty body triggers validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OrientationUpdate()  # type: ignore[call-arg]
