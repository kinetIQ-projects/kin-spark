"""Tests for dashboard metrics endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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


def _make_conv(
    *,
    days_ago: int = 0,
    turn_count: int = 5,
    outcome: str | None = None,
    sentiment: str | None = None,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    """Build a mock conversation row."""
    created = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "client_id": str(_CLIENT.id),
        "turn_count": turn_count,
        "created_at": created.isoformat(),
        "ended_at": None,
        "outcome": outcome,
        "sentiment": sentiment,
    }
    if duration_minutes is not None:
        row["ended_at"] = (created + timedelta(minutes=duration_minutes)).isoformat()
    return row


def _make_lead(*, days_ago: int = 0) -> dict[str, Any]:
    """Build a mock lead row."""
    created = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    return {
        "id": str(uuid4()),
        "client_id": str(_CLIENT.id),
        "created_at": created.isoformat(),
    }


class _FakeResult:
    """Minimal mock for supabase execute() result."""

    def __init__(self, data: list[dict[str, Any]], count: int | None = None) -> None:
        self.data = data
        self.count = count if count is not None else len(data)


def _mock_sb(
    conv_data: list[dict[str, Any]] | None = None,
    lead_data: list[dict[str, Any]] | None = None,
    conv_count: int | None = None,
    lead_count: int | None = None,
) -> MagicMock:
    """Create a mock Supabase client that returns different data per table."""
    sb = MagicMock()

    convs = conv_data or []
    leads = lead_data or []
    conv_result = _FakeResult(convs, conv_count)
    lead_result = _FakeResult(leads, lead_count)

    def _table(name: str) -> MagicMock:
        chain = MagicMock()
        if name == "spark_conversations":
            chain.select.return_value.eq.return_value.gte.return_value.limit.return_value.execute = AsyncMock(
                return_value=conv_result
            )
        elif name == "spark_leads":
            chain.select.return_value.eq.return_value.gte.return_value.limit.return_value.execute = AsyncMock(
                return_value=lead_result
            )
        return chain

    sb.table = MagicMock(side_effect=_table)
    return sb


# =============================================================================
# SUMMARY TESTS
# =============================================================================


class TestMetricsSummary:
    """Tests for GET /metrics/summary aggregation logic."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """Verify all 6 fields with realistic data."""
        from app.routers.admin import metrics_summary

        convs = [
            _make_conv(days_ago=1, turn_count=4, duration_minutes=10),
            _make_conv(days_ago=2, turn_count=6, duration_minutes=20),
            _make_conv(days_ago=3, turn_count=8),  # no ended_at
        ]
        leads = [_make_lead(days_ago=1), _make_lead(days_ago=2)]

        sb = _mock_sb(conv_data=convs, lead_data=leads)

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_summary(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert result.total_conversations == 3
        assert result.total_leads == 2
        assert abs(result.conversion_rate - 2 / 3) < 0.01
        assert result.avg_turns == 6.0  # (4+6+8)/3
        # avg_duration from 2 rows: (600 + 1200) / 2 = 900
        assert result.avg_duration_seconds == 900.0
        assert result.conversations_with_duration == 2

    @pytest.mark.asyncio
    async def test_zero_conversations(self) -> None:
        """Empty dataset returns safe defaults."""
        from app.routers.admin import metrics_summary

        sb = _mock_sb(conv_data=[], lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_summary(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert result.total_conversations == 0
        assert result.total_leads == 0
        assert result.conversion_rate == 0.0
        assert result.avg_turns == 0.0
        assert result.avg_duration_seconds is None
        assert result.conversations_with_duration == 0

    @pytest.mark.asyncio
    async def test_no_ended_at_values(self) -> None:
        """All active conversations → avg_duration is None."""
        from app.routers.admin import metrics_summary

        convs = [
            _make_conv(days_ago=1, turn_count=3),
            _make_conv(days_ago=2, turn_count=7),
        ]
        sb = _mock_sb(conv_data=convs, lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_summary(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert result.avg_duration_seconds is None
        assert result.conversations_with_duration == 0
        assert result.avg_turns == 5.0  # (3+7)/2

    @pytest.mark.asyncio
    async def test_mixed_durations(self) -> None:
        """Only rows with both timestamps are included in avg_duration."""
        from app.routers.admin import metrics_summary

        convs = [
            _make_conv(days_ago=1, turn_count=4, duration_minutes=30),
            _make_conv(days_ago=2, turn_count=6),  # no duration
            _make_conv(days_ago=3, turn_count=2, duration_minutes=10),
        ]
        sb = _mock_sb(conv_data=convs, lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_summary(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        # avg of 1800s and 600s = 1200s
        assert result.avg_duration_seconds == 1200.0
        assert result.conversations_with_duration == 2


# =============================================================================
# TIMESERIES TESTS
# =============================================================================


class TestMetricsTimeseries:
    """Tests for GET /metrics/timeseries aggregation logic."""

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """Daily buckets have correct counts."""
        from app.routers.admin import metrics_timeseries

        convs = [
            _make_conv(days_ago=0, outcome="completed", sentiment="positive"),
            _make_conv(days_ago=0, outcome="completed", sentiment="neutral"),
            _make_conv(days_ago=1, outcome="abandoned", sentiment="negative"),
        ]
        leads = [_make_lead(days_ago=0)]

        sb = _mock_sb(conv_data=convs, lead_data=leads)

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_timeseries(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert len(result.daily) == 7

        # Today's entry should have 2 conversations and 1 lead
        today_iso = datetime.now(timezone.utc).date().isoformat()
        today_point = next(d for d in result.daily if d.date == today_iso)
        assert today_point.conversations == 2
        assert today_point.leads == 1

        # Outcome distribution
        outcome_map = {o.outcome: o.count for o in result.outcomes}
        assert outcome_map["completed"] == 2
        assert outcome_map["abandoned"] == 1

        # Sentiment distribution
        sentiment_map = {s.sentiment: s.count for s in result.sentiments}
        assert sentiment_map["positive"] == 1
        assert sentiment_map["neutral"] == 1
        assert sentiment_map["negative"] == 1

    @pytest.mark.asyncio
    async def test_gap_filling(self) -> None:
        """30 days requested with data on 2 days → 30 entries with 28 zeros."""
        from app.routers.admin import metrics_timeseries

        convs = [
            _make_conv(days_ago=0),
            _make_conv(days_ago=10),
        ]
        sb = _mock_sb(conv_data=convs, lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_timeseries(
                request=MagicMock(), _rate=None, client=_CLIENT, days=30
            )

        assert len(result.daily) == 30
        non_zero = [d for d in result.daily if d.conversations > 0]
        assert len(non_zero) == 2

    @pytest.mark.asyncio
    async def test_empty_data(self) -> None:
        """No data → full range of zeros, empty distributions."""
        from app.routers.admin import metrics_timeseries

        sb = _mock_sb(conv_data=[], lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_timeseries(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert len(result.daily) == 7
        assert all(d.conversations == 0 and d.leads == 0 for d in result.daily)
        assert result.outcomes == []
        assert result.sentiments == []

    @pytest.mark.asyncio
    async def test_null_outcomes_excluded(self) -> None:
        """Rows with null outcome/sentiment don't appear in distributions."""
        from app.routers.admin import metrics_timeseries

        convs = [
            _make_conv(days_ago=0, outcome="completed", sentiment=None),
            _make_conv(days_ago=1, outcome=None, sentiment="positive"),
            _make_conv(days_ago=2, outcome=None, sentiment=None),
        ]
        sb = _mock_sb(conv_data=convs, lead_data=[])

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            result = await metrics_timeseries(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert len(result.outcomes) == 1
        assert result.outcomes[0].outcome == "completed"
        assert len(result.sentiments) == 1
        assert result.sentiments[0].sentiment == "positive"


# =============================================================================
# CLIENT ISOLATION
# =============================================================================


class TestClientIsolation:
    """Verify queries are scoped by client_id."""

    @pytest.mark.asyncio
    async def test_summary_filters_by_client(self) -> None:
        from app.routers.admin import metrics_summary

        # Track tables queried and their eq() args
        tables_queried: list[str] = []
        eq_args_per_table: dict[str, list[tuple[Any, ...]]] = {}

        def _table(name: str) -> MagicMock:
            tables_queried.append(name)
            chain = MagicMock()
            eq_args_per_table[name] = []

            original_eq = chain.select.return_value.eq

            def _track_eq(*args: Any, **kwargs: Any) -> MagicMock:
                eq_args_per_table[name].append(args)
                return original_eq(*args, **kwargs)

            chain.select.return_value.eq = _track_eq
            result = _FakeResult([], 0)
            original_eq.return_value.gte.return_value.limit.return_value.execute = (
                AsyncMock(return_value=result)
            )
            return chain

        sb = MagicMock()
        sb.table = MagicMock(side_effect=_table)

        with patch(
            "app.routers.admin.get_supabase_client",
            new_callable=AsyncMock,
            return_value=sb,
        ):
            await metrics_summary(
                request=MagicMock(), _rate=None, client=_CLIENT, days=7
            )

        assert "spark_conversations" in tables_queried
        assert "spark_leads" in tables_queried
        for table in ["spark_conversations", "spark_leads"]:
            assert any(
                args == ("client_id", str(_CLIENT.id))
                for args in eq_args_per_table[table]
            ), f"Missing client_id filter on {table}"
