"""
Tests for Spark Settling Layer — timezone-aware timestamp generation.

Covers:
- Timestamp uses client timezone when set
- Timestamp defaults to UTC when no timezone configured
- Invalid timezone in config falls back to UTC
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.spark.settling import build_system_prompt, clear_template_cache


# A minimal template that only needs {timestamp} — avoids loading from disk
_MINIMAL_TEMPLATE = (
    "{timestamp}\n"
    "{company_name}\n"
    "{company_description}\n"
    "{turn_awareness}\n"
    "{scope_notes}\n"
    "{doc_context}\n"
    "{lead_capture_instructions}\n"
    "{boundary_instructions}\n"
    "{custom_instructions}"
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_template_cache()


def _build(settling_config: dict) -> str:  # type: ignore[type-arg]
    """Call build_system_prompt with minimal args, return the result."""
    with patch(
        "app.services.spark.settling._load_template", return_value=_MINIMAL_TEMPLATE
    ):
        return build_system_prompt(
            settling_config=settling_config,
            retrieved_chunks=[],
            turn_count=1,
            max_turns=20,
            wind_down=False,
        )


@pytest.mark.unit
class TestSettlingTimezone:
    """Timezone handling in build_system_prompt."""

    def test_defaults_to_utc(self) -> None:
        result = _build({})
        # Should contain "UTC" in the timestamp line
        first_line = result.split("\n")[0]
        assert "UTC" in first_line

    def test_uses_client_timezone(self) -> None:
        result = _build({"timezone": "America/New_York"})
        first_line = result.split("\n")[0]
        # Should contain an Eastern abbreviation (EST or EDT depending on date)
        assert "ET" in first_line or "ES" in first_line or "ED" in first_line

    def test_uses_pacific_timezone(self) -> None:
        result = _build({"timezone": "America/Los_Angeles"})
        first_line = result.split("\n")[0]
        assert "PT" in first_line or "PS" in first_line or "PD" in first_line

    def test_invalid_timezone_falls_back_to_utc(self) -> None:
        result = _build({"timezone": "Not/A/Timezone"})
        first_line = result.split("\n")[0]
        assert "UTC" in first_line

    def test_empty_timezone_defaults_to_utc(self) -> None:
        result = _build({"timezone": ""})
        # Empty string is not a valid timezone — should fall back
        first_line = result.split("\n")[0]
        assert "UTC" in first_line

    def test_timestamp_format_structure(self) -> None:
        result = _build({"timezone": "UTC"})
        first_line = result.split("\n")[0]
        # Should start with "It is" and contain day/date/time
        assert first_line.startswith("It is ")
        assert "at" in first_line
