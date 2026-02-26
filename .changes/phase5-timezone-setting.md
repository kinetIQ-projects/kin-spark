# Phase 5: Timezone Setting

**Date:** 2026-02-26
**Status:** Complete

## What

Added client-configurable timezone setting to the Spark admin portal. Spark's time awareness in system prompts now matches the client's business location instead of being hardcoded to UTC.

## Why

Phase 4 noted "UTC date boundaries (no timezone adjustment)" as a v1 limitation. Clients in different regions need Spark to know what time it is locally — a rep saying "Good morning" at 9 PM is a presence failure.

## Backend Changes

- **`api/app/services/spark/settling.py`** (MODIFIED) — Reads `settling_config.timezone`, converts via `ZoneInfo`, formats timestamp with local abbreviation (e.g. "EST", "PST"). Falls back to UTC on invalid/missing timezone.
- **`api/app/models/admin.py`** (MODIFIED) — Added `settling_config` field to `AdminClientProfile`. New `AdminSettingsUpdate` model with optional `timezone` field.
- **`api/app/routers/admin.py`** (MODIFIED) — New `PATCH /spark/admin/settings` endpoint. Validates timezone against `zoneinfo.available_timezones()`, merges into existing `settling_config` JSONB, returns updated profile. Also exposed `settling_config` on `GET /me`.
- **`api/tests/test_settling.py`** (NEW) — 6 tests: UTC default, Eastern timezone, Pacific timezone, invalid timezone fallback, empty string fallback, timestamp format structure.

## Frontend Changes

- **`portal/src/lib/types.ts`** — Added `settling_config` to `ClientProfile`, new `SettingsUpdate` interface.
- **`portal/src/pages/Settings.tsx`** (REWRITTEN) — Replaced placeholder with timezone picker. Grouped dropdown (14 common zones at top, full IANA list via `Intl.supportedValuesOf` below). Loads current value from profile, saves via PATCH, toast feedback.

## Architecture Decisions

- **Timezone stored in `settling_config` JSONB** — No migration needed. `build_system_prompt()` already reads from this dict, so the timezone is available exactly where it's consumed.
- **PATCH merges, doesn't overwrite** — Fetch-merge-write pattern preserves all other settling_config keys (company_name, tone, etc.).
- **Double-layer validation** — PATCH endpoint rejects invalid timezones (422). Settling layer also catches invalid values at read time (defense-in-depth for manual DB edits).
- **`ZoneInfo` (stdlib)** — No new dependencies. Available since Python 3.9.

## Verification

- Tests: 110/110 passed
- TypeScript: clean
- Scythe audit: PASS
- QA: PASS
