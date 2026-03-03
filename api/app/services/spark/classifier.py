"""
Classification Service — Stage 1 of the ingestion pipeline.

Gathers all source material, chunks it, and classifies each chunk
with multi-label signal types using Sonnet via LLM service.

Signal types:
  - voice: tone, personality, energy, style
  - values: beliefs, principles, what matters
  - facts: concrete info (services, pricing, hours, team, history)
  - procedures: how things are done, workflows, policies
  - boundaries: what not to do, legal constraints, disclaimers
  - icp: customer descriptions, pain points, who they serve

Stores results in spark_classified_chunks (no embeddings).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from uuid import UUID

from app.config import settings
from app.services import llm
from app.services.spark.ingestion import chunk_text
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10  # Chunks per LLM call
_VALID_SIGNAL_TYPES = frozenset({"voice", "values", "facts", "procedures", "boundaries", "icp"})

_CLASSIFICATION_PROMPT = """You are classifying text chunks from a business's materials.
For each chunk, assign one or more signal types:
- voice: tone, personality, energy, style of communication
- values: beliefs, principles, what the business cares about
- facts: concrete info (services, pricing, hours, team bios, history, locations)
- procedures: how things are done, workflows, policies, processes
- boundaries: what not to do, legal constraints, disclaimers, limitations
- icp: customer descriptions, pain points, who they serve, target audience

A chunk can have MULTIPLE signal types (e.g., a brand guide paragraph might be both "voice" and "values").
Assign a confidence score (0.0-1.0) for the overall classification quality.

Here are the chunks to classify:

{chunks_text}

Respond with ONLY valid JSON in this exact format:
{{"chunks": [{{"index": 0, "signal_types": ["voice", "values"], "confidence": 0.9}}, ...]}}"""


async def classify_sources(
    client_id: UUID,
    run_id: UUID,
    sources: dict[str, Any],
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify all source material into signal-typed chunks.

    Args:
        client_id: The client ID.
        run_id: The pipeline run ID.
        sources: Dict from _gather_sources() with uploads, paste_items,
            questionnaire_text.
        progress_callback: Optional async callback(current, total, message)
            for progress updates.

    Returns:
        List of classified chunk dicts as stored in DB.
    """
    sb = await get_supabase_client()

    # Delete any existing classified chunks for this run (idempotent re-run)
    await (
        sb.table("spark_classified_chunks")
        .delete()
        .eq("pipeline_run_id", str(run_id))
        .execute()
    )

    # ── Build chunk list with source attribution ────────────────
    raw_chunks: list[dict[str, Any]] = []

    # Uploads (includes scrape results — both have parsed_text)
    for upload in sources.get("uploads", []):
        parsed = upload.get("parsed_text")
        if not parsed:
            continue
        text_chunks = chunk_text(parsed)
        for i, chunk in enumerate(text_chunks):
            raw_chunks.append({
                "content": chunk,
                "source_type": upload.get("source_type", "upload"),
                "source_id": upload.get("id"),
                "metadata": {
                    "source_name": upload.get("original_name", ""),
                    "chunk_index": i,
                },
            })

    # Paste items
    for paste in sources.get("paste_items", []):
        content = paste.get("content")
        if not content:
            continue
        text_chunks = chunk_text(content)
        for i, chunk in enumerate(text_chunks):
            raw_chunks.append({
                "content": chunk,
                "source_type": "paste",
                "source_id": paste.get("id"),
                "metadata": {
                    "source_name": paste.get("title", "Pasted text"),
                    "chunk_index": i,
                },
            })

    # Questionnaire
    questionnaire_text = sources.get("questionnaire_text", "")
    if questionnaire_text:
        text_chunks = chunk_text(questionnaire_text)
        for i, chunk in enumerate(text_chunks):
            raw_chunks.append({
                "content": chunk,
                "source_type": "questionnaire",
                "source_id": None,
                "metadata": {
                    "source_name": "Onboarding Questionnaire",
                    "chunk_index": i,
                },
            })

    total_chunks = len(raw_chunks)
    if total_chunks == 0:
        logger.warning("No chunks to classify for client %s", client_id)
        return []

    logger.info("Classifying %d chunks for client %s", total_chunks, client_id)

    # ── Classify in batches ─────────────────────────────────────
    all_classified: list[dict[str, Any]] = []
    processed = 0

    for batch_start in range(0, total_chunks, _BATCH_SIZE):
        batch = raw_chunks[batch_start : batch_start + _BATCH_SIZE]

        # Build prompt with chunk text
        chunks_text = "\n\n".join(
            f"--- CHUNK {i} ---\n{c['content']}"
            for i, c in enumerate(batch)
        )

        prompt = _CLASSIFICATION_PROMPT.format(chunks_text=chunks_text)

        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=settings.pipeline_stage_1_model,
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"},
                timeout=60,
            )

            classifications = _parse_classification_response(response, len(batch))

        except Exception as e:
            logger.error(
                "Classification failed for batch starting at %d: %s",
                batch_start, e,
            )
            # On failure, assign all chunks as "facts" with low confidence
            classifications = [
                {"index": i, "signal_types": ["facts"], "confidence": 0.3}
                for i in range(len(batch))
            ]

        # Store classified chunks
        rows_to_insert: list[dict[str, Any]] = []
        for i, chunk_data in enumerate(batch):
            classification = classifications[i] if i < len(classifications) else {
                "signal_types": ["facts"],
                "confidence": 0.3,
            }

            row = {
                "pipeline_run_id": str(run_id),
                "client_id": str(client_id),
                "source_type": chunk_data["source_type"],
                "source_id": chunk_data["source_id"],
                "content": chunk_data["content"],
                "signal_types": classification["signal_types"],
                "confidence": classification["confidence"],
                "metadata": chunk_data["metadata"],
            }
            rows_to_insert.append(row)
            all_classified.append(row)

        if rows_to_insert:
            await sb.table("spark_classified_chunks").insert(rows_to_insert).execute()

        processed += len(batch)

        if progress_callback is not None:
            await progress_callback(
                processed,
                total_chunks,
                f"Classifying chunk {processed}/{total_chunks}",
            )

    logger.info(
        "Classification complete for client %s: %d chunks classified",
        client_id, len(all_classified),
    )
    return all_classified


def _parse_classification_response(
    response: str, expected_count: int
) -> list[dict[str, Any]]:
    """Parse and validate the LLM classification response.

    Returns a list of dicts with {index, signal_types, confidence}.
    Falls back to safe defaults on parse failure.
    """
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse classification JSON, using fallback")
        return [
            {"index": i, "signal_types": ["facts"], "confidence": 0.3}
            for i in range(expected_count)
        ]

    chunks = data.get("chunks", [])
    if not isinstance(chunks, list):
        logger.warning("Classification response missing 'chunks' array")
        return [
            {"index": i, "signal_types": ["facts"], "confidence": 0.3}
            for i in range(expected_count)
        ]

    # Build index-keyed map for lookup
    result_map: dict[int, dict[str, Any]] = {}
    for item in chunks:
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= expected_count:
            continue

        raw_types = item.get("signal_types", [])
        if not isinstance(raw_types, list):
            raw_types = ["facts"]

        # Validate signal types
        valid_types = [t for t in raw_types if t in _VALID_SIGNAL_TYPES]
        if not valid_types:
            valid_types = ["facts"]

        confidence = item.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)):
            confidence = 0.5
        confidence = max(0.0, min(1.0, float(confidence)))

        result_map[idx] = {
            "index": idx,
            "signal_types": valid_types,
            "confidence": confidence,
        }

    # Build ordered result list, filling gaps with defaults
    results: list[dict[str, Any]] = []
    for i in range(expected_count):
        if i in result_map:
            results.append(result_map[i])
        else:
            results.append({
                "index": i,
                "signal_types": ["facts"],
                "confidence": 0.3,
            })

    return results
