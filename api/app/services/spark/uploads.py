"""
Upload Service — Presign, confirm, list, and delete file uploads.

Handles the two-step upload flow:
  1. presign: validate + create DB row → return {upload_id, storage_path}
  2. confirm: mark upload confirmed, trigger parsing in background
"""

from __future__ import annotations

import logging
import re
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.config import settings
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# Allowed MIME types (checked on presign)
ALLOWED_MIME_TYPES = frozenset(
    t.strip() for t in settings.allowed_upload_types.split(",")
)


def _sanitize_filename(name: str) -> str:
    """Strip path components and dangerous characters from filename."""
    # Take only the basename (strip directory separators)
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    # Replace anything that isn't alphanumeric, dot, dash, underscore
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200] or "unnamed"


async def presign_upload(
    client_id: UUID,
    filename: str,
    mime_type: str,
    file_size: int,
) -> dict[str, str]:
    """Validate upload and create a tracking row.

    Returns {upload_id, storage_path} for the portal to upload directly
    to Supabase Storage.
    """
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed: {mime_type}",
        )

    if file_size > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {file_size} bytes (max {settings.max_upload_size_bytes})",
        )

    upload_id = uuid4()
    safe_name = _sanitize_filename(filename)
    storage_path = f"{client_id}/{upload_id}/{safe_name}"

    sb = await get_supabase_client()
    await sb.table("spark_uploads").insert(
        {
            "id": str(upload_id),
            "client_id": str(client_id),
            "filename": safe_name,
            "original_name": filename[:255],
            "mime_type": mime_type,
            "file_size": file_size,
            "storage_path": storage_path,
            "source_type": "upload",
            "status": "uploaded",
        }
    ).execute()

    return {"upload_id": str(upload_id), "storage_path": storage_path}


async def confirm_upload(client_id: UUID, upload_id: UUID) -> dict[str, str]:
    """Mark an upload as confirmed (file is in storage).

    Returns the upload row. Caller is responsible for triggering parsing.
    """
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_uploads")
        .select("*")
        .eq("id", str(upload_id))
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    row = result.data[0]
    if row["status"] != "uploaded":
        raise HTTPException(
            status_code=400,
            detail=f"Upload already in status: {row['status']}",
        )

    return row


async def list_uploads(client_id: UUID) -> list[dict]:
    """List all uploads for a client, newest first."""
    sb = await get_supabase_client()
    result = await (
        sb.table("spark_uploads")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


async def delete_upload(client_id: UUID, upload_id: UUID) -> None:
    """Delete an upload row and its file from storage."""
    sb = await get_supabase_client()

    # Fetch the row to get storage_path
    result = await (
        sb.table("spark_uploads")
        .select("storage_path")
        .eq("id", str(upload_id))
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    storage_path = result.data[0]["storage_path"]

    # Delete from storage (best-effort — row deletion is the important part)
    try:
        await sb.storage.from_(settings.supabase_storage_bucket).remove([storage_path])
    except Exception:
        logger.warning("Failed to delete storage file: %s", storage_path, exc_info=True)

    # Delete the DB row
    await (
        sb.table("spark_uploads")
        .delete()
        .eq("id", str(upload_id))
        .eq("client_id", str(client_id))
        .execute()
    )
