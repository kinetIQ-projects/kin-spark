# Lead Conversation Summary + Webhook Payload for HoneyBook

**Date:** 2026-03-06
**Type:** Feature
**Scope:** CRM integration, lead capture

## What Changed

### Conversation Summary Generation (`crm.py`)
- Added `generate_lead_summary()` — fetches full conversation history and uses
  Groq Llama (preflight model) to produce a 2-3 sentence summary of what the
  visitor discussed. Focuses on specifics (event type, date, budget, guest count)
  from a third-person business-owner perspective.
- Fail-safe: returns None on any error — lead capture never blocks on summary.

### Lead Capture Route (`spark.py`)
- `POST /spark/lead` now auto-generates a conversation summary before inserting
  the lead row. Summary is stored in the `notes` field and forwarded to CRM sync.
- If the widget already sent `notes`, those are used (no override).

### Webhook Payload Shape (`crm.py`)
- Webhook payload is now flat and clean for Zapier field mapping:
  `name`, `email`, `phone`, `company_name`, `summary`, `conversation_id`
- `notes` maps to `summary` in the webhook payload (matches HoneyBook "Project Details")
- None values are stripped from the payload to avoid null fields in Zapier.

## Why

Elaborate Events (first Spark client) needs leads flowing into HoneyBook via
Zapier webhook. HoneyBook's "Create Project" Zapier action requires: Client Name,
Client Email, and Project Details. The conversation summary fills the Project
Details field so the business owner has context about what the visitor discussed.

## Configuration

To enable for a client, set in `settling_config`:
```json
{
  "webhook_url": "https://hooks.zapier.com/hooks/catch/XXXXX/XXXXX/"
}
```

Zapier maps: `email` -> Client Email, `name` -> Client Full Name, `summary` -> Project Details.

## Tests

19/19 passed in `test_crm.py`. New tests:
- `TestGenerateLeadSummary` — happy path, empty messages, LLM failure
- `TestWebhookPayloadShape` — summary field mapping, None stripping
