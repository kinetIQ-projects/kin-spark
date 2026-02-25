"""
Spark Ingestion — Document chunking, embedding, and storage.

chunk_text(): Paragraph-boundary chunking with overlap.
ingest_text(): Chunk → hash → batch embed → upsert (skip existing).
ingest_url(): Fetch → strip HTML → delete existing → ingest_text.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from uuid import UUID

import httpx

from app.services.embeddings import create_embeddings_batch
from app.services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# Chunking parameters
_CHUNK_SIZE = 1000  # ~1000 chars per chunk
_CHUNK_OVERLAP = 200  # 200-char overlap between chunks


def chunk_text(
    text: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """Split text into chunks at paragraph boundaries with overlap.

    Pure function — no side effects.
    """
    if not text or not text.strip():
        return []

    # Split on double newlines (paragraph boundaries)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        # If adding this paragraph would exceed chunk_size, finalize current
        if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(current_chunk.strip())

            # Overlap: carry tail of current chunk into next
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:] + "\n\n" + para
            else:
                current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _content_hash(content: str) -> str:
    """SHA-256 hash of chunk content for deduplication."""
    return hashlib.sha256(content.encode()).hexdigest()


async def ingest_text(
    client_id: UUID,
    content: str,
    title: str | None = None,
    source_type: str = "text",
    source_url: str | None = None,
) -> int:
    """Chunk text, embed, and store in spark_documents.

    Skips chunks whose content_hash already exists for this client.
    Returns number of chunks inserted.
    """
    chunks = chunk_text(content)
    if not chunks:
        return 0

    # Compute hashes
    hashes = [_content_hash(c) for c in chunks]

    # Check which hashes already exist
    sb = await get_supabase_client()
    existing_result = await (
        sb.table("spark_documents")
        .select("content_hash")
        .eq("client_id", str(client_id))
        .in_("content_hash", hashes)
        .execute()
    )
    existing_hashes = {r["content_hash"] for r in (existing_result.data or [])}

    # Filter to new chunks only
    new_items = [
        (i, chunk, h)
        for i, (chunk, h) in enumerate(zip(chunks, hashes))
        if h not in existing_hashes
    ]

    if not new_items:
        logger.info("Spark ingestion: all %d chunks already exist", len(chunks))
        return 0

    # Batch embed new chunks
    new_texts = [item[1] for item in new_items]
    embeddings = await create_embeddings_batch(new_texts, input_type="document")

    # Insert
    rows = []
    for (idx, chunk, h), embedding in zip(new_items, embeddings):
        rows.append(
            {
                "client_id": str(client_id),
                "content": chunk,
                "embedding": embedding,
                "title": title,
                "source_type": source_type,
                "source_url": source_url,
                "chunk_index": idx,
                "content_hash": h,
            }
        )

    await sb.table("spark_documents").insert(rows).execute()

    logger.info(
        "Spark ingestion: inserted %d chunks (skipped %d existing)",
        len(rows),
        len(chunks) - len(rows),
    )
    return len(rows)


def _strip_html(html: str) -> str:
    """Extract text from HTML, stripping scripts/styles/nav/footer."""
    # Remove script and style elements entirely
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove nav and footer elements
    text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE
    )

    # Replace block elements with newlines
    text = re.sub(r"<(?:p|div|br|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)

    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode common entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&nbsp;", " ")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")

    # Collapse whitespace
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


async def ingest_url(
    client_id: UUID,
    url: str,
    title: str | None = None,
) -> int:
    """Fetch URL content, strip HTML, delete existing chunks for URL, re-ingest.

    Returns number of chunks inserted.
    """
    # Fetch
    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.get(url, follow_redirects=True)
        response.raise_for_status()
        html = response.text

    # Strip HTML
    content = _strip_html(html)
    if not content:
        logger.warning("Spark URL ingestion: no content extracted from %s", url)
        return 0

    # Delete existing chunks for this URL (clean re-ingestion)
    sb = await get_supabase_client()
    await (
        sb.table("spark_documents")
        .delete()
        .eq("client_id", str(client_id))
        .eq("source_url", url)
        .execute()
    )

    # Ingest fresh
    return await ingest_text(
        client_id=client_id,
        content=content,
        title=title or url,
        source_type="url",
        source_url=url,
    )
