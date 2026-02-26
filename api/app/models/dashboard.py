"""
Dashboard Models — Pydantic response models for metrics endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel

# =============================================================================
# SUMMARY (KPI CARDS)
# =============================================================================


class DashboardSummary(BaseModel):
    """Aggregate KPIs for the dashboard summary cards."""

    total_conversations: int
    total_leads: int
    conversion_rate: float  # leads / conversations, 0.0–1.0
    avg_turns: float
    avg_duration_seconds: float | None  # None when no conversations have ended_at
    conversations_with_duration: int  # sample size for avg_duration


# =============================================================================
# TIMESERIES (CHARTS)
# =============================================================================


class TimeseriesPoint(BaseModel):
    """Single day in the daily activity chart."""

    date: str  # YYYY-MM-DD
    conversations: int
    leads: int


class OutcomeBucket(BaseModel):
    """Outcome distribution for the donut chart."""

    outcome: str
    count: int


class SentimentBucket(BaseModel):
    """Sentiment distribution for the bar chart."""

    sentiment: str
    count: int


class DashboardTimeseries(BaseModel):
    """Full timeseries response: daily activity + distributions."""

    daily: list[TimeseriesPoint]
    outcomes: list[OutcomeBucket]
    sentiments: list[SentimentBucket]
