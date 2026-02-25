"""
Spark Orchestrator — Core pipeline for Kin Spark conversations.

Pipeline:
  1. Pre-flight (parallel safety + retrieval, ~200ms)
  2. Safety gate (tiered deflection if unsafe)
  3. Context assembly (settling + docs + sliding window + turn awareness)
  4. LLM stream (Flash via llm.stream)
  5. Post-process (normalize_format)
  6. Store messages + analytics event (fire-and-forget)

Yields SSE events: session | token | wind_down | done | error
"""

from __future__ import annotations

import asyncio
import json
import logging
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

logger = logging.getLogger(__name__)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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


def _deflection_response(
    rejection_tier: str | None,
    settling_config: dict[str, Any],
) -> str:
    """Get appropriate deflection response for unsafe messages."""
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


async def process_message(
    message: str,
    client_id: UUID,
    conversation_id: UUID,
    settling_config: dict[str, Any],
    max_turns: int,
    turn_count: int,
) -> AsyncGenerator[str, None]:
    """Process a Spark chat message. Yields SSE event strings.

    This is the main pipeline — called by the router after auth,
    rate limiting, and session management.
    """
    # -------------------------------------------------------------------------
    # 1. Pre-flight (parallel safety + retrieval)
    # -------------------------------------------------------------------------
    try:
        preflight = await run_preflight(message, client_id)
    except Exception as e:
        logger.error("Spark preflight failed: %s", e)
        yield _sse_event(
            "error", {"message": "Something went wrong. Please try again."}
        )
        return

    # -------------------------------------------------------------------------
    # 2. Safety gate
    # -------------------------------------------------------------------------
    if not preflight.safe:
        deflection = _deflection_response(preflight.rejection_tier, settling_config)

        # Store both messages
        await store_message(conversation_id, "user", message)
        await store_message(conversation_id, "assistant", deflection)

        # Emit as tokens for streaming consistency
        for word in deflection.split(" "):
            yield _sse_event("token", {"text": word + " "})

        # Track the event
        asyncio.create_task(
            _emit_analytics(
                client_id,
                conversation_id,
                "jailbreak_blocked",
                {"tier": preflight.rejection_tier},
            )
        )

        if preflight.rejection_tier == "terminate":
            from app.services.spark.session import end_session

            await end_session(conversation_id, state="terminated")

        yield _sse_event("done", {})
        return

    # -------------------------------------------------------------------------
    # 3. Increment turn + check wind-down
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

        await end_session(conversation_id, state="completed")
        yield _sse_event("done", {"turns_remaining": 0})
        return

    # -------------------------------------------------------------------------
    # 4. Context assembly
    # -------------------------------------------------------------------------
    # Get sliding window of conversation history
    history = await get_history(conversation_id, limit=settings.spark_context_turns)

    # Build system prompt
    system_prompt = build_system_prompt(
        settling_config=settling_config,
        retrieved_chunks=preflight.retrieved_chunks,
        turn_count=new_turn_count,
        max_turns=max_turns,
        wind_down=wind_down,
        conversation_state=preflight.conversation_state,
        rejection_tier=preflight.rejection_tier,
    )

    # Assemble messages for LLM
    llm_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Add sliding window history
    for msg in history:
        llm_messages.append(
            {
                "role": msg["role"],
                "content": msg["content"],
            }
        )

    # Add current user message
    llm_messages.append({"role": "user", "content": message})

    # -------------------------------------------------------------------------
    # 5. Store user message
    # -------------------------------------------------------------------------
    await store_message(conversation_id, "user", message)

    # -------------------------------------------------------------------------
    # 6. LLM stream
    # -------------------------------------------------------------------------
    full_response = ""
    try:
        async for chunk in llm.stream(
            messages=llm_messages,
            model=settings.spark_primary_model,
            temperature=0.7,
            max_tokens=1024,
        ):
            full_response += chunk
            yield _sse_event("token", {"text": chunk})
    except Exception as e:
        logger.error("Spark LLM stream failed: %s", e)
        yield _sse_event("error", {"message": "I hit a snag. Please try again."})
        return

    # -------------------------------------------------------------------------
    # 7. Post-process + store
    # -------------------------------------------------------------------------
    normalized = normalize_format(full_response)

    await store_message(conversation_id, "assistant", normalized)

    # Wind-down event
    if wind_down:
        yield _sse_event("wind_down", {"turns_remaining": turns_remaining})

    # Analytics (fire-and-forget)
    event_type = "first_message" if new_turn_count == 1 else "message"
    asyncio.create_task(_emit_analytics(client_id, conversation_id, event_type))

    # Out of scope tracking
    if not preflight.in_scope:
        asyncio.create_task(_emit_analytics(client_id, conversation_id, "out_of_scope"))

    yield _sse_event("done", {"turns_remaining": turns_remaining})
