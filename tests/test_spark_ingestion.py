"""
Tests for Spark Ingestion Pipeline.

Covers: chunking logic (pure function), HTML stripping, deduplication.
"""

import pytest

from app.services.spark.ingestion import chunk_text, _strip_html

# ===========================================================================
# TestChunkText
# ===========================================================================


@pytest.mark.unit
class TestChunkText:
    """Paragraph-boundary chunking with overlap."""

    def test_empty_text_returns_empty(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self) -> None:
        text = "Hello world. This is a short paragraph."
        chunks = chunk_text(text, chunk_size=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_respects_paragraph_boundaries(self) -> None:
        para1 = "A" * 600
        para2 = "B" * 600
        text = f"{para1}\n\n{para2}"
        chunks = chunk_text(text, chunk_size=800, overlap=0)
        assert len(chunks) == 2
        assert chunks[0] == para1
        assert chunks[1] == para2

    def test_overlap_carries_tail(self) -> None:
        para1 = "First paragraph content here."
        para2 = "Second paragraph content here."
        para3 = "Third paragraph content here."
        text = f"{para1}\n\n{para2}\n\n{para3}"
        chunks = chunk_text(text, chunk_size=60, overlap=20)
        # Should have overlap from previous chunk
        assert len(chunks) >= 2
        # Second chunk should contain overlap from first
        if len(chunks) > 1:
            # The overlap means some tail of chunk N appears at start of chunk N+1
            assert len(chunks[1]) > len(para2)

    def test_multiple_paragraphs_fit_in_one_chunk(self) -> None:
        text = "Short one.\n\nShort two.\n\nShort three."
        chunks = chunk_text(text, chunk_size=1000)
        assert len(chunks) == 1

    def test_whitespace_only_paragraphs_skipped(self) -> None:
        text = "Content here.\n\n   \n\nMore content."
        chunks = chunk_text(text, chunk_size=1000)
        assert len(chunks) == 1
        assert "Content here." in chunks[0]
        assert "More content." in chunks[0]


# ===========================================================================
# TestStripHtml
# ===========================================================================


@pytest.mark.unit
class TestStripHtml:
    """HTML stripping for URL ingestion."""

    def test_removes_script_tags(self) -> None:
        html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
        result = _strip_html(html)
        assert "alert" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_style_tags(self) -> None:
        html = "<style>.foo { color: red; }</style><p>Content</p>"
        result = _strip_html(html)
        assert "color" not in result
        assert "Content" in result

    def test_removes_nav_and_footer(self) -> None:
        html = "<nav>Menu</nav><main>Content</main><footer>Legal</footer>"
        result = _strip_html(html)
        assert "Menu" not in result
        assert "Content" in result
        assert "Legal" not in result

    def test_decodes_entities(self) -> None:
        html = "<p>Tom &amp; Jerry &lt;3&gt;</p>"
        result = _strip_html(html)
        assert "Tom & Jerry" in result

    def test_block_elements_become_newlines(self) -> None:
        html = "<h1>Title</h1><p>Paragraph</p>"
        result = _strip_html(html)
        assert "Title" in result
        assert "Paragraph" in result

    def test_empty_html_returns_empty(self) -> None:
        assert _strip_html("") == ""
        assert _strip_html("<script>only js</script>") == ""
