"""
Tests for Spark Ingestion Pipeline.

Covers: chunking logic (pure function), sentence/word fallback,
HTML stripping, content-type routing, deduplication, re-ingestion.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.services.spark import ingestion as ingestion_mod
from app.services.spark.ingestion import chunk_text, _strip_html, _split_oversized_chunk

_CLIENT_ID = uuid4()

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
# TestChunkTextSentenceFallback
# ===========================================================================


@pytest.mark.unit
class TestChunkTextSentenceFallback:
    """Sentence and word-boundary fallback for oversized chunks."""

    def test_chunk_text_sentence_fallback(self) -> None:
        """Single long paragraph with sentences splits on sentence boundaries."""
        # Build a ~5000-char paragraph from ~50-char sentences
        sentence = "This is a reasonably sized sentence for testing. "
        # Repeat enough times to exceed 5000 chars (each ~50 chars)
        para = (sentence * 110).strip()  # ~5500 chars, single paragraph
        assert len(para) > 5000

        chunks = chunk_text(para, chunk_size=1000, overlap=0)

        # Should produce multiple chunks
        assert len(chunks) > 1
        # No chunk exceeds chunk_size
        for c in chunks:
            assert len(c) <= 1000, f"Chunk too long: {len(c)} chars"

    def test_chunk_text_word_boundary_fallback(self) -> None:
        """Single long string with no sentence boundaries splits on word boundary."""
        # 2000 chars with spaces but no sentence-ending punctuation
        words = "word " * 400  # 2000 chars, no .!? anywhere
        words = words.strip()
        assert len(words) > 1500

        chunks = chunk_text(words, chunk_size=500, overlap=0)

        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 500, f"Chunk too long: {len(c)} chars"
        # Reassembled content should contain all words (modulo whitespace)
        reassembled = " ".join(chunks)
        assert reassembled.count("word") == 400

    def test_chunk_text_mixed_paragraphs(self) -> None:
        """Normal paragraphs pass through; long one gets sentence-split."""
        short_para = "Short paragraph that fits easily."
        # Build a long paragraph from sentences
        sentence = "A sentence that is about fifty characters long. "
        long_para = (sentence * 30).strip()  # ~1500 chars
        assert len(long_para) > 1000

        text = f"{short_para}\n\n{long_para}"
        chunks = chunk_text(text, chunk_size=500, overlap=0)

        # Short paragraph should be its own chunk
        assert chunks[0] == short_para
        # Long paragraph should be split into multiple chunks
        assert len(chunks) > 2
        for c in chunks:
            assert len(c) <= 500

    def test_chunk_text_normal_unchanged(self) -> None:
        """Normal text under chunk_size behaves identically to before (regression)."""
        text = "Hello world. This is a short paragraph."
        chunks_new = chunk_text(text, chunk_size=1000)
        assert len(chunks_new) == 1
        assert chunks_new[0] == text

        # Multiple short paragraphs fitting in one chunk
        text2 = "Para one.\n\nPara two.\n\nPara three."
        chunks2 = chunk_text(text2, chunk_size=1000)
        assert len(chunks2) == 1


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


# ===========================================================================
# TestIngestUrlContentType
# ===========================================================================


def _mock_response(
    text: str,
    content_type: str | None = None,
    status_code: int = 200,
) -> httpx.Response:
    """Build a fake httpx.Response with the given content-type header.

    When content_type is None, no Content-Type header is sent (simulates
    a server that omits the header). We use ``content=`` (bytes) to avoid
    httpx auto-adding ``text/plain`` when ``text=`` is used.
    """
    headers: dict[str, str] = {}
    request = httpx.Request("GET", "https://example.com")
    if content_type is not None:
        headers["content-type"] = content_type
        return httpx.Response(
            status_code=status_code,
            text=text,
            headers=headers,
            request=request,
        )
    # No content-type: use raw bytes to prevent httpx from adding one
    return httpx.Response(
        status_code=status_code,
        content=text.encode(),
        headers=headers,
        request=request,
    )


@pytest.mark.unit
class TestIngestUrlContentType:
    """Content-Type routing in ingest_url."""

    @pytest.mark.asyncio
    async def test_ingest_url_html_content_type(self) -> None:
        """text/html content runs through _strip_html pipeline."""
        html = "<p>Hello</p><script>bad</script>"
        resp = _mock_response(html, content_type="text/html; charset=utf-8")

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp)

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        mock_ingest_text = AsyncMock(return_value=1)

        with patch("httpx.AsyncClient", return_value=mock_http), \
             patch.object(ingestion_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(ingestion_mod, "ingest_text", mock_ingest_text):
            result = await ingestion_mod.ingest_url(_CLIENT_ID, "https://example.com")

        # ingest_text should have been called with stripped content (no script)
        call_kwargs = mock_ingest_text.call_args
        content_arg = call_kwargs.kwargs.get("content") or call_kwargs.args[1]
        assert "bad" not in content_arg
        assert "Hello" in content_arg
        assert result == 1

    @pytest.mark.asyncio
    async def test_ingest_url_plain_text_content_type(self) -> None:
        """text/plain skips HTML stripping."""
        plain = "<p>This is literal text with angle brackets</p>"
        resp = _mock_response(plain, content_type="text/plain")

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp)

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        mock_ingest_text = AsyncMock(return_value=1)

        with patch("httpx.AsyncClient", return_value=mock_http), \
             patch.object(ingestion_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(ingestion_mod, "ingest_text", mock_ingest_text):
            result = await ingestion_mod.ingest_url(_CLIENT_ID, "https://example.com")

        # Content should still contain the raw <p> tags (not stripped)
        call_kwargs = mock_ingest_text.call_args
        content_arg = call_kwargs.kwargs.get("content") or call_kwargs.args[1]
        assert "<p>" in content_arg

    @pytest.mark.asyncio
    async def test_ingest_url_pdf_rejected(self) -> None:
        """application/pdf raises ValueError."""
        resp = _mock_response("", content_type="application/pdf")

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ValueError, match="PDF ingestion is not yet supported"):
                await ingestion_mod.ingest_url(_CLIENT_ID, "https://example.com/doc.pdf")

    @pytest.mark.asyncio
    async def test_ingest_url_unsupported_type(self) -> None:
        """application/json raises ValueError."""
        resp = _mock_response("{}", content_type="application/json")

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp)

        with patch("httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ValueError, match="Unsupported content type"):
                await ingestion_mod.ingest_url(_CLIENT_ID, "https://example.com/data")

    @pytest.mark.asyncio
    async def test_ingest_url_missing_content_type(self) -> None:
        """Missing Content-Type header defaults to HTML behaviour."""
        html = "<p>Hello</p>"
        resp = _mock_response(html, content_type=None)

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp)

        mock_sb = MagicMock()
        mock_sb.table.return_value.delete.return_value.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        mock_ingest_text = AsyncMock(return_value=1)

        with patch("httpx.AsyncClient", return_value=mock_http), \
             patch.object(ingestion_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(ingestion_mod, "ingest_text", mock_ingest_text):
            result = await ingestion_mod.ingest_url(_CLIENT_ID, "https://example.com")

        # Should go through HTML stripping (default behaviour)
        call_kwargs = mock_ingest_text.call_args
        content_arg = call_kwargs.kwargs.get("content") or call_kwargs.args[1]
        assert "<p>" not in content_arg
        assert "Hello" in content_arg


# ===========================================================================
# TestReingestionConsistency
# ===========================================================================


@pytest.mark.unit
class TestReingestionConsistency:
    """Re-ingestion: source_url triggers delete-then-insert; no URL uses hash dedup."""

    @pytest.mark.asyncio
    async def test_ingest_text_with_source_url_cleans_stale(self) -> None:
        """When source_url is provided, old chunks are deleted before inserting."""
        mock_sb = MagicMock()

        # delete().eq().eq().execute()
        mock_delete_chain = MagicMock()
        mock_delete_chain.eq.return_value.eq.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )
        mock_sb.table.return_value.delete.return_value = mock_delete_chain

        # insert().execute()
        mock_sb.table.return_value.insert.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[{"id": "1"}])
        )

        mock_embed = AsyncMock(return_value=[[0.1] * 10])

        with patch.object(ingestion_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(ingestion_mod, "create_embeddings_batch", mock_embed):
            result = await ingestion_mod.ingest_text(
                client_id=_CLIENT_ID,
                content="Short content for test.",
                source_url="https://example.com/page",
            )

        # Delete should have been called for the URL
        mock_sb.table.return_value.delete.assert_called_once()

        # No select (hash dedup) should have been called
        mock_sb.table.return_value.select.assert_not_called()

        assert result == 1

    @pytest.mark.asyncio
    async def test_ingest_text_without_source_url_dedup_only(self) -> None:
        """When no source_url, hash dedup runs and no delete occurs."""
        mock_sb = MagicMock()

        # select().eq().in_().execute() — hash dedup returns no existing
        mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[])
        )

        # insert().execute()
        mock_sb.table.return_value.insert.return_value.execute = AsyncMock(
            return_value=MagicMock(data=[{"id": "1"}])
        )

        mock_embed = AsyncMock(return_value=[[0.1] * 10])

        with patch.object(ingestion_mod, "get_supabase_client", AsyncMock(return_value=mock_sb)), \
             patch.object(ingestion_mod, "create_embeddings_batch", mock_embed):
            result = await ingestion_mod.ingest_text(
                client_id=_CLIENT_ID,
                content="Short content for test.",
                source_url=None,
            )

        # Delete should NOT have been called
        mock_sb.table.return_value.delete.assert_not_called()

        # Select (hash dedup) SHOULD have been called
        mock_sb.table.return_value.select.assert_called_once()

        assert result == 1
