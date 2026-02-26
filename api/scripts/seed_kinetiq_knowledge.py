"""
Seed KinetIQ demo knowledge items from markdown files.

Reads all .md files from seeds/kinetiq/, parses YAML frontmatter + content body,
hashes, embeds, and upserts into spark_knowledge_items. Safe to re-run (dedup
via content_hash). Also sets the demo client's orientation_template to "kinetiq".

Usage:
    cd staging/kin-spark/api
    python3 -m scripts.seed_kinetiq_knowledge --client-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import Any

# Ensure app imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.embeddings import create_embedding  # noqa: E402
from app.services.supabase import get_supabase_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).resolve().parents[1] / "seeds" / "kinetiq"

# Simple YAML frontmatter parser (avoids pyyaml dependency)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and return (metadata, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    meta_raw = match.group(1)
    body = text[match.end() :].strip()

    # Simple key: value parsing (no nested YAML needed)
    meta: dict[str, Any] = {}
    for line in meta_raw.strip().split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Type coercion
            if value.isdigit():
                meta[key] = int(value)
            elif value.lower() in ("true", "false"):
                meta[key] = value.lower() == "true"
            else:
                meta[key] = value

    return meta, body


def _content_hash(content: str) -> str:
    """SHA-256 hash of content for deduplication."""
    return hashlib.sha256(content.encode()).hexdigest()


async def seed(client_id: str) -> None:
    """Seed all knowledge items from markdown files."""
    if not _SEEDS_DIR.exists():
        logger.error("Seeds directory not found: %s", _SEEDS_DIR)
        return

    md_files = sorted(_SEEDS_DIR.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", _SEEDS_DIR)
        return

    logger.info("Found %d seed files in %s", len(md_files), _SEEDS_DIR)

    sb = await get_supabase_client()

    # Get existing hashes for this client
    existing_result = await (
        sb.table("spark_knowledge_items")
        .select("content_hash")
        .eq("client_id", client_id)
        .execute()
    )
    existing_hashes = {r["content_hash"] for r in (existing_result.data or [])}

    created = 0
    skipped = 0

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)

        if not body:
            logger.warning("Skipping empty file: %s", md_file.name)
            continue

        title = meta.get("title", md_file.stem.replace("-", " ").title())
        category = meta.get("category", "company")
        subcategory = meta.get("subcategory")
        priority = meta.get("priority", 0)

        content_h = _content_hash(body)

        if content_h in existing_hashes:
            logger.info("  Skip (exists): %s", title)
            skipped += 1
            continue

        # Embed
        logger.info("  Embedding: %s", title)
        embedding = await create_embedding(body, input_type="document")

        row = {
            "client_id": client_id,
            "title": title,
            "content": body,
            "category": category,
            "subcategory": subcategory,
            "priority": priority,
            "active": True,
            "embedding": embedding,
            "embedding_model": settings.embedding_model,
            "content_hash": content_h,
        }

        try:
            await sb.table("spark_knowledge_items").insert(row).execute()
            created += 1
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                logger.info("  Skip (duplicate): %s", title)
                skipped += 1
            else:
                logger.error("  Failed to insert %s: %s", title, e)

    logger.info(
        "Seed complete: %d created, %d skipped (already existed)", created, skipped
    )

    # Update demo client settling_config to use kinetiq orientation
    logger.info("Setting orientation_template to 'kinetiq' for client %s", client_id)
    try:
        # Fetch current settling_config
        client_result = await (
            sb.table("spark_clients")
            .select("settling_config")
            .eq("id", client_id)
            .limit(1)
            .execute()
        )
        if client_result.data:
            config = client_result.data[0].get("settling_config", {}) or {}
            config["orientation_template"] = "kinetiq"
            await (
                sb.table("spark_clients")
                .update({"settling_config": config})
                .eq("id", client_id)
                .execute()
            )
            logger.info("Client settling_config updated.")
        else:
            logger.warning("Client %s not found — skipping config update.", client_id)
    except Exception as e:
        logger.error("Failed to update client config: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed KinetIQ knowledge items")
    parser.add_argument(
        "--client-id",
        required=True,
        help="UUID of the Spark client to seed",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.client_id))


if __name__ == "__main__":
    main()
