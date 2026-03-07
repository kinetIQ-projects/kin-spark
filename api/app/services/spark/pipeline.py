"""
Pipeline Runner — Orchestrates the multi-stage ingestion pipeline.

Stages:
  - Stage 0: Web scraping (optional, when include_scrape=True)
  - Stage 1: Classification (chunks → signal types via Sonnet)
  - Stage 2: Cross-reference (contradiction detection via Opus)
  - Stage 3: Extraction (profiles + KB items via Opus)

Features:
  - Heartbeat: updates last_heartbeat every 30s
  - Cancellation: checks `cancelled` flag between stages
  - Exception safety: catches all errors, marks run as failed
  - Stale detection: mark_stale_runs() called on app startup
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 30


async def mark_stale_runs() -> None:
    """Mark any in-progress pipeline runs as failed on startup.

    Called from main.py lifespan. If the server crashed mid-pipeline,
    any run with a heartbeat older than 5 minutes is considered stale.
    """
    sb = await get_supabase_client()

    # Find runs that are not in a terminal state
    terminal_statuses = ("completed", "failed", "cancelled")
    result = await (
        sb.table("spark_pipeline_runs")
        .select("id, last_heartbeat, status")
        .not_.in_("status", terminal_statuses)
        .execute()
    )

    if not result.data:
        return

    now = datetime.now(timezone.utc)
    stale_ids: list[str] = []

    for row in result.data:
        heartbeat = row.get("last_heartbeat")
        if heartbeat is None:
            # No heartbeat ever recorded — if status is pending, leave it
            if row["status"] != "pending":
                stale_ids.append(row["id"])
        else:
            # Parse heartbeat timestamp
            if isinstance(heartbeat, str):
                hb_time = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
            else:
                hb_time = heartbeat
            age = (now - hb_time).total_seconds()
            if age > 300:  # 5 minutes
                stale_ids.append(row["id"])

    for run_id in stale_ids:
        logger.warning("Marking stale pipeline run as failed: %s", run_id)
        await (
            sb.table("spark_pipeline_runs")
            .update(
                {
                    "status": "failed",
                    "error_message": "Server restarted during pipeline execution",
                    "completed_at": now.isoformat(),
                }
            )
            .eq("id", run_id)
            .execute()
        )

    if stale_ids:
        logger.info("Marked %d stale pipeline runs as failed", len(stale_ids))


async def run_pipeline(
    run_id: UUID,
    client_id: UUID,
    include_uploads: bool = True,
    include_paste: bool = True,
    include_questionnaire: bool = True,
    include_scrape: bool = False,
) -> None:
    """Execute the ingestion pipeline for a client.

    This is the main entry point, called from BackgroundTask.
    Updates progress in spark_pipeline_runs throughout.
    """
    sb = await get_supabase_client()
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # Mark as started
        await _update_run(
            sb,
            run_id,
            status="pending",
            progress={"stage": "gathering", "percent": 0, "message": "Gathering sources..."},
            started_at=datetime.now(timezone.utc).isoformat(),
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
        )

        # Start heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat_loop(run_id))

        # ── Gather sources ──────────────────────────────────────
        sources = await _gather_sources(
            client_id,
            include_uploads=include_uploads,
            include_paste=include_paste,
            include_questionnaire=include_questionnaire,
        )

        source_summary = {
            "uploads": sources.get("upload_count", 0),
            "paste_items": sources.get("paste_count", 0),
            "questionnaire": sources.get("has_questionnaire", False),
            "scraped_pages": 0,
        }

        await _update_run(
            sb,
            run_id,
            source_summary=source_summary,
            progress={"stage": "gathering", "percent": 100, "message": "Sources gathered"},
        )

        # ── Check for cancellation ──────────────────────────────
        if await _is_cancelled(sb, run_id):
            await _mark_cancelled(sb, run_id)
            return

        # ── Embed parsed uploads into spark_documents ─────────────
        # This makes the raw content searchable during conversations.
        from app.services.spark.ingestion import ingest_text

        embed_count = 0
        uploads_to_embed = sources.get("uploads", [])
        for i, upload in enumerate(uploads_to_embed):
            parsed = upload.get("parsed_text")
            if not parsed:
                continue
            try:
                inserted = await ingest_text(
                    client_id=client_id,
                    content=parsed,
                    title=upload.get("original_name"),
                    source_type=upload.get("source_type", "upload"),
                )
                embed_count += inserted
            except Exception as e:
                logger.warning(
                    "Failed to embed upload %s: %s",
                    upload.get("id"), e,
                )

        # Embed paste items too
        for paste in sources.get("paste_items", []):
            content = paste.get("content")
            if not content:
                continue
            try:
                inserted = await ingest_text(
                    client_id=client_id,
                    content=content,
                    title=paste.get("title", "Pasted text"),
                    source_type="paste",
                )
                embed_count += inserted
            except Exception as e:
                logger.warning(
                    "Failed to embed paste item %s: %s",
                    paste.get("id"), e,
                )

        # Embed questionnaire text
        questionnaire_text = sources.get("questionnaire_text", "")
        if questionnaire_text:
            try:
                inserted = await ingest_text(
                    client_id=client_id,
                    content=questionnaire_text,
                    title="Onboarding Questionnaire",
                    source_type="questionnaire",
                )
                embed_count += inserted
            except Exception as e:
                logger.warning("Failed to embed questionnaire: %s", e)

        logger.info(
            "Embedded %d document chunks for client %s",
            embed_count, client_id,
        )

        await _update_run(
            sb,
            run_id,
            progress={
                "stage": "gathering",
                "percent": 100,
                "message": f"Embedded {embed_count} document chunks",
            },
        )

        if await _is_cancelled(sb, run_id):
            await _mark_cancelled(sb, run_id)
            return

        # ── Stage 0: Scrape ──────────────────────────────────────
        if include_scrape:
            await _update_run(
                sb,
                run_id,
                status="stage_0_scrape",
                progress={"stage": "stage_0_scrape", "percent": 0, "message": "Starting web scrape..."},
            )

            # Get website URL from client
            client_row = await (
                sb.table("spark_clients")
                .select("website_url")
                .eq("id", str(client_id))
                .limit(1)
                .execute()
            )
            website_url = (client_row.data[0].get("website_url") or "") if client_row.data else ""

            if website_url:
                from app.services.spark.scraper import scrape_website

                async def _scrape_progress(pages: int, total: int) -> None:
                    await _update_run(
                        sb,
                        run_id,
                        progress={
                            "stage": "stage_0_scrape",
                            "percent": min(95, int(pages / max(total, 1) * 100)),
                            "message": f"Scraped {pages} pages...",
                        },
                    )

                scraped_count = await scrape_website(
                    client_id=client_id,
                    website_url=website_url,
                    progress_callback=_scrape_progress,
                )
                source_summary["scraped_pages"] = scraped_count

                # Re-gather uploads to include newly scraped pages
                scrape_result = await (
                    sb.table("spark_uploads")
                    .select("id, parsed_text, original_name, source_type")
                    .eq("client_id", str(client_id))
                    .eq("status", "parsed")
                    .eq("source_type", "scrape")
                    .execute()
                )
                scraped_uploads = scrape_result.data or []
                sources["uploads"] = (sources.get("uploads") or []) + scraped_uploads
                sources["upload_count"] = len(sources.get("uploads", []))

                # Embed scraped pages into spark_documents
                scrape_embed_count = 0
                for upload in scraped_uploads:
                    parsed = upload.get("parsed_text")
                    if not parsed:
                        continue
                    try:
                        inserted = await ingest_text(
                            client_id=client_id,
                            content=parsed,
                            title=upload.get("original_name"),
                            source_type="scrape",
                        )
                        scrape_embed_count += inserted
                    except Exception as e:
                        logger.warning(
                            "Failed to embed scraped page %s: %s",
                            upload.get("id"), e,
                        )

                logger.info(
                    "Embedded %d chunks from %d scraped pages",
                    scrape_embed_count, scraped_count,
                )

                await _update_run(
                    sb,
                    run_id,
                    source_summary=source_summary,
                    progress={"stage": "stage_0_scrape", "percent": 100, "message": f"Scraped {scraped_count} pages, embedded {scrape_embed_count} chunks"},
                )
            else:
                logger.warning("Scrape requested but no website_url configured for client %s", client_id)
                await _update_run(
                    sb,
                    run_id,
                    progress={"stage": "stage_0_scrape", "percent": 100, "message": "No website URL configured"},
                )

        if await _is_cancelled(sb, run_id):
            await _mark_cancelled(sb, run_id)
            return

        # ── Stage 1: Classification ──────────────────────────────
        await _update_run(
            sb,
            run_id,
            status="stage_1",
            progress={"stage": "stage_1", "percent": 0, "message": "Classifying content..."},
        )

        from app.services.spark.classifier import classify_sources

        async def _classify_progress(current: int, total: int, message: str) -> None:
            await _update_run(
                sb,
                run_id,
                progress={
                    "stage": "stage_1",
                    "percent": int(current / max(total, 1) * 100),
                    "message": message,
                },
            )

        classified_chunks = await classify_sources(
            client_id=client_id,
            run_id=run_id,
            sources=sources,
            progress_callback=_classify_progress,
        )

        await _update_run(
            sb,
            run_id,
            progress={
                "stage": "stage_1",
                "percent": 100,
                "message": f"Classified {len(classified_chunks)} chunks",
            },
        )

        if await _is_cancelled(sb, run_id):
            await _mark_cancelled(sb, run_id)
            return

        # ── Stage 2: Cross-reference ─────────────────────────────
        await _update_run(
            sb,
            run_id,
            status="stage_2",
            progress={"stage": "stage_2", "percent": 0, "message": "Cross-referencing..."},
        )

        from app.services.spark.alignment import cross_reference

        async def _crossref_progress(current: int, total: int, message: str) -> None:
            await _update_run(
                sb,
                run_id,
                progress={
                    "stage": "stage_2",
                    "percent": int(current / max(total, 1) * 100),
                    "message": message,
                },
            )

        alignment_findings = await cross_reference(
            client_id=client_id,
            run_id=run_id,
            classified_chunks=classified_chunks,
            progress_callback=_crossref_progress,
        )

        await _update_run(
            sb,
            run_id,
            progress={
                "stage": "stage_2",
                "percent": 100,
                "message": f"Cross-reference complete: {len(alignment_findings)} findings",
            },
        )

        if await _is_cancelled(sb, run_id):
            await _mark_cancelled(sb, run_id)
            return

        # ── Stage 3: Extraction ──────────────────────────────────
        await _update_run(
            sb,
            run_id,
            status="stage_3",
            progress={"stage": "stage_3", "percent": 0, "message": "Extracting profiles..."},
        )

        from app.services.spark.extractor import extract_artifacts

        async def _extract_progress(current: int, total: int, message: str) -> None:
            await _update_run(
                sb,
                run_id,
                progress={
                    "stage": "stage_3",
                    "percent": int(current / max(total, 1) * 100),
                    "message": message,
                },
            )

        extraction_result = await extract_artifacts(
            client_id=client_id,
            run_id=run_id,
            classified_chunks=classified_chunks,
            alignment_findings=alignment_findings,
            progress_callback=_extract_progress,
        )

        await _update_run(
            sb,
            run_id,
            progress={
                "stage": "stage_3",
                "percent": 100,
                "message": (
                    f"Extraction complete: {extraction_result['profiles_created']} profiles, "
                    f"{extraction_result['kb_items_created']} KB items"
                ),
            },
        )

        # ── Complete ────────────────────────────────────────────
        await _update_run(
            sb,
            run_id,
            status="completed",
            progress={"stage": "completed", "percent": 100, "message": "Pipeline complete"},
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info("Pipeline run %s completed for client %s", run_id, client_id)

    except Exception as e:
        logger.exception("Pipeline run %s failed", run_id)
        try:
            await _update_run(
                sb,
                run_id,
                status="failed",
                error_message=str(e)[:500],
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            logger.exception("Failed to mark pipeline run %s as failed", run_id)

    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


# ── Helpers ─────────────────────────────────────────────────────────


async def _heartbeat_loop(run_id: UUID) -> None:
    """Update last_heartbeat every 30 seconds."""
    sb = await get_supabase_client()
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
        try:
            await (
                sb.table("spark_pipeline_runs")
                .update({"last_heartbeat": datetime.now(timezone.utc).isoformat()})
                .eq("id", str(run_id))
                .execute()
            )
        except Exception:
            logger.warning("Heartbeat update failed for run %s", run_id, exc_info=True)


async def _update_run(
    sb: Any,
    run_id: UUID,
    **fields: Any,
) -> None:
    """Update fields on a pipeline run row."""
    if "last_heartbeat" not in fields:
        fields["last_heartbeat"] = datetime.now(timezone.utc).isoformat()

    await (
        sb.table("spark_pipeline_runs")
        .update(fields)
        .eq("id", str(run_id))
        .execute()
    )


async def _is_cancelled(sb: Any, run_id: UUID) -> bool:
    """Check if a pipeline run has been cancelled."""
    result = await (
        sb.table("spark_pipeline_runs")
        .select("cancelled")
        .eq("id", str(run_id))
        .limit(1)
        .execute()
    )
    if result.data:
        return bool(result.data[0].get("cancelled"))
    return False


async def _mark_cancelled(sb: Any, run_id: UUID) -> None:
    """Mark a pipeline run as cancelled."""
    logger.info("Pipeline run %s cancelled by user", run_id)
    await _update_run(
        sb,
        run_id,
        status="cancelled",
        progress={"stage": "cancelled", "percent": 0, "message": "Cancelled by user"},
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


async def _gather_sources(
    client_id: UUID,
    include_uploads: bool = True,
    include_paste: bool = True,
    include_questionnaire: bool = True,
) -> dict[str, Any]:
    """Gather all source material for pipeline processing.

    Returns a dict with source counts and content for downstream stages.
    """
    sb = await get_supabase_client()
    sources: dict[str, Any] = {
        "upload_count": 0,
        "paste_count": 0,
        "has_questionnaire": False,
        "uploads": [],
        "paste_items": [],
        "questionnaire_text": "",
    }

    if include_uploads:
        result = await (
            sb.table("spark_uploads")
            .select("id, parsed_text, original_name, source_type")
            .eq("client_id", str(client_id))
            .eq("status", "parsed")
            .execute()
        )
        sources["uploads"] = result.data or []
        sources["upload_count"] = len(sources["uploads"])

    if include_paste:
        result = await (
            sb.table("spark_paste_items")
            .select("id, content, title")
            .eq("client_id", str(client_id))
            .execute()
        )
        sources["paste_items"] = result.data or []
        sources["paste_count"] = len(sources["paste_items"])

    if include_questionnaire:
        result = await (
            sb.table("spark_clients")
            .select("onboarding_data")
            .eq("id", str(client_id))
            .limit(1)
            .execute()
        )
        if result.data:
            ob_data = result.data[0].get("onboarding_data") or {}
            if ob_data:
                sources["has_questionnaire"] = True
                sources["questionnaire_text"] = _flatten_questionnaire(ob_data)

    return sources


def _flatten_questionnaire(data: dict[str, Any]) -> str:
    """Flatten onboarding questionnaire data into plain text."""
    parts: list[str] = []

    for section_key in ("purpose_story", "values_culture", "brand_voice", "procedures_policies"):
        section = data.get(section_key)
        if isinstance(section, dict):
            for key, val in section.items():
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                if val:
                    # Convert key like "a1_why_started" to "Why Started"
                    label = key.split("_", 1)[-1].replace("_", " ").title() if "_" in key else key
                    parts.append(f"{label}: {val}")

    # Customer profiles
    customers = data.get("customers")
    if isinstance(customers, list):
        for i, c in enumerate(customers, 1):
            if isinstance(c, dict):
                name = c.get("name", f"Customer {i}")
                desc = c.get("description", "")
                signals = c.get("signals", "")
                needs = c.get("needs", "")
                parts.append(f"Customer Profile - {name}: {desc}. Signals: {signals}. Needs: {needs}")

    # Additional context
    additional = data.get("additional_context")
    if additional:
        parts.append(f"Additional Context: {additional}")

    return "\n".join(parts)
