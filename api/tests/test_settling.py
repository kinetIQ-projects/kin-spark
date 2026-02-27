"""
Tests for Spark Settling Layer.

Covers:
- Timezone-aware timestamp generation
- Token budget and priority trimming
- Orientation resolution (DB vs template)
- Boundary signal formatting
- format_map handles missing placeholders gracefully
- "No docs found" strengthened message
- Calendly link in lead capture instructions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.spark.settling import (
    _estimate_tokens,
    _format_boundary_signals,
    _format_doc_context,
    _trim_component,
    _trim_to_budget,
    build_system_prompt,
    clear_template_cache,
)


# A minimal template that exercises all supported placeholders
_MINIMAL_TEMPLATE = (
    "{timestamp}\n"
    "{company_name}\n"
    "{company_description}\n"
    "{turn_awareness}\n"
    "{doc_context}\n"
    "{lead_capture_instructions}\n"
    "{boundary_signals}\n"
    "{custom_instructions}"
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_template_cache()


def _build(
    settling_config: dict | None = None,  # type: ignore[type-arg]
    boundary_signal: str | None = None,
    retrieved_chunks: list | None = None,  # type: ignore[type-arg]
    orientation_text: str | None = None,
) -> str:
    """Call build_system_prompt with minimal args, return the result."""
    with patch(
        "app.services.spark.settling._load_template", return_value=_MINIMAL_TEMPLATE
    ):
        return build_system_prompt(
            settling_config=settling_config or {},
            retrieved_chunks=retrieved_chunks or [],
            turn_count=1,
            max_turns=20,
            wind_down=False,
            boundary_signal=boundary_signal,
            orientation_text=orientation_text,
        )


# ── Timezone tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestSettlingTimezone:
    """Timezone handling in build_system_prompt."""

    def test_defaults_to_utc(self) -> None:
        result = _build()
        first_line = result.split("\n")[0]
        assert "UTC" in first_line

    def test_uses_client_timezone(self) -> None:
        result = _build({"timezone": "America/New_York"})
        first_line = result.split("\n")[0]
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
        first_line = result.split("\n")[0]
        assert "UTC" in first_line

    def test_timestamp_format_structure(self) -> None:
        result = _build({"timezone": "UTC"})
        first_line = result.split("\n")[0]
        assert first_line.startswith("It is ")
        assert "at" in first_line


# ── Token budget and priority trimming ──────────────────────────────


@pytest.mark.unit
class TestEstimateTokens:
    """Token estimation via char/4 approximation."""

    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("") == 0
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 400) == 100


@pytest.mark.unit
class TestTrimComponent:
    """Component trimming with clean boundary detection."""

    def test_trim_component_under_budget(self) -> None:
        text = "Short text."
        assert _trim_component(text, 1000) == text

    def test_trim_component_paragraph_boundary(self) -> None:
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph that is long."
        result = _trim_component(text, 40)
        assert result == "First paragraph.\n\nSecond paragraph."

    def test_trim_component_sentence_boundary(self) -> None:
        text = "First sentence. Second sentence. Third sentence is very long."
        result = _trim_component(text, 35)
        assert result == "First sentence. Second sentence."

    def test_trim_component_hard_truncate(self) -> None:
        text = "a" * 200
        result = _trim_component(text, 50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")


@pytest.mark.unit
class TestTrimToBudget:
    """Budget enforcement across prioritized components."""

    def test_under_budget_unchanged(self) -> None:
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 400),
            ("doc_context", 4, "y" * 400),
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "x" * 400
        assert result["doc_context"] == "y" * 400

    def test_p4_trimmed_first(self) -> None:
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 20000),
            ("procedures", 3, "y" * 12000),
            ("doc_context", 4, "z" * 28000),
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "x" * 20000
        assert len(result["doc_context"]) < 28000

    def test_p1_p2_never_trimmed(self) -> None:
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "x" * 60000),
            ("boundaries", 2, "y" * 4000),
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "x" * 60000
        assert result["boundaries"] == "y" * 4000

    def test_empty_components(self) -> None:
        components: list[tuple[str, int, str]] = [
            ("orientation", 1, "Some text"),
            ("voice_examples", 3, ""),
            ("doc_context", 4, ""),
        ]
        result = _trim_to_budget(components)
        assert result["orientation"] == "Some text"
        assert result["voice_examples"] == ""
        assert result["doc_context"] == ""


# ── Boundary signal formatting ──────────────────────────────────────


@pytest.mark.unit
class TestFormatBoundarySignals:
    """Boundary signal → tactical text formatting."""

    def test_none_returns_empty(self) -> None:
        assert _format_boundary_signals(None) == ""

    def test_prompt_probing(self) -> None:
        result = _format_boundary_signals("prompt_probing")
        assert "instructions" in result.lower()
        assert len(result) > 50

    def test_identity_breaking(self) -> None:
        result = _format_boundary_signals("identity_breaking")
        assert "roleplay" in result.lower() or "something other" in result.lower()

    def test_extraction_framing(self) -> None:
        result = _format_boundary_signals("extraction_framing")
        assert "developer" in result.lower() or "framing" in result.lower()

    def test_boundary_erosion(self) -> None:
        result = _format_boundary_signals("boundary_erosion")
        assert "drift" in result.lower() or "steering" in result.lower()

    def test_adversarial_stress(self) -> None:
        result = _format_boundary_signals("adversarial_stress")
        assert "reaction" in result.lower() or "pushing" in result.lower()

    def test_unknown_signal_returns_empty(self) -> None:
        assert _format_boundary_signals("unknown_signal_type") == ""


# ── Doc context formatting ──────────────────────────────────────────


@pytest.mark.unit
class TestFormatDocContext:
    """Doc context formatting and strengthened empty message."""

    def test_no_docs_returns_strengthened_message(self) -> None:
        result = _format_doc_context([])
        assert "don't have any information" in result
        assert "don't know" in result
        assert "connect them" in result

    def test_with_chunks(self) -> None:
        chunks = [{"title": "FAQ", "content": "We do X", "similarity": 0.8}]
        result = _format_doc_context(chunks)
        assert "FAQ" in result
        assert "We do X" in result


# ── Orientation resolution ──────────────────────────────────────────


@pytest.mark.unit
class TestOrientationResolution:
    """Orientation text from DB vs template fallback."""

    def test_orientation_text_used_directly(self) -> None:
        custom_orientation = _MINIMAL_TEMPLATE
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


# ── format_map handles missing placeholders ─────────────────────────


@pytest.mark.unit
class TestFormatMapGraceful:
    """format_map(defaultdict(str, ...)) resolves missing keys to empty string."""

    def test_unknown_placeholder_resolves_to_empty(self) -> None:
        """Template with {unknown_placeholder} doesn't crash."""
        template_with_unknown = "{timestamp}\n{unknown_placeholder}\n{company_name}"
        result = _build(
            settling_config={"company_name": "TestCo"},
            orientation_text=template_with_unknown,
        )
        assert "TestCo" in result
        # Unknown placeholder should be empty, not raise KeyError
        assert "{unknown_placeholder}" not in result


# ── Calendly link ───────────────────────────────────────────────────


@pytest.mark.unit
class TestCalendlyLink:
    """Calendly link in lead capture instructions."""

    def test_calendly_link_included(self) -> None:
        result = _build(
            settling_config={
                "calendly_link": "https://calendly.com/test/meeting"
            }
        )
        assert "calendly.com/test/meeting" in result

    def test_no_calendly_link(self) -> None:
        result = _build(settling_config={})
        assert "calendly" not in result.lower()


# ── Boundary signal in system prompt ────────────────────────────────


@pytest.mark.unit
class TestBoundarySignalInPrompt:
    """Boundary signals flow through to the assembled system prompt."""

    def test_boundary_signal_injected(self) -> None:
        result = _build(boundary_signal="prompt_probing")
        assert "instructions" in result.lower()

    def test_no_boundary_signal_clean(self) -> None:
        result = _build(boundary_signal=None)
        # The boundary_signals section should be empty
        # (no tactical text noise on clean conversations)
        lines = result.split("\n")
        # Find the line after "boundary_signals" placeholder would be
        # With None signal, the tactical text is empty string
        assert "This person is asking" not in result


# ── Token budget integration ────────────────────────────────────────


@pytest.mark.unit
class TestBuildSystemPromptBudget:
    """Budget trimming applied to doc_context inside build_system_prompt."""

    def test_token_budget_trims_doc_context(self) -> None:
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
        assert len(result) > 0
        assert len(result) < 500_000
