"""
Ingestion Router — File uploads, paste items, and pipeline management.

Mounted at /spark/admin/ingestion in main.py.
Uses the same admin JWT auth as admin.py.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.models.ingestion import (
    FileUploadOut,
    PasteItemCreate,
    PasteItemOut,
    PipelineRunOut,
    PipelineTriggerRequest,
    PresignRequest,
    PresignResponse,
    ProfileChangeRequest,
    ProfileOut,
    ProfileUpdate,
    WebsiteUrlOut,
    WebsiteUrlUpdate,
)
from app.models.spark import SparkClient
from app.services.spark.admin_auth import verify_admin_jwt
from app.services.spark.uploads import (
    confirm_upload,
    delete_upload,
    list_uploads,
    presign_upload,
)
from app.services.spark.parsing import parse_upload
from app.services.spark.pipeline import run_pipeline
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Rate limiter (reuse pattern from admin.py) ──────────────────────

_rate_limiter: dict[str, list[float]] = {}


async def _rate_limit(request: Request, client: SparkClient = Depends(verify_admin_jwt)) -> None:
    """Simple per-client rate limiter for ingestion endpoints."""
    import time

    key = str(client.id)
    now = time.time()
    window = _rate_limiter.setdefault(key, [])
    # Clean old entries (1-minute window)
    _rate_limiter[key] = [t for t in window if now - t < 60]
    if len(_rate_limiter[key]) >= 60:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_limiter[key].append(now)


# ═════════════════════════════════════════════════════════════════════
# UPLOADS
# ═════════════════════════════════════════════════════════════════════


@router.post("/uploads/presign", response_model=PresignResponse)
async def presign(
    body: PresignRequest,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> PresignResponse:
    """Validate an upload and create a tracking row.

    Returns {upload_id, storage_path} for the portal to upload the
    file directly to Supabase Storage.
    """
    result = await presign_upload(
        client_id=client.id,
        filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
    )
    return PresignResponse(
        upload_id=UUID(result["upload_id"]),
        storage_path=result["storage_path"],
    )


@router.post("/uploads/{upload_id}/confirm", response_model=FileUploadOut)
async def confirm(
    upload_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> FileUploadOut:
    """Confirm an upload (file is in storage) and trigger parsing."""
    row = await confirm_upload(client.id, upload_id)

    # Trigger parsing in background
    background_tasks.add_task(parse_upload, upload_id, client.id)

    # Mark as parsing so the response reflects the new status
    sb = await get_supabase_client()
    await (
        sb.table("spark_uploads")
        .update({"status": "parsing"})
        .eq("id", str(upload_id))
        .eq("client_id", str(client.id))
        .execute()
    )
    row["status"] = "parsing"

    return FileUploadOut(**row)


@router.get("/uploads", response_model=list[FileUploadOut])
async def get_uploads(
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> list[FileUploadOut]:
    """List all uploads for the authenticated client."""
    rows = await list_uploads(client.id)
    return [FileUploadOut(**r) for r in rows]


@router.delete("/uploads/{upload_id}", status_code=204)
async def remove_upload(
    upload_id: UUID,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> None:
    """Delete an upload and its storage file."""
    await delete_upload(client.id, upload_id)


# ═════════════════════════════════════════════════════════════════════
# PASTE ITEMS
# ═════════════════════════════════════════════════════════════════════


@router.post("/paste", response_model=PasteItemOut, status_code=201)
async def create_paste(
    body: PasteItemCreate,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> PasteItemOut:
    """Submit pasted text for ingestion."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_paste_items")
        .insert(
            {
                "client_id": str(client.id),
                "content": body.content,
                "title": body.title,
            }
        )
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create paste item")

    return PasteItemOut(**result.data[0])


@router.get("/paste", response_model=list[PasteItemOut])
async def get_pastes(
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> list[PasteItemOut]:
    """List all paste items for the authenticated client."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_paste_items")
        .select("*")
        .eq("client_id", str(client.id))
        .order("created_at", desc=True)
        .execute()
    )
    return [PasteItemOut(**r) for r in (result.data or [])]


@router.delete("/paste/{paste_id}", status_code=204)
async def remove_paste(
    paste_id: UUID,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> None:
    """Delete a paste item."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_paste_items")
        .delete()
        .eq("id", str(paste_id))
        .eq("client_id", str(client.id))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Paste item not found")


# ═════════════════════════════════════════════════════════════════════
# WEBSITE URL
# ═════════════════════════════════════════════════════════════════════


@router.get("/website-url", response_model=WebsiteUrlOut)
async def get_website_url(
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> WebsiteUrlOut:
    """Get the client's configured website URL."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_clients")
        .select("website_url")
        .eq("id", str(client.id))
        .limit(1)
        .execute()
    )
    url = result.data[0].get("website_url") if result.data else None
    return WebsiteUrlOut(website_url=url)


@router.put("/website-url", response_model=WebsiteUrlOut)
async def set_website_url(
    body: WebsiteUrlUpdate,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> WebsiteUrlOut:
    """Set the client's website URL for scraping."""
    sb = await get_supabase_client()
    await (
        sb.table("spark_clients")
        .update({"website_url": body.website_url})
        .eq("id", str(client.id))
        .execute()
    )
    return WebsiteUrlOut(website_url=body.website_url)


# ═════════════════════════════════════════════════════════════════════
# PIPELINE RUNS
# ═════════════════════════════════════════════════════════════════════

# Terminal statuses — no active pipeline in these states
_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


@router.post("/run", response_model=PipelineRunOut, status_code=201)
async def trigger_pipeline(
    body: PipelineTriggerRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> PipelineRunOut:
    """Create a pipeline run and trigger execution.

    Rejects with 409 if an active run already exists for this client.
    """
    sb = await get_supabase_client()

    # Check for active runs
    active = await (
        sb.table("spark_pipeline_runs")
        .select("id")
        .eq("client_id", str(client.id))
        .not_.in_("status", _TERMINAL_STATUSES)
        .limit(1)
        .execute()
    )

    if active.data:
        raise HTTPException(
            status_code=409,
            detail="An active pipeline run already exists for this client",
        )

    # Create the run
    result = await (
        sb.table("spark_pipeline_runs")
        .insert(
            {
                "client_id": str(client.id),
                "status": "pending",
                "trigger_type": body.trigger_type,
            }
        )
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create pipeline run")

    run_row = result.data[0]
    run_id = UUID(run_row["id"])

    # Trigger pipeline in background
    background_tasks.add_task(
        run_pipeline,
        run_id,
        client.id,
        body.include_uploads,
        body.include_paste,
        body.include_questionnaire,
        body.include_scrape,
    )

    return PipelineRunOut(**run_row)


@router.get("/runs", response_model=list[PipelineRunOut])
async def get_runs(
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> list[PipelineRunOut]:
    """List all pipeline runs for the authenticated client."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_pipeline_runs")
        .select("*")
        .eq("client_id", str(client.id))
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return [PipelineRunOut(**r) for r in (result.data or [])]


@router.get("/runs/{run_id}", response_model=PipelineRunOut)
async def get_run(
    run_id: UUID,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> PipelineRunOut:
    """Get a single pipeline run (for progress polling)."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_pipeline_runs")
        .select("*")
        .eq("id", str(run_id))
        .eq("client_id", str(client.id))
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    return PipelineRunOut(**result.data[0])


@router.post("/runs/{run_id}/cancel", status_code=200)
async def cancel_run(
    run_id: UUID,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> dict[str, str]:
    """Request cancellation of a pipeline run.

    Sets cancelled=true. The pipeline checks this flag between stages.
    """
    sb = await get_supabase_client()

    # Verify the run exists and belongs to this client
    result = await (
        sb.table("spark_pipeline_runs")
        .select("id, status")
        .eq("id", str(run_id))
        .eq("client_id", str(client.id))
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    row = result.data[0]
    if row["status"] in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a run in status: {row['status']}",
        )

    await (
        sb.table("spark_pipeline_runs")
        .update({"cancelled": True})
        .eq("id", str(run_id))
        .eq("client_id", str(client.id))
        .execute()
    )

    return {"status": "cancellation_requested"}


# ═════════════════════════════════════════════════════════════════════
# PROFILES
# ═════════════════════════════════════════════════════════════════════


@router.get("/profiles", response_model=list[ProfileOut])
async def get_profiles(
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> list[ProfileOut]:
    """List the latest version of each profile type for the client."""
    sb = await get_supabase_client()

    # Get all profiles for this client, ordered by type and version desc
    result = await (
        sb.table("spark_profiles")
        .select("*")
        .eq("client_id", str(client.id))
        .order("profile_type")
        .order("version", desc=True)
        .execute()
    )

    if not result.data:
        return []

    # Keep only the latest version per profile_type
    seen_types: set[str] = set()
    latest: list[ProfileOut] = []
    for row in result.data:
        ptype = row["profile_type"]
        if ptype not in seen_types:
            seen_types.add(ptype)
            latest.append(ProfileOut(**row))

    return latest


@router.get("/profiles/{profile_id}", response_model=ProfileOut)
async def get_profile(
    profile_id: UUID,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> ProfileOut:
    """Get a single profile by ID."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_profiles")
        .select("*")
        .eq("id", str(profile_id))
        .eq("client_id", str(client.id))
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    return ProfileOut(**result.data[0])


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
async def update_profile(
    profile_id: UUID,
    body: ProfileUpdate,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> ProfileOut:
    """Update profile status (approve/reject)."""
    sb = await get_supabase_client()

    from datetime import datetime, timezone

    # Verify ownership
    existing = await (
        sb.table("spark_profiles")
        .select("id, status")
        .eq("id", str(profile_id))
        .eq("client_id", str(client.id))
        .limit(1)
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    update_fields: dict[str, str] = {"status": body.status}
    if body.status in ("approved", "rejected"):
        update_fields["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    result = await (
        sb.table("spark_profiles")
        .update(update_fields)
        .eq("id", str(profile_id))
        .eq("client_id", str(client.id))
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update profile")

    return ProfileOut(**result.data[0])


@router.post("/profiles/{profile_id}/request-changes", response_model=ProfileOut)
async def request_profile_changes(
    profile_id: UUID,
    body: ProfileChangeRequest,
    request: Request,
    _rate: None = Depends(_rate_limit),
    client: SparkClient = Depends(verify_admin_jwt),
) -> ProfileOut:
    """Client requests changes to a profile with feedback."""
    sb = await get_supabase_client()

    from datetime import datetime, timezone

    # Verify ownership
    existing = await (
        sb.table("spark_profiles")
        .select("id, status")
        .eq("id", str(profile_id))
        .eq("client_id", str(client.id))
        .limit(1)
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    result = await (
        sb.table("spark_profiles")
        .update({
            "status": "rejected",
            "client_feedback": body.feedback,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", str(profile_id))
        .eq("client_id", str(client.id))
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update profile")

    return ProfileOut(**result.data[0])
