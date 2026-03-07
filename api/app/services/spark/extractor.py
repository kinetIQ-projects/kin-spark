"""
Extractor Service — Stage 3 of the ingestion pipeline.

Produces 6 artifacts from classified chunks using Opus:
  1. Voice Profile → spark_profiles (type: voice)
  2. Values Profile → spark_profiles (type: values)
  3. Boundary Rules → spark_profiles (type: boundaries)
  4. ICP Profiles → spark_profiles (type: icp)
  5. Procedure Playbooks → spark_profiles (type: procedures)
  6. Knowledge Base Items → spark_knowledge_items (active: false)
     Extracted from ALL classified chunks (not just "facts") because
     FAQs and product info span every signal type.

Where alignment findings identified contradictions relevant to a profile,
the extractor flags them as annotations — does NOT silently resolve them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from uuid import UUID

from app.config import settings
from app.services import llm
from app.services.spark.knowledge import create_knowledge_item
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# ── Profile extraction prompts ─────────────────────────────────────────

_PROFILE_PROMPTS: dict[str, str] = {
    "voice": """You are extracting a Voice Profile from a business's classified materials.

Using ONLY the voice-signal chunks below, produce a narrative document describing this business's communication style:
- Tone (formal/casual/warm/edgy/professional/etc.)
- Energy level and pacing
- Personality traits that come through
- Language patterns and vocabulary preferences
- How they address their audience
- What makes their voice distinctive

{alignment_notes}

== VOICE SIGNAL CHUNKS ==
{chunks}

Write the voice profile as a clear, actionable document that could be used to train an AI to write in this business's voice. Use specific examples from the source material. 2-3 pages.

If any areas have alignment notes, include them as "[ALIGNMENT NOTE: ...]" annotations inline — do NOT resolve contradictions yourself.""",

    "values": """You are extracting a Values Profile from a business's classified materials.

Using ONLY the values-signal chunks below, produce a structured document describing this business's core beliefs and principles:
- Core values (with evidence from source material)
- What the business stands for
- What they prioritize in decision-making
- Cultural beliefs that drive behavior
- How values manifest in practice

{alignment_notes}

== VALUES SIGNAL CHUNKS ==
{chunks}

Write as a structured document with each value clearly stated, supported by evidence from their materials. Include "[ALIGNMENT NOTE: ...]" for any flagged contradictions.""",

    "boundaries": """You are extracting Boundary Rules from a business's classified materials.

Using ONLY the boundaries-signal chunks below, produce an explicit rule list:
- Legal constraints and disclaimers
- Things the business should NOT say or claim
- Topics to avoid
- Limitations on promises or guarantees
- Compliance requirements
- Sensitive areas requiring careful handling

{alignment_notes}

== BOUNDARY SIGNAL CHUNKS ==
{chunks}

Write as a clear numbered list of rules/boundaries. Each rule should be actionable — an AI system should know exactly what NOT to do. Include "[ALIGNMENT NOTE: ...]" for flagged contradictions.""",

    "icp": """You are extracting Ideal Customer Profiles from a business's classified materials.

Using ONLY the ICP-signal chunks below, produce persona documents:
- Who the business serves (demographics, firmographics)
- Customer pain points and challenges
- What customers are looking for
- Buying triggers and signals
- Common objections
- How this business helps them

{alignment_notes}

== ICP SIGNAL CHUNKS ==
{chunks}

Write as detailed persona profiles. If multiple distinct customer types exist, create a separate section for each. Include "[ALIGNMENT NOTE: ...]" for flagged contradictions.""",

    "procedures": """You are extracting Procedure Playbooks from a business's classified materials.

Using ONLY the procedures-signal chunks below, produce operational guides:
- How the business handles inquiries
- Sales process and stages
- Service delivery workflow
- Escalation procedures
- Common scenarios and how to handle them
- Response templates and approaches

{alignment_notes}

== PROCEDURE SIGNAL CHUNKS ==
{chunks}

Write as actionable playbooks with clear conditional logic ("When X happens, do Y"). Include triggers, steps, and expected outcomes. Include "[ALIGNMENT NOTE: ...]" for flagged contradictions.""",
}

_KB_EXTRACTION_PROMPT = """You are extracting individual knowledge base items from a business's factual content.

Using ONLY the facts-signal chunks below, extract discrete knowledge items — individual pieces of factual information that a customer-facing AI would need to know.

Each item should be:
- A single, self-contained fact (not a paragraph of mixed information)
- Useful for answering customer questions
- Categorized as one of: company, product, competitor, legal, team, fun, customer_profile, procedure

Category guide:
- company: general business info (about, history, location, contact, hours)
- product: products, services, pricing, features, offerings
- competitor: competitive positioning, market differentiation
- legal: legal disclaimers, terms, compliance, policies
- team: people, roles, bios, org structure
- fun: fun facts, culture, personality
- customer_profile: customer demographics, use cases, testimonials
- procedure: processes, workflows, how things work

== FACTS SIGNAL CHUNKS ==
{chunks}

Respond with ONLY valid JSON:
{{"items": [{{"title": "brief title (max 100 chars)", "content": "the factual content (max 2000 chars)", "category": "company|product|competitor|legal|team|fun|customer_profile|procedure"}}]}}

Extract as many distinct items as the source material supports. Do not fabricate — only extract what is explicitly stated."""

_VALID_KB_CATEGORIES = frozenset({
    "company", "product", "competitor", "legal",
    "team", "fun", "customer_profile", "procedure",
})


async def extract_artifacts(
    client_id: UUID,
    run_id: UUID,
    classified_chunks: list[dict[str, Any]],
    alignment_findings: list[dict[str, Any]],
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> dict[str, Any]:
    """Extract profiles and KB items from classified chunks.

    Args:
        client_id: The client ID.
        run_id: The pipeline run ID.
        classified_chunks: List of classified chunk dicts from Stage 1.
        alignment_findings: List of contradiction findings from Stage 2.
        progress_callback: Optional async callback(current, total, message).

    Returns:
        Dict with counts: {profiles_created, kb_items_created}.
    """
    sb = await get_supabase_client()

    # Group chunks by signal type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for chunk in classified_chunks:
        for signal_type in chunk.get("signal_types", []):
            by_type.setdefault(signal_type, []).append(chunk)

    # Group alignment findings by relevant signal types
    alignment_by_type: dict[str, list[dict[str, Any]]] = {}
    for finding in alignment_findings:
        comparison = finding.get("comparison", "")
        for signal_type in comparison.split("_vs_"):
            alignment_by_type.setdefault(signal_type, []).append(finding)

    # 5 profile types + 1 KB extraction = 6 total steps
    total_steps = 6
    completed = 0
    profiles_created = 0
    kb_items_created = 0

    # ── Extract profiles ─────────────────────────────────────────
    for profile_type, prompt_template in _PROFILE_PROMPTS.items():
        chunks = by_type.get(profile_type, [])

        if not chunks:
            logger.info("No %s chunks for client %s, skipping profile", profile_type, client_id)
            completed += 1
            if progress_callback:
                await progress_callback(
                    completed, total_steps,
                    f"Skipped {profile_type} profile (no data)",
                )
            continue

        chunks_text = _format_chunks(chunks)
        # Truncate to stay within token limits (~80K chars ≈ ~20K tokens)
        chunks_text = chunks_text[:80_000]

        # Build alignment notes section
        relevant_findings = alignment_by_type.get(profile_type, [])
        alignment_notes = _format_alignment_notes(relevant_findings)

        prompt = prompt_template.format(
            chunks=chunks_text,
            alignment_notes=alignment_notes,
        )

        try:
            content = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=settings.pipeline_stage_3_model,
                temperature=0.3,
                max_tokens=8000,
                timeout=180,
            )

            if content.strip():
                await (
                    sb.table("spark_profiles")
                    .insert({
                        "client_id": str(client_id),
                        "pipeline_run_id": str(run_id),
                        "profile_type": profile_type,
                        "content": content,
                        "status": "draft",
                    })
                    .execute()
                )
                profiles_created += 1
                logger.info(
                    "Created %s profile for client %s (%d chars)",
                    profile_type, client_id, len(content),
                )

        except Exception as e:
            logger.error(
                "Profile extraction failed for %s: %s",
                profile_type, e,
            )

        completed += 1
        if progress_callback:
            await progress_callback(
                completed, total_steps,
                f"Extracted {profile_type} profile ({completed}/{total_steps})",
            )

    logger.info(
        "Profile extraction complete: %d profiles. Starting KB extraction...",
        profiles_created,
    )

    # ── Extract KB items from ALL chunks ─────────────────────────
    # FAQs and product info span every signal type (procedures, values,
    # etc.), not just "facts". Use the full corpus for KB extraction.
    all_chunks = classified_chunks or []
    if all_chunks:
        chunks_text = _format_chunks(all_chunks)
        chunks_text = chunks_text[:80_000]

        prompt = _KB_EXTRACTION_PROMPT.format(chunks=chunks_text)

        logger.info(
            "KB extraction: sending %d chunks (%d chars) to %s",
            len(all_chunks), len(chunks_text), settings.pipeline_stage_3_model,
        )

        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=settings.pipeline_stage_3_model,
                temperature=0.2,
                max_tokens=8000,
                response_format={"type": "json_object"},
                timeout=180,
            )

            logger.info(
                "KB extraction LLM response: %d chars, preview: %.200s",
                len(response), response[:200],
            )

            kb_items = _parse_kb_response(response)
            logger.info("KB extraction parsed %d valid items", len(kb_items))

            for item in kb_items:
                try:
                    await create_knowledge_item(
                        client_id=client_id,
                        title=item["title"],
                        content=item["content"],
                        category=item["category"],
                        active=False,  # Client activates during review
                    )
                    kb_items_created += 1
                except Exception as e:
                    # Duplicate or other error — skip and continue
                    err_str = str(e).lower()
                    if "409" in err_str or "duplicate" in err_str:
                        logger.debug("KB item duplicate, skipping: %s", item["title"])
                    else:
                        logger.warning("Failed to create KB item '%s': %s", item["title"], e)

            logger.info(
                "Created %d KB items for client %s",
                kb_items_created, client_id,
            )

        except Exception as e:
            logger.exception("KB extraction failed for client %s", client_id)
    else:
        logger.info("No classified chunks for client %s, skipping KB extraction", client_id)

    completed += 1
    if progress_callback:
        await progress_callback(
            completed, total_steps,
            f"Extraction complete: {profiles_created} profiles, {kb_items_created} KB items",
        )

    return {
        "profiles_created": profiles_created,
        "kb_items_created": kb_items_created,
    }


def _format_chunks(chunks: list[dict[str, Any]]) -> str:
    """Format classified chunks into labeled text blocks."""
    parts: list[str] = []
    for chunk in chunks:
        source = chunk.get("metadata", {}).get("source_name", "Unknown")
        content = chunk.get("content", "")
        parts.append(f"[Source: {source}]\n{content}")
    return "\n\n---\n\n".join(parts)


def _format_alignment_notes(findings: list[dict[str, Any]]) -> str:
    """Format alignment findings as context for the extractor."""
    if not findings:
        return ""

    lines = [
        "**IMPORTANT — The following alignment issues were detected. "
        "Flag these as [ALIGNMENT NOTE: ...] annotations in the profile "
        "where relevant. Do NOT resolve them — just note them.**\n"
    ]
    for f in findings:
        lines.append(
            f"- {f['area']} ({f['severity']}): "
            f"One side says \"{f['marketed']}\", "
            f"but the other suggests \"{f['operational']}\""
        )

    return "\n".join(lines) + "\n"


def _parse_kb_response(response: str) -> list[dict[str, Any]]:
    """Parse and validate the KB extraction response."""
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse KB extraction JSON")
        return []

    items = data.get("items", [])
    if not isinstance(items, list):
        return []

    valid: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title", ""))[:200]
        content = str(item.get("content", ""))[:3000]
        category = str(item.get("category", "company"))

        if category not in _VALID_KB_CATEGORIES:
            category = "company"

        if not title or not content:
            continue

        valid.append({
            "title": title,
            "content": content,
            "category": category,
        })

    return valid
