# Phase 4: Dashboard Metrics

**Date:** 2026-02-25
**Status:** Complete — pending deployment

## What

Added dashboard metrics endpoints and a full analytics UI to the Spark admin portal. Replaces the placeholder Dashboard page with live KPI cards, activity charts, outcome distribution, and sentiment breakdown.

## Why

Brendan's scope: "conversation counts, lead conversion rates, usage over time." All underlying data was already being collected in `spark_conversations` and `spark_leads` — this phase surfaces it.

## Backend Changes

- **`api/app/models/dashboard.py`** (NEW) — 5 Pydantic response models: `DashboardSummary`, `TimeseriesPoint`, `OutcomeBucket`, `SentimentBucket`, `DashboardTimeseries`.
- **`api/app/routers/admin.py`** (MODIFIED) — 2 new endpoints:
  - `GET /spark/admin/metrics/summary?days=` — KPI aggregates (totals, conversion rate, avg turns, avg duration with sample size).
  - `GET /spark/admin/metrics/timeseries?days=` — Daily activity buckets (gap-filled), outcome distribution, sentiment distribution.
  - Both use `asyncio.gather` for parallel DB queries, `count="exact"` for accurate totals, and truncation detection at 10k rows.
- **`api/tests/test_dashboard.py`** (NEW) — 9 tests covering: happy path, zero data, null durations, mixed durations, gap filling, null outcome/sentiment exclusion, client isolation.

## Frontend Changes

- **`recharts`** added as dependency (~130KB gzipped).
- **`portal/src/lib/types.ts`** — 6 new interfaces + `DateRange` type.
- **5 new components** in `portal/src/components/dashboard/`:
  - `KpiCards.tsx` — 5-card grid with skeleton loading.
  - `DateRangeSelector.tsx` — 7/30/90 day toggle.
  - `ConversationsChart.tsx` — Composed bar+line chart for daily activity.
  - `OutcomeChart.tsx` — Donut chart for outcome distribution.
  - `SentimentChart.tsx` — Horizontal bar chart for sentiment.
- **`portal/src/pages/Dashboard.tsx`** (REWRITTEN) — Full metrics page with two independent `useQuery` calls, loading/error/empty states.

## Architecture Decisions

- **Application-level aggregation** — PostgREST doesn't support GROUP BY/AVG. Fetch columns and aggregate in Python. Swap to Postgres RPC if scale demands it.
- **`days` parameter, not date range** — Simpler for dashboard presets. Clamped 1–90.
- **UTC date boundaries (v1)** — Conscious tradeoff documented in code. Timezone-aware is Phase 5.
- **`conversations_with_duration`** included for transparency on sample size.
- **Two endpoints, not one** — Cards render immediately while charts load. Independent cache/refetch via Tanstack Query.

## v1 Limitations

1. UTC date boundaries (no timezone adjustment)
2. Flat distributions (not trended over time)
3. No period-over-period comparison on cards
4. 10k row ceiling (detected and logged, not silent)

## Verification

- Tests: 83/83 passed
- Black: clean
- Mypy (new models): clean
- Bandit: no new issues
- TypeScript: clean
- Vite build: successful
- Scythe audit: PASS
- QA: PASS
