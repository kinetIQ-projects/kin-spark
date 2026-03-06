# Security: Remove admin endpoints from widget API key auth

**Date:** 2026-03-06
**Type:** Security fix

## What changed

Removed 5 endpoints from `spark.py` (widget router, publishable API key auth) that should only be accessible via JWT auth:

- `GET /spark/conversations` — read all conversation transcripts
- `GET /spark/conversations/{id}/messages` — read full message history
- `GET /spark/leads` — read all captured leads (names, emails, phones)
- `POST /spark/ingest/text` — inject knowledge into knowledge base
- `POST /spark/ingest/url` — trigger server-side URL fetches + inject knowledge

## Why

These endpoints were guarded by `verify_spark_api_key` (the publishable key visible in HTML source). Anyone who viewed page source could:
- Read every conversation and lead for that client
- Poison the knowledge base with false information
- Trigger SSRF via the URL ingestion endpoint

## What remains on widget auth (by design)

- `POST /spark/chat` — chat (rate-limited, 30 RPM/IP)
- `POST /spark/lead` — submit a lead (write-only)
- `POST /spark/event` — fire analytics (write-only)

## Where admin versions live

All 5 removed endpoints already had proper JWT-protected equivalents:
- `admin.py` → conversations, leads (with filtering, pagination, export)
- `ingestion.py` → file uploads, paste items, URL ingestion, pipeline runs

No functionality was lost. The duplicate endpoints were the vulnerability.
