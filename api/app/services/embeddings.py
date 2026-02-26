"""
Embeddings Service — OpenAI text-embedding-3-large (2000 dimensions).
"""

import logging
from typing import Literal

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create async OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def create_embedding(
    text: str, input_type: Literal["document", "query"] = "document"
) -> list[float]:
    """Generate embedding for text."""
    client = get_openai_client()

    try:
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=text,
            dimensions=settings.embedding_dimensions,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
        raise


async def create_embeddings_batch(
    texts: list[str], input_type: Literal["document", "query"] = "document"
) -> list[list[float]]:
    """Generate embeddings for multiple texts (batch)."""
    client = get_openai_client()

    try:
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
            dimensions=settings.embedding_dimensions,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    except Exception as e:
        logger.error("Batch embedding generation failed: %s", e)
        raise
