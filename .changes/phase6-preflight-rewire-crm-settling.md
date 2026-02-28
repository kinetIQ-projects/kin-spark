# Phase 6: Pre-flight Rewire + CRM Integration + Settling Practice

**Date:** 2026-02-27
**Status:** Complete

## What

Three interconnected changes to how Spark handles conversations:

1. **Pre-flight rewire** — Replaced hard-coded jailbreak deflections with tactical boundary signals injected into Spark's system prompt. Spark now handles boundary situations herself instead of being short-circuited.
2. **CRM lead integration** — Leads flow to HubSpot and/or webhooks automatically after capture.
3. **Settling practice** — Structural injection at the end of every user message (recency bias) plus a private `<spark_notes>` scratchpad so Spark can think before she speaks.

## Why

- **Pre-flight**: The old "gate" mode meant Gemini never saw boundary messages — Spark couldn't learn to handle them herself. Signals mode lets her respond naturally with tactical guidance.
- **CRM**: Leads were captured in the DB but never synced anywhere. Clients need them in HubSpot or via webhook.
- **Settling**: Across all three models, Spark's orientation worked on the edges of conversations but lost force in the middle. Model gravity took over on substantive questions. The settling reminder exploits recency bias (last thing before generation), and the scratchpad warms up generation with reflective tokens instead of reactive ones.

## Backend Changes

- **`api/app/models/spark.py`** (MODIFIED) — `PreflightResult`: replaced `safe`/`rejection_tier` with `boundary_signal` (5 signal types) + `terminate` bool + `conversation_state`. Added `company_name` to `SparkLeadCreate` and `SparkLeadOut`.
- **`api/app/services/spark/preflight.py`** (REWRITTEN) — Split single classifier into two parallel Groq calls (boundary detection + conversation state) running alongside retrieval via `asyncio.gather`. Conditional history passing when `boundary_signals_fired > 0`.
- **`api/app/services/spark/settling.py`** (REWRITTEN) — `_format_boundary_signals()` maps each signal to tactical text. `build_system_prompt()` uses `format_map(defaultdict(str))` for safe template rendering. Default template switched to `kinetiq`. Added `calendly_link` support.
- **`api/app/services/spark/core.py`** (REWRITTEN) — Feature flag `SPARK_PREFLIGHT_MODE` (signals/gate). Settling reminder injected after every user message. `<spark_notes>` scratchpad: buffer during notes, strip before streaming to visitor, strip before DB storage. Leading whitespace between notes and public response stripped. Empty history messages filtered (Kimi compatibility). Fallback self-loop prevention.
- **`api/app/services/spark/crm.py`** (NEW) — `sync_lead()` orchestrates HubSpot upsert + webhook POST. 409 conflict handling for existing contacts. `crm_sync_status` tracking (pending/synced/failed).
- **`api/app/services/llm.py`** (MODIFIED) — Anthropic/Claude Haiku key resolver. Fallback won't loop to itself when primary == fallback model.
- **`api/app/config.py`** (MODIFIED) — Added `anthropic_api_key` for Claude Haiku support.
- **`api/app/routers/spark.py`** (MODIFIED) — Lead endpoint includes `company_name`, fires CRM sync as fire-and-forget task.

## Migrations

- **`006_boundary_tracking.sql`** — `boundary_signals_fired` counter on `spark_conversations`. `company_name` and `crm_sync_status` on `spark_leads`. Atomic `increment_boundary_signals` RPC function.
- **`007_update_kinetiq_orientation.sql`** — Updated KinetIQ orientation template (v2) with `{boundary_signals}` placeholder.

## Widget Changes

- **`api/static/spark/widget.js`** — Added optional company name input to lead form.

## Tests

- **`test_spark_preflight.py`** (REWRITTEN) — 23 tests: boundary detection, terminate criteria, conditional history, conversation state, retrieval, full preflight orchestration.
- **`test_settling.py`** (REWRITTEN) — 26 tests: timezone, boundary signal formatting, doc context, orientation resolution, format_map safety, calendly link.
- **`test_spark_core.py`** (REWRITTEN) — 15 tests: SSE format, wind-down, signals mode, gate mode, max turns, preflight error, orientation passthrough.
- **`test_crm.py`** (NEW) — 11 tests: name splitting, HubSpot upsert (create/409/failure/no-email), webhook (success/timeout), sync_lead orchestration.
- **Full suite: 196/196 passing.**

## Architecture Decisions

- **Feature flag for rollback** — `SPARK_PREFLIGHT_MODE=gate` restores old behavior without redeployment.
- **Settling reminder at recency position** — End of user message is the highest-leverage position in the context window. Same language as orientation so it feels like remembering, not instruction.
- **Scratchpad via output stripping** — No extra API calls or latency. Model generates notes + response in one pass. Infrastructure just buffers and strips. If Spark doesn't use the scratchpad, 50-char threshold flushes and streams normally.
- **Atomic RPC for boundary counter** — Avoids read-then-write race condition on concurrent fire-and-forget tasks.
- **`format_map(defaultdict(str))`** — Missing placeholders in user-editable orientations resolve to empty string instead of crashing.
- **Switchable primary model** — `SPARK_PRIMARY_MODEL` env var on Railway switches between Gemini 3 Flash, Kimi K2.5, and Claude Haiku without redeployment.

## Verification

- Tests: 196/196 passed
- Scythe audit: PASS
- QA: PASS
- Live testing: Settling injection confirmed working across models. Scratchpad stripping confirmed clean.
