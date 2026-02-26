"""
Tests for Spark Settling Layer — timezone-aware timestamp generation.

Covers:
- Timestamp uses client timezone when set
- Timestamp defaults to UTC when no timezone configured
- Invalid timezone in config falls back to UTC
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.spark.settling import (
    _estimate_tokens,
    _trim_component,
    _trim_to_budget,
    build_system_prompt,
    clear_template_cache,
)


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


# ── Token budget and priority trimming tests ────────────────────────


@pytest.mark.unit
class TestEstimateTokens:
    """Token estimation via char/4 approximation."""

    def test_estimate_tokens(self) -> None:
        """char_count // 4"""
        assert _estimate_tokens("") == 0
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 400) == 100


@pytest.mark.unit
class TestTrimComponent:
    """Component trimming with clean boundary detection."""

    def test_trim_component_under_budget(self) -> None:
        """Text under budget returned unchanged."""
        text = "Short text."
        assert _trim_component(text, 1000) == text

    def test_trim_component_paragraph_boundary(self) -> None:
        """Truncates on paragraph boundary when possible."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph that is long."
        result = _trim_component(text, 40)
        assert result == "First paragraph.\n\nSecond paragraph."

    def test_trim_component_sentence_boundary(self) -> None:
        """Falls back to sentence boundary when no paragraph break fits."""
        text = "First sentence. Second sentence. Third sentence is very long."
        result = _trim_component(text, 35)
        assert result == "First sentence. Second sentence."

    def test_trim_component_hard_truncate(self) -> None:
        """Hard truncates with ... when no clean boundary available."""
        text = "a" * 200
        result = _trim_component(text, 50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")


@pytest.mark.unit
class TestTrimToBudget:
    """Budget enforcement across prioritized components."""

    def test_trim_to_budget_under_budget(self) -> None:
        """All components under budget returned unchanged."""
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 400),   # 100 tokens
            ("doc_context", 4, "y" * 400),    # 100 tokens
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "x" * 400
        assert result["doc_context"] == "y" * 400

    def test_trim_to_budget_p4_trimmed_first(self) -> None:
        """P4 components trimmed before P3."""
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 20000),     # 5000 tokens (P1 - never trim)
            ("procedures", 3, "y" * 12000),       # 3000 tokens (P3)
            ("doc_context", 4, "z" * 28000),      # 7000 tokens (P4) — total 15000, over 12000
        ]
        result = _trim_to_budget(components)
        # P1 untouched
        assert result["orientation"] == "x" * 20000
        # P3 should be untouched or less trimmed than P4
        # P4 should be trimmed
        assert len(result["doc_context"]) < 28000

    def test_trim_to_budget_p1_p2_never_trimmed(self) -> None:
        """P1 and P2 components are never trimmed even when over budget."""
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 60000),      # 15000 tokens — over budget alone
            ("boundaries", 2, "y" * 4000),         # 1000 tokens
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "x" * 60000
        assert result["boundaries"] == "y" * 4000

    def test_trim_to_budget_empty_components(self) -> None:
        """Empty content handled gracefully."""
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "Some text"),
            ("voice_examples", 3, ""),
            ("doc_context", 4, ""),
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "Some text"
        assert result["voice_examples"] == ""
        assert result["doc_context"] == ""


# ── Orientation resolution tests ─────────────────────────────────────


@pytest.mark.unit
class TestOrientationResolution:
    """Orientation text from DB vs template fallback."""

    def test_orientation_text_used_directly(self) -> None:
        """When orientation_text is provided, _load_template() is not called."""
        custom_orientation = (
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
        mock_load = MagicMock(return_value=_MINIMAL_TEMPLATE)
        with patch("app.services.spark.settling._load_template", mock_load):
            result = build_system_prompt(
                settling_config={"company_name": "CustomCo"},
                retrieved_chunks=[],
                turn_count=1,
                max_turns=20,
                wind_down=False,
                orientation_text=custom_orientation,
            )
        mock_load.assert_not_called()
        assert "CustomCo" in result

    def test_orientation_text_none_falls_back(self) -> None:
        """When orientation_text is None, falls back to template."""
        mock_load = MagicMock(return_value=_MINIMAL_TEMPLATE)
        with patch("app.services.spark.settling._load_template", mock_load):
            build_system_prompt(
                settling_config={},
                retrieved_chunks=[],
                turn_count=1,
                max_turns=20,
                wind_down=False,
                orientation_text=None,
            )
        mock_load.assert_called_once()

    def test_orientation_text_empty_falls_back(self) -> None:
        """When orientation_text is empty string, falls back to template."""
        mock_load = MagicMock(return_value=_MINIMAL_TEMPLATE)
        with patch("app.services.spark.settling._load_template", mock_load):
            build_system_prompt(
                settling_config={},
                retrieved_chunks=[],
                turn_count=1,
                max_turns=20,
                wind_down=False,
                orientation_text="",
            )
        mock_load.assert_called_once()

    def test_orientation_text_template_vars_replaced(self) -> None:
        """Orientation text from DB still gets variable substitution."""
        custom_orientation = "You work for {company_name}. {doc_context}"
        with patch("app.services.spark.settling._load_template") as mock_load:
            result = build_system_prompt(
                settling_config={"company_name": "AcmeCorp"},
                retrieved_chunks=[],
                turn_count=1,
                max_turns=20,
                wind_down=False,
                orientation_text=custom_orientation,
            )
        mock_load.assert_not_called()
        assert "AcmeCorp" in result
        assert "{company_name}" not in result


# ── Token budget integration in build_system_prompt ──────────────────


@pytest.mark.unit
class TestBuildSystemPromptBudget:
    """Budget trimming is applied to doc_context inside build_system_prompt."""

    def test_token_budget_trims_doc_context(self) -> None:
        """Doc context (P4) is trimmed when total exceeds budget."""
        # Build a large doc context via retrieved_chunks
        large_chunks = [
            {"title": f"Doc {i}", "content": "word " * 5000}
            for i in range(20)
        ]
        with patch(
            "app.services.spark.settling._load_template",
            return_value=_MINIMAL_TEMPLATE,
        ):
            result = build_system_prompt(
                settling_config={},
                retrieved_chunks=large_chunks,
                turn_count=1,
                max_turns=20,
                wind_down=False,
            )
        # The result should exist and be shorter than if we'd included
        # all 20 chunks * 5000 words untrimmed
        assert len(result) > 0
        # 20 chunks * "word " * 5000 = 500,000 chars untrimmed
        # Budget is 12,000 tokens * 4 chars = 48,000 chars
        # The result should be well under the untrimmed size
        assert len(result) < 500_000
