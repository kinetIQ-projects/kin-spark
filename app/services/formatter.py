"""
Format Normalizer — Lightweight markdown cleanup for Spark responses.

Pure function, no LLM calls, no DB, sub-10ms.
"""

from __future__ import annotations

import re


def normalize_format(raw_response: str) -> str:
    """Clean up LLM response formatting.

    Strips excessive markdown decoration that feels robotic in a chat widget.
    """
    if not raw_response or not raw_response.strip():
        return raw_response

    text = raw_response

    # Remove heading markers in short responses (chat doesn't need them)
    if len(text) < 500:
        text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)

    # Collapse triple+ newlines to double
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip trailing whitespace per line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

    return text.strip()
