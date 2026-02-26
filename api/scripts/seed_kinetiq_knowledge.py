"""
Seed KinetIQ demo knowledge items from markdown files.

Reads all .md files from seeds/kinetiq/, parses YAML frontmatter + content body,
hashes, embeds, and upserts into spark_knowledge_items. Safe to re-run (dedup
via content_hash). Also sets the demo client's orientation_template to "kinetiq".

Usage:
    cd staging/kin-spark/api
    # From individual seed files:
    python3 -m scripts.seed_kinetiq_knowledge --client-id <uuid>
    # From a compiled knowledge base markdown:
    python3 -m scripts.seed_kinetiq_knowledge --client-id <uuid> --from-compiled path/to/kb.md
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


# Header pattern: "## Category / Subcategory" or "## Category"
_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)(?:\s*/\s*(.+))?\s*$", re.MULTILINE)

# Inline metadata: "Category: foo | Subcategory: bar" or "**Category: foo | Subcategory: bar**"
_INLINE_META_RE = re.compile(
    r"\*{0,2}Category:\s*(\w+)\s*\|\s*Subcategory:\s*(\w+)\*{0,2}",
    re.IGNORECASE,
)

# Bold title line: "**Some Title**"
_BOLD_TITLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*$", re.MULTILINE)


# Category name normalisation: lowercase, spaces/hyphens to underscores
_KNOWN_CATEGORIES = {
    "company",
    "product",
    "competitor",
    "legal",
    "team",
    "fun",
    "customer_profile",
    "procedure",
    "faq",
    "industry",
}


def _normalise_category(raw: str) -> str:
    """Map a section-header category to a valid DB category value."""
    norm = raw.strip().lower().replace(" ", "_").replace("-", "_")
    # Map known aliases
    aliases: dict[str, str] = {
        "in_development": "product",
        "industry_context": "competitor",
        "industry": "competitor",
        "objection_handling_&_faqs": "product",
        "objection_handling___faqs": "product",
        "use_cases": "product",
        "faq": "product",
    }
    if norm in aliases:
        return aliases[norm]
    if norm in _KNOWN_CATEGORIES:
        return norm
    # Default fallback
    return "company"


def _parse_compiled_sections(text: str) -> list[dict[str, Any]]:
    """Parse a compiled knowledge base markdown into section dicts.

    The compiled file uses ``* * *`` horizontal rules to separate sections.
    Each section has a ``## Category / Subcategory`` header, an optional bold
    title, and body content.  Some sections carry inline metadata in the form
    ``Category: X | Subcategory: Y``.
    """
    # Split on the "* * *" separator (with optional leading/trailing whitespace)
    raw_sections = re.split(r"\n\s*\*\s+\*\s+\*\s*\n", text)

    items: list[dict[str, Any]] = []

    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        category = "company"
        subcategory: str | None = None
        title: str | None = None

        # Try to extract ## header
        header_match = _SECTION_HEADER_RE.search(section)
        if header_match:
            category = _normalise_category(header_match.group(1))
            if header_match.group(2):
                subcategory = header_match.group(2).strip().lower().replace(" ", "_")

        # Check for inline metadata (overrides header if present)
        inline_match = _INLINE_META_RE.search(section)
        if inline_match:
            category = _normalise_category(inline_match.group(1))
            subcategory = inline_match.group(2).strip().lower()

        # Extract bold title (first bold line after the header)
        bold_match = _BOLD_TITLE_RE.search(section)
        if bold_match:
            title = bold_match.group(1).strip()

        # Build body: strip the header line and the bold title, keep the rest
        body_lines: list[str] = []
        for line in section.split("\n"):
            # Skip the ## header line
            if _SECTION_HEADER_RE.match(line):
                continue
            # Skip inline metadata lines
            if _INLINE_META_RE.search(line):
                continue
            body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if not body:
            continue

        # Fallback title from header if no bold title found
        if not title and header_match:
            parts = [header_match.group(1)]
            if header_match.group(2):
                parts.append(header_match.group(2))
            title = " — ".join(parts)

        if not title:
            title = "Untitled Section"

        items.append(
            {
                "title": title,
                "category": category,
                "subcategory": subcategory,
                "body": body,
            }
        )

    return items


async def seed_from_compiled(client_id: str, compiled_path: str) -> None:
    """Seed knowledge items from a compiled knowledge base markdown file."""
    path = Path(compiled_path)
    if not path.exists():
        logger.error("Compiled file not found: %s", path)
        return

    text = path.read_text(encoding="utf-8")
    sections = _parse_compiled_sections(text)

    if not sections:
        logger.warning("No sections parsed from %s", path)
        return

    logger.info("Parsed %d sections from %s", len(sections), path.name)

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

    for section in sections:
        body = section["body"]
        content_h = _content_hash(body)

        if content_h in existing_hashes:
            logger.info("  Skip (exists): %s", section["title"])
            skipped += 1
            continue

        logger.info("  Embedding: %s", section["title"])
        embedding = await create_embedding(body, input_type="document")

        row = {
            "client_id": client_id,
            "title": section["title"],
            "content": body,
            "category": section["category"],
            "subcategory": section["subcategory"],
            "priority": 0,
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
                logger.info("  Skip (duplicate): %s", section["title"])
                skipped += 1
            else:
                logger.error("  Failed to insert %s: %s", section["title"], e)

    logger.info(
        "Seed complete: %d created, %d skipped (already existed)", created, skipped
    )


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
    parser.add_argument(
        "--from-compiled",
        default=None,
        metavar="FILE",
        help="Path to a compiled knowledge base markdown file. "
        "Parses sections separated by '* * *' rules. "
        "If omitted, seeds from individual files in seeds/kinetiq/.",
    )
    args = parser.parse_args()

    if args.from_compiled:
        asyncio.run(seed_from_compiled(args.client_id, args.from_compiled))
    else:
        asyncio.run(seed(args.client_id))


if __name__ == "__main__":
    main()
