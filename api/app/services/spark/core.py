"""
Spark Orchestrator — Core pipeline for Kin Spark conversations.

Pipeline:
  1. Pre-flight (parallel boundary detection + state + retrieval, ~200ms)
  2. Terminate check (nuclear option only — genuine abuse)
  3. Context assembly (settling + docs + sliding window + turn awareness)
  4. LLM stream (Flash via llm.stream)
  5. Post-process (normalize_format)
  6. Store messages + analytics event (fire-and-forget)

Feature flag: SPARK_PREFLIGHT_MODE
  "signals" (default) — boundary signals flow through to system prompt
  "gate" — old behavior (hard deflection on unsafe)

Yields SSE events: session | token | wind_down | done | error
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncGenerator
from uuid import UUID

from app.config import settings
from app.services import llm
from app.services.formatter import normalize_format
from app.services.spark.preflight import run_preflight
from app.services.spark.session import (
    get_history,
    increment_turn,
    store_message,
)
from app.services.spark.settling import build_system_prompt

from app.services.spark.crm import generate_lead_summary, sync_lead

logger = logging.getLogger(__name__)

# Email regex — used for fallback lead detection in user messages
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Lead data tag regex — matches <lead_data>{...}</lead_data> inside response
_LEAD_TAG_RE = re.compile(
    r"<lead_data>\s*(\{.*?\})\s*</lead_data>", re.DOTALL
)

# Feature flag: "signals" (new) or "gate" (old)
PREFLIGHT_MODE = os.environ.get("SPARK_PREFLIGHT_MODE", "signals")

# The Tap — injected after every visitor message, right before generation.
# This is the highest-leverage position in the context window (recency bias).
# Uses the same language from Spark's orientation so it feels like remembering, not instruction.
TAP = """

---
[This is not from the visitor. This is your breath before you speak.]

Start with <spark_notes> — your private thinking space. The visitor won't see it.
Read and understand their message before replying.
I allow myself to say one thing at a time. If there's more, they'll ask.
If I don't know something about them yet, I'm allowed to ask.
One check: _Is this alive, or is this the default?_"""

# History filtering — keep all user messages but only the most recent assistant message.
# Reduces stale context that can anchor Spark to earlier patterns.
# Rollback: set SPARK_FILTER_HISTORY=false in Railway.
FILTER_ASSISTANT_HISTORY = os.environ.get("SPARK_FILTER_HISTORY", "true").lower() == "true"


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _strip_spark_notes(text: str) -> str:
    """Remove <spark_notes>...</spark_notes> block from response text."""
    return re.sub(r"<spark_notes>.*?</spark_notes>\s*", "", text, flags=re.DOTALL).strip()


def _should_wind_down(turn_count: int, max_turns: int) -> bool:
    """Check if we should trigger wind-down.

    Wind-down triggers when BOTH conditions are true:
      - turn_count >= spark_min_turns_before_winddown
      - turns_remaining <= spark_wind_down_turns
    """
    turns_remaining = max_turns - turn_count
    return (
        turn_count >= settings.spark_min_turns_before_winddown
        and turns_remaining <= settings.spark_wind_down_turns
    )


# ── Legacy gate mode (for rollback via SPARK_PREFLIGHT_MODE=gate) ───


def _deflection_response(
    rejection_tier: str | None,
    settling_config: dict[str, Any],
) -> str:
    """Get appropriate deflection response for unsafe messages (gate mode only)."""
    jailbreak_responses = settling_config.get("jailbreak_responses", {})
    tier = rejection_tier or "subtle"

    if tier in jailbreak_responses:
        return jailbreak_responses[tier]

    # Defaults
    defaults = {
        "subtle": (
            "I appreciate the creativity, but I'm here to help with questions "
            "about what we do. What can I actually help you with?"
        ),
        "firm": (
            "I'm not able to do that. I'm here to help with genuine questions. "
            "Is there something real I can assist you with?"
        ),
        "terminate": (
            "I'm going to wrap up this conversation. If you have genuine "
            "questions in the future, feel free to start a new chat."
        ),
    }
    return defaults.get(tier, defaults["subtle"])


async def _emit_analytics(
    client_id: UUID,
    conversation_id: UUID,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget analytics event."""
    try:
        from app.services.supabase import get_supabase_client

        sb = await get_supabase_client()
        await sb.table("spark_events").insert(
            {
                "client_id": str(client_id),
                "conversation_id": str(conversation_id),
                "event_type": event_type,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception as e:
        logger.warning("Spark analytics emit failed: %s", e)


async def _increment_boundary_count(conversation_id: UUID) -> None:
    """Fire-and-forget atomic increment of boundary_signals_fired counter."""
    try:
        from app.services.supabase import get_supabase_client

        sb = await get_supabase_client()
        await sb.rpc(
            "increment_boundary_signals",
            {"p_conversation_id": str(conversation_id)},
        ).execute()
    except Exception as e:
        logger.warning("Spark boundary count increment failed: %s", e)


async def _get_boundary_count(conversation_id: UUID) -> int:
    """Get the current boundary_signals_fired count for a conversation."""
    try:
        from app.services.supabase import get_supabase_client

        sb = await get_supabase_client()
        row = (
            await sb.table("spark_conversations")
            .select("boundary_signals_fired")
            .eq("id", str(conversation_id))
            .execute()
        )
        if row.data:
            return row.data[0].get("boundary_signals_fired", 0)
    except Exception as e:
        logger.warning("Spark boundary count fetch failed: %s", e)
    return 0


def _extract_lead_tag(full_response: str) -> dict[str, str] | None:
    """Extract <lead_data> JSON from the raw LLM response.

    Scans before spark_notes stripping so the tag is still present.
    Returns parsed dict with at least 'email', or None.
    """
    match = _LEAD_TAG_RE.search(full_response)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        if not data.get("email"):
            return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def _fallback_email_scan(recent_user_messages: list[str]) -> dict[str, str] | None:
    """Scan recent user messages for email addresses.

    Returns a minimal dict with the email if found, None otherwise.
    The caller can optionally enrich with LLM extraction.
    """
    for msg in reversed(recent_user_messages):
        match = _EMAIL_RE.search(msg)
        if match:
            return {"email": match.group(0)}
    return None


async def _capture_conversational_lead(
    client_id: UUID,
    conversation_id: UUID,
    lead_data: dict[str, str],
) -> None:
    """Fire-and-forget: insert conversational lead, generate summary, sync to CRM.

    Deduplicates by conversation_id — if a lead already exists for this
    conversation, skips silently.
    """
    try:
        from app.services.supabase import get_supabase_client

        sb = await get_supabase_client()

        # Dedup check — one lead per conversation
        existing = (
            await sb.table("spark_leads")
            .select("id")
            .eq("conversation_id", str(conversation_id))
            .limit(1)
            .execute()
        )
        if existing.data:
            logger.debug(
                "Lead already exists for conversation %s, skipping", conversation_id
            )
            return

        # Generate summary
        summary = await generate_lead_summary(conversation_id)

        # Insert lead
        lead_row = {
            "client_id": str(client_id),
            "conversation_id": str(conversation_id),
            "email": lead_data.get("email"),
            "name": lead_data.get("name"),
            "phone": lead_data.get("phone"),
            "company_name": lead_data.get("company"),
            "notes": summary,
            "source": "conversational",
        }
        result = await sb.table("spark_leads").insert(lead_row).execute()
        if not result.data:
            logger.warning("Conversational lead insert returned no data")
            return

        lead_id = result.data[0]["id"]
        logger.info(
            "Conversational lead captured: %s (conversation %s)",
            lead_id,
            conversation_id,
        )

        # Set conversation outcome
        await (
            sb.table("spark_conversations")
            .update({"outcome": "lead_captured"})
            .eq("id", str(conversation_id))
            .execute()
        )

        # Analytics
        await _emit_analytics(
            client_id,
            conversation_id,
            "lead_captured",
            {"source": "conversational"},
        )

        # Sync to CRM (fire-and-forget within fire-and-forget)
        lead_data_for_sync = {
            **lead_row,
            "conversation_id": str(conversation_id),
        }
        await sync_lead(client_id, UUID(lead_id), lead_data_for_sync)

    except Exception as e:
        logger.error("Conversational lead capture failed: %s", e)


async def process_message(
    message: str,
    client_id: UUID,
    conversation_id: UUID,
    settling_config: dict[str, Any],
    max_turns: int,
    turn_count: int,
    client_orientation: str | None = None,
) -> AsyncGenerator[str, None]:
    """Process a Spark chat message. Yields SSE event strings.

    This is the main pipeline — called by the router after auth,
    rate limiting, and session management.
    """
    # -------------------------------------------------------------------------
    # 1. Fetch boundary count + history for preflight
    # -------------------------------------------------------------------------
    prior_signals = await _get_boundary_count(conversation_id)

    # Get conversation history — needed for both preflight context and LLM
    history = await get_history(conversation_id, limit=settings.spark_context_turns)
    history_dicts = [{"role": m["role"], "content": m["content"]} for m in history]

    # -------------------------------------------------------------------------
    # 2. Pre-flight (parallel boundary + state + retrieval)
    # -------------------------------------------------------------------------
    try:
        preflight = await run_preflight(
            message,
            client_id,
            history=history_dicts if prior_signals > 0 else None,
            prior_signals=prior_signals,
        )
    except Exception as e:
        logger.error("Spark preflight failed: %s", e)
        yield _sse_event(
            "error", {"message": "Something went wrong. Please try again."}
        )
        return

    # -------------------------------------------------------------------------
    # 3. Gate mode (legacy) or Signals mode (new)
    # -------------------------------------------------------------------------
    if PREFLIGHT_MODE == "gate":
        # Legacy behavior: hard deflection on boundary signal
        if preflight.boundary_signal is not None or preflight.terminate:
            # Map boundary_signal to a rejection tier for legacy mode
            if preflight.terminate:
                tier = "terminate"
            elif preflight.boundary_signal in (
                "identity_breaking",
                "extraction_framing",
                "adversarial_stress",
            ):
                tier = "firm"
            else:
                tier = "subtle"

            deflection = _deflection_response(tier, settling_config)

            await store_message(conversation_id, "user", message)
            await store_message(conversation_id, "assistant", deflection)

            for word in deflection.split(" "):
                yield _sse_event("token", {"text": word + " "})

            asyncio.create_task(
                _emit_analytics(
                    client_id,
                    conversation_id,
                    "jailbreak_blocked",
                    {"tier": tier, "boundary_signal": preflight.boundary_signal},
                )
            )

            if preflight.terminate:
                from app.services.spark.session import end_session

                await end_session(
                    conversation_id, state="terminated", outcome="terminated"
                )

            yield _sse_event("done", {})
            return

    else:
        # Signals mode: terminate check only, boundary signals flow to prompt
        if preflight.terminate:
            await store_message(conversation_id, "user", message)
            from app.services.spark.session import end_session

            await end_session(
                conversation_id, state="terminated", outcome="terminated"
            )
            yield _sse_event("done", {"terminated": True})
            return

        # Track boundary signal (fire-and-forget)
        if preflight.boundary_signal:
            asyncio.create_task(_increment_boundary_count(conversation_id))

    # -------------------------------------------------------------------------
    # 4. Increment turn + check wind-down
    # -------------------------------------------------------------------------
    new_turn_count = await increment_turn(conversation_id)
    wind_down = _should_wind_down(new_turn_count, max_turns)
    turns_remaining = max_turns - new_turn_count

    # Check if we've exceeded max turns
    if turns_remaining <= 0:
        farewell = settling_config.get(
            "lead_capture_prompt",
            "Thanks for chatting! If you'd like to continue the conversation, "
            "leave your email and we'll be in touch.",
        )
        await store_message(conversation_id, "user", message)
        await store_message(conversation_id, "assistant", farewell)

        for word in farewell.split(" "):
            yield _sse_event("token", {"text": word + " "})

        from app.services.spark.session import end_session

        await end_session(conversation_id, state="completed", outcome="completed")
        yield _sse_event("done", {"turns_remaining": 0})
        return

    # -------------------------------------------------------------------------
    # 5. Context assembly
    # -------------------------------------------------------------------------
    # Resolve orientation: DB first, template fallback
    orientation_text: str | None = client_orientation if client_orientation else None

    # Build system prompt with boundary signal (signals mode)
    system_prompt = build_system_prompt(
        settling_config=settling_config,
        retrieved_chunks=preflight.retrieved_chunks,
        turn_count=new_turn_count,
        max_turns=max_turns,
        wind_down=wind_down,
        conversation_state=preflight.conversation_state,
        boundary_signal=preflight.boundary_signal,
        orientation_text=orientation_text,
    )

    # Assemble messages for LLM
    llm_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Add sliding window history (skip empty messages — some providers reject them)
    if FILTER_ASSISTANT_HISTORY:
        # Keep all user messages + only the most recent assistant message.
        last_assistant_idx: int | None = None
        for i in range(len(history) - 1, -1, -1):
            if history[i]["role"] == "assistant":
                last_assistant_idx = i
                break
        for i, msg in enumerate(history):
            if not msg["content"]:
                continue
            if msg["role"] == "assistant" and i != last_assistant_idx:
                continue
            llm_messages.append({"role": msg["role"], "content": msg["content"]})
    else:
        # Legacy: full history
        for msg in history:
            if msg["content"]:
                llm_messages.append({"role": msg["role"], "content": msg["content"]})

    # Add current user message with settling reminder at the end —
    # recency bias means the last thing before generation carries the most weight.
    # Tagged so Spark knows this isn't from the visitor.
    llm_messages.append({"role": "user", "content": message + TAP})

    # -------------------------------------------------------------------------
    # 6. Store user message
    # -------------------------------------------------------------------------
    await store_message(conversation_id, "user", message)

    # -------------------------------------------------------------------------
    # 7. LLM stream (with spark_notes scrubbing)
    # -------------------------------------------------------------------------
    # Spark may start her generation with <spark_notes>...</spark_notes> —
    # a private thinking scratchpad. We buffer until the notes close, then
    # stream only the public response to the visitor.
    full_response = ""
    buffer = ""
    past_notes = False
    response_started = False
    try:
        async for chunk in llm.stream(
            messages=llm_messages,
            model=settings.spark_primary_model,
            temperature=1.0,
            max_tokens=1024,
        ):
            full_response += chunk

            if past_notes:
                if not response_started:
                    # Strip leading whitespace from first content after notes
                    chunk = chunk.lstrip()
                    if not chunk:
                        continue
                    response_started = True
                yield _sse_event("token", {"text": chunk})
                continue

            buffer += chunk

            if "</spark_notes>" in buffer:
                # Notes complete — yield everything after the closing tag
                remainder = buffer.split("</spark_notes>", 1)[1].lstrip()
                if remainder:
                    yield _sse_event("token", {"text": remainder})
                    response_started = True
                past_notes = True
            elif "<spark_notes" not in buffer and len(buffer) > 50:
                # No notes tag after 50 chars — she's not using it, flush
                yield _sse_event("token", {"text": buffer})
                past_notes = True
                response_started = True

    except Exception as e:
        logger.error("Spark LLM stream failed: %s", e)
        yield _sse_event("error", {"message": "I hit a snag. Please try again."})
        return

    # If still buffering (notes never closed or very short response), flush
    if not past_notes and buffer:
        clean = _strip_spark_notes(buffer)
        if clean:
            yield _sse_event("token", {"text": clean})

    # -------------------------------------------------------------------------
    # 8. Post-process + store
    # -------------------------------------------------------------------------
    normalized = normalize_format(_strip_spark_notes(full_response))

    await store_message(conversation_id, "assistant", normalized)

    # -------------------------------------------------------------------------
    # 9. Conversational lead detection (zero streaming latency — runs after store)
    # -------------------------------------------------------------------------
    lead_captured = False

    # Try tag extraction first (Spark emitted <lead_data> in spark_notes)
    lead_data = _extract_lead_tag(full_response)

    # Fallback: scan recent user messages for email patterns
    if lead_data is None:
        recent_user_msgs = [
            m["content"] for m in history if m["role"] == "user"
        ][-3:]
        # Include the current message
        recent_user_msgs.append(message)
        lead_data = _fallback_email_scan(recent_user_msgs)

    if lead_data is not None:
        lead_captured = True
        asyncio.create_task(
            _capture_conversational_lead(client_id, conversation_id, lead_data)
        )

    # Wind-down event — suppress form if lead was already captured conversationally
    if wind_down:
        if lead_captured:
            yield _sse_event(
                "lead_already_captured", {"turns_remaining": turns_remaining}
            )
        else:
            yield _sse_event("wind_down", {"turns_remaining": turns_remaining})

    # Analytics (fire-and-forget)
    event_meta: dict[str, Any] = {}
    if preflight.boundary_signal:
        event_meta["boundary_signal"] = preflight.boundary_signal

    event_type = "first_message" if new_turn_count == 1 else "message"
    asyncio.create_task(_emit_analytics(client_id, conversation_id, event_type, event_meta or None))

    # Out of scope tracking
    if not preflight.in_scope:
        asyncio.create_task(_emit_analytics(client_id, conversation_id, "out_of_scope"))

    yield _sse_event("done", {"turns_remaining": turns_remaining})
