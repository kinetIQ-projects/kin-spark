"""
Spark CRM Integration — Sync leads to HubSpot and/or webhooks.

Uses createOrUpdate (upsert by email) for HubSpot to avoid duplicates.
Failed syncs are logged and marked for future retry sweep.

Also provides conversation summary generation for lead capture —
produces a 2-3 sentence summary of what was discussed, stored as the
lead's notes and forwarded to CRM/webhook integrations.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """Summarize this conversation between a website visitor and a business assistant in 2-3 sentences. Focus on what the visitor is looking for, any specific details they shared (event type, date, budget, guest count, etc.), and where the conversation left off. Write from a third-person perspective as a note for the business owner. Be specific and concise — no filler.

Conversation:
{transcript}"""

_HUBSPOT_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
_WEBHOOK_TIMEOUT = 10.0


async def generate_lead_summary(conversation_id: UUID) -> str | None:
    """Generate a 2-3 sentence summary of a conversation for lead capture.

    Fetches the full message history and uses the preflight model (Groq Llama)
    for fast, cheap summarization. Returns None on failure — lead capture
    should never block on summary generation.
    """
    try:
        sb = await get_supabase_client()
        result = await (
            sb.table("spark_messages")
            .select("role, content")
            .eq("conversation_id", str(conversation_id))
            .order("created_at", desc=False)
            .execute()
        )

        messages = result.data or []
        if not messages:
            return None

        # Build readable transcript
        transcript_lines: list[str] = []
        for msg in messages:
            role = "Visitor" if msg["role"] == "user" else "Assistant"
            transcript_lines.append(f"{role}: {msg['content']}")
        transcript = "\n".join(transcript_lines)

        # Use preflight model (Groq Llama) — fast and cheap
        from app.services import llm
        from app.config import settings

        summary = await llm.complete(
            messages=[
                {
                    "role": "user",
                    "content": _SUMMARY_PROMPT.format(transcript=transcript),
                }
            ],
            model=settings.spark_preflight_model,
            temperature=0.3,
            max_tokens=200,
            timeout=10,
        )
        return summary.strip() if summary else None

    except Exception as e:
        logger.warning("Lead summary generation failed: %s", e)
        return None


def _split_name(full_name: str | None) -> tuple[str, str]:
    """Split a full name into (firstname, lastname)."""
    if not full_name:
        return ("", "")
    parts = full_name.strip().split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return (first, last)


async def _hubspot_upsert_contact(
    api_key: str,
    lead_data: dict[str, Any],
) -> None:
    """Upsert a contact in HubSpot using email as the unique identifier."""
    email = lead_data.get("email")
    if not email:
        logger.warning("HubSpot sync skipped: no email on lead")
        return

    firstname, lastname = _split_name(lead_data.get("name"))

    properties: dict[str, str] = {
        "email": email,
        "hs_lead_status": "NEW",
    }
    if firstname:
        properties["firstname"] = firstname
    if lastname:
        properties["lastname"] = lastname
    if lead_data.get("company_name"):
        properties["company"] = lead_data["company_name"]
    if lead_data.get("phone"):
        properties["phone"] = lead_data["phone"]

    payload: dict[str, Any] = {
        "properties": properties,
    }

    async with httpx.AsyncClient() as client:
        # Try create first
        resp = await client.post(
            _HUBSPOT_CONTACTS_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=_WEBHOOK_TIMEOUT,
        )

        if resp.status_code == 409:
            # Contact exists — extract ID from conflict response and update
            conflict_data = resp.json()
            existing_id = conflict_data.get("message", "").split("Existing ID: ")
            if len(existing_id) > 1:
                contact_id = existing_id[1].strip().rstrip(".")
                update_url = f"{_HUBSPOT_CONTACTS_URL}/{contact_id}"
                update_resp = await client.patch(
                    update_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=_WEBHOOK_TIMEOUT,
                )
                update_resp.raise_for_status()
                logger.info("HubSpot contact updated: %s", contact_id)
            else:
                logger.warning("HubSpot 409 but could not extract existing ID")
                resp.raise_for_status()
        else:
            resp.raise_for_status()
            logger.info("HubSpot contact created for %s", email)


async def _webhook_post(
    webhook_url: str,
    lead_data: dict[str, Any],
    conversation_id: str | None = None,
) -> None:
    """POST lead data to a configured webhook URL.

    Payload is flat and clean for Zapier field mapping:
      name, email, phone, company_name, summary, conversation_id
    """
    payload: dict[str, Any] = {
        "name": lead_data.get("name"),
        "email": lead_data.get("email"),
        "phone": lead_data.get("phone"),
        "company_name": lead_data.get("company_name"),
        "summary": lead_data.get("notes"),  # maps to HoneyBook "Project Details"
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    # Strip None values so Zapier doesn't get null fields
    payload = {k: v for k, v in payload.items() if v is not None}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            webhook_url,
            json=payload,
            timeout=_WEBHOOK_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info("Webhook POST successful: %s", webhook_url)


async def _update_sync_status(
    lead_id: UUID,
    status: str,
    error_detail: str | None = None,
) -> None:
    """Update crm_sync_status on a lead row."""
    try:
        sb = await get_supabase_client()
        update_data: dict[str, Any] = {"crm_sync_status": status}
        if error_detail:
            # Store error detail in notes or a metadata field for debugging
            logger.error("CRM sync failed for lead %s: %s", lead_id, error_detail)
        await (
            sb.table("spark_leads")
            .update(update_data)
            .eq("id", str(lead_id))
            .execute()
        )
    except Exception as e:
        logger.error("Failed to update crm_sync_status for lead %s: %s", lead_id, e)


async def sync_lead(
    client_id: UUID,
    lead_id: UUID,
    lead_data: dict[str, Any],
) -> None:
    """Sync a lead to CRM (HubSpot) and/or webhook.

    Loads client config for HubSpot key and webhook URL. Fire-and-forget
    — errors are logged and status updated, not raised.

    Args:
        client_id: The Spark client owning this lead.
        lead_id: The lead row ID for status updates.
        lead_data: Dict with email, name, phone, company_name, notes, etc.
    """
    try:
        sb = await get_supabase_client()
        client_row = (
            await sb.table("spark_clients")
            .select("settling_config")
            .eq("id", str(client_id))
            .execute()
        )

        if not client_row.data:
            logger.warning("CRM sync: client %s not found", client_id)
            await _update_sync_status(lead_id, "failed", "client not found")
            return

        config = client_row.data[0].get("settling_config", {})
        hubspot_key = config.get("hubspot_api_key")
        webhook_url = config.get("webhook_url")

        if not hubspot_key and not webhook_url:
            # No CRM configured — mark as synced (nothing to do)
            await _update_sync_status(lead_id, "synced")
            return

        errors: list[str] = []

        if hubspot_key:
            try:
                await _hubspot_upsert_contact(hubspot_key, lead_data)
            except Exception as e:
                errors.append(f"HubSpot: {e}")

        if webhook_url:
            try:
                await _webhook_post(
                    webhook_url,
                    lead_data,
                    conversation_id=lead_data.get("conversation_id"),
                )
            except Exception as e:
                errors.append(f"Webhook: {e}")

        if errors:
            await _update_sync_status(lead_id, "failed", "; ".join(errors))
        else:
            await _update_sync_status(lead_id, "synced")

    except Exception as e:
        logger.error("CRM sync_lead unexpected error: %s", e)
        await _update_sync_status(lead_id, "failed", str(e))
