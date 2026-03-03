"""
Alignment Service — Stage 2 of the ingestion pipeline.

Cross-references classified chunks across signal type pairs to detect
contradictions, gaps, and misalignments in a client's materials.

Runs 7 defined comparison pairs using Opus, then compiles findings
into a structured alignment report stored in spark_alignment_reports.

Comparison Matrix:
  1. voice vs. procedures — Tone mismatch
  2. values vs. procedures — Values don't match operations
  3. voice vs. facts — Marketing doesn't match factual content
  4. values vs. facts — Claimed values contradict evidence
  5. boundaries vs. procedures — Legal vs. operational promises
  6. icp vs. voice — Target audience vs. brand voice mismatch
  7. voice vs. values — Personality contradicts stated beliefs
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from uuid import UUID

from app.config import settings
from app.services import llm
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# The 7 cross-reference comparison pairs
_COMPARISON_PAIRS: list[tuple[str, str, str]] = [
    ("voice", "procedures", "Tone mismatch between brand voice and operational procedures"),
    ("values", "procedures", "Stated values don't match operational reality"),
    ("voice", "facts", "Marketing voice doesn't match factual content"),
    ("values", "facts", "Claimed values contradict factual evidence"),
    ("boundaries", "procedures", "Legal disclaimers conflict with operational promises"),
    ("icp", "voice", "Target audience mismatch with brand voice"),
    ("voice", "values", "Brand personality contradicts stated beliefs"),
]

_CROSSREF_PROMPT = """You are analyzing a business's materials for internal contradictions and misalignments.

Compare these two categories of content from the same business:

== {type_a_label} SIGNALS ({type_a}) ==
{type_a_chunks}

== {type_b_label} SIGNALS ({type_b}) ==
{type_b_chunks}

Context: {pair_description}

Identify contradictions, gaps, and misalignments between these two categories. For each finding:
- What the business markets/claims in one area
- What the other area suggests or contradicts
- Source attribution for both sides (use the source names provided)
- Severity: minor (cosmetic inconsistency), moderate (confusing to customers), significant (damages trust)

If there are no contradictions, return an empty findings array.

Respond with ONLY valid JSON in this exact format:
{{"findings": [{{"area": "brief description", "marketed": "what one side claims", "operational": "what the other side suggests", "source_a": "source name", "source_b": "source name", "severity": "minor|moderate|significant"}}]}}"""

_TYPE_LABELS: dict[str, str] = {
    "voice": "BRAND VOICE",
    "values": "VALUES & BELIEFS",
    "facts": "FACTUAL CONTENT",
    "procedures": "PROCEDURES & OPERATIONS",
    "boundaries": "BOUNDARIES & LEGAL",
    "icp": "IDEAL CUSTOMER PROFILE",
}


async def cross_reference(
    client_id: UUID,
    run_id: UUID,
    classified_chunks: list[dict[str, Any]],
    progress_callback: Callable[[int, int, str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Run cross-reference analysis across classified chunks.

    Args:
        client_id: The client ID.
        run_id: The pipeline run ID.
        classified_chunks: List of classified chunk dicts from Stage 1.
        progress_callback: Optional async callback(current, total, message).

    Returns:
        List of all contradiction findings across all comparison pairs.
    """
    sb = await get_supabase_client()

    # Group chunks by signal type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for chunk in classified_chunks:
        for signal_type in chunk.get("signal_types", []):
            by_type.setdefault(signal_type, []).append(chunk)

    all_findings: list[dict[str, Any]] = []
    total_pairs = len(_COMPARISON_PAIRS)
    completed = 0

    for type_a, type_b, description in _COMPARISON_PAIRS:
        chunks_a = by_type.get(type_a, [])
        chunks_b = by_type.get(type_b, [])

        # Skip pairs where either side has no chunks
        if not chunks_a or not chunks_b:
            logger.info(
                "Skipping %s vs %s: %d/%d chunks",
                type_a, type_b, len(chunks_a), len(chunks_b),
            )
            completed += 1
            if progress_callback:
                await progress_callback(
                    completed, total_pairs,
                    f"Skipped {type_a} vs {type_b} (insufficient data)",
                )
            continue

        # Format chunk text with source attribution
        type_a_text = _format_chunks(chunks_a)
        type_b_text = _format_chunks(chunks_b)

        # Truncate if too long (keep under ~50K tokens per side)
        type_a_text = type_a_text[:80_000]
        type_b_text = type_b_text[:80_000]

        prompt = _CROSSREF_PROMPT.format(
            type_a=type_a,
            type_b=type_b,
            type_a_label=_TYPE_LABELS.get(type_a, type_a.upper()),
            type_b_label=_TYPE_LABELS.get(type_b, type_b.upper()),
            type_a_chunks=type_a_text,
            type_b_chunks=type_b_text,
            pair_description=description,
        )

        try:
            response = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=settings.pipeline_stage_2_model,
                temperature=0.2,
                max_tokens=4000,
                response_format={"type": "json_object"},
                timeout=120,
            )

            findings = _parse_findings(response, type_a, type_b)
            all_findings.extend(findings)

            logger.info(
                "Cross-ref %s vs %s: %d findings",
                type_a, type_b, len(findings),
            )

        except Exception as e:
            logger.error(
                "Cross-reference failed for %s vs %s: %s",
                type_a, type_b, e,
            )
            # Continue with other pairs — don't fail the whole stage

        completed += 1
        if progress_callback:
            await progress_callback(
                completed, total_pairs,
                f"Compared {type_a} vs {type_b} ({completed}/{total_pairs})",
            )

    # Build and store the alignment report
    report_content = _build_report_text(all_findings)

    await (
        sb.table("spark_alignment_reports")
        .insert({
            "client_id": str(client_id),
            "pipeline_run_id": str(run_id),
            "content": report_content,
            "contradictions": all_findings,
        })
        .execute()
    )

    logger.info(
        "Alignment report for client %s: %d total findings",
        client_id, len(all_findings),
    )

    return all_findings


def _format_chunks(chunks: list[dict[str, Any]]) -> str:
    """Format classified chunks into labeled text blocks."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks):
        source = chunk.get("metadata", {}).get("source_name", "Unknown")
        content = chunk.get("content", "")
        parts.append(f"[Source: {source}]\n{content}")
    return "\n\n---\n\n".join(parts)


def _parse_findings(
    response: str,
    type_a: str,
    type_b: str,
) -> list[dict[str, Any]]:
    """Parse and validate the LLM cross-reference response."""
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        logger.warning("Failed to parse cross-ref JSON for %s vs %s", type_a, type_b)
        return []

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        return []

    valid: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue

        severity = finding.get("severity", "minor")
        if severity not in ("minor", "moderate", "significant"):
            severity = "minor"

        valid.append({
            "area": str(finding.get("area", ""))[:500],
            "marketed": str(finding.get("marketed", ""))[:1000],
            "operational": str(finding.get("operational", ""))[:1000],
            "source_a": str(finding.get("source_a", ""))[:200],
            "source_b": str(finding.get("source_b", ""))[:200],
            "severity": severity,
            "comparison": f"{type_a}_vs_{type_b}",
        })

    return valid


def _build_report_text(findings: list[dict[str, Any]]) -> str:
    """Build a human-readable alignment report from structured findings."""
    if not findings:
        return "# Alignment Report\n\nNo contradictions or misalignments detected."

    # Group by severity
    by_severity: dict[str, list[dict[str, Any]]] = {
        "significant": [],
        "moderate": [],
        "minor": [],
    }
    for f in findings:
        by_severity.get(f["severity"], by_severity["minor"]).append(f)

    parts = ["# Alignment Report\n"]
    parts.append(f"**Total findings:** {len(findings)}")
    parts.append(
        f"- Significant: {len(by_severity['significant'])}, "
        f"Moderate: {len(by_severity['moderate'])}, "
        f"Minor: {len(by_severity['minor'])}\n"
    )

    for severity in ("significant", "moderate", "minor"):
        items = by_severity[severity]
        if not items:
            continue

        parts.append(f"## {severity.title()} Issues\n")
        for i, f in enumerate(items, 1):
            comparison = f.get("comparison", "").replace("_vs_", " vs ")
            parts.append(f"### {i}. {f['area']} ({comparison})")
            parts.append(f"- **One side claims:** {f['marketed']}")
            parts.append(f"- **Other side suggests:** {f['operational']}")
            parts.append(f"- Sources: {f['source_a']} / {f['source_b']}\n")

    return "\n".join(parts)
