"""
LLM Service — Thin wrapper around LiteLLM for Spark.

Provides complete() and stream() with a simple fallback chain.
No tier system, no metabolic routing — just model + fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator

import litellm

from app.config import settings

logger = logging.getLogger(__name__)

# Suppress LiteLLM's noisy logging
litellm.suppress_debug_info = True


def _get_api_key(model: str) -> str | None:
    """Resolve API key from model identifier."""
    if model.startswith("gemini/"):
        return settings.google_ai_api_key
    if model.startswith("moonshot/"):
        return settings.moonshot_api_key
    if model.startswith("groq/"):
        return settings.groq_api_key
    return None


def _get_fallback(model: str) -> str | None:
    """Get fallback model for a given primary."""
    if model == settings.spark_primary_model:
        return settings.spark_fallback_model
    return None


async def complete(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: int = 30,
) -> str:
    """Get a completion from the LLM. Falls back on failure."""
    resolved = model or settings.spark_primary_model
    start = time.perf_counter()

    try:
        response = await litellm.acompletion(
            model=resolved,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            api_key=_get_api_key(resolved),
            timeout=timeout,
        )

        result = response.choices[0].message.content or ""
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug("LLM complete (%s): %.0fms", resolved, elapsed)
        return result

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error("LLM complete failed (%s, %.0fms): %s", resolved, elapsed, e)

        fallback = _get_fallback(resolved)
        if fallback:
            logger.info("Falling back: %s → %s", resolved, fallback)
            try:
                response = await litellm.acompletion(
                    model=fallback,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    api_key=_get_api_key(fallback),
                    timeout=timeout,
                )
                return response.choices[0].message.content or ""
            except Exception as fb_err:
                logger.error("Fallback also failed (%s): %s", fallback, fb_err)

        raise


async def stream(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    timeout: int = 30,
) -> AsyncGenerator[str, None]:
    """Stream a completion. Falls back to complete() on failure."""
    resolved = model or settings.spark_primary_model
    start = time.perf_counter()

    try:
        logger.info("LLM stream starting (%s)", resolved)
        response = await litellm.acompletion(
            model=resolved,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            api_key=_get_api_key(resolved),
            timeout=timeout,
            stream_timeout=timeout,
        )

        logger.info("LLM stream connected (%s), reading chunks...", resolved)
        chunk_count = 0
        async for chunk in response:
            if chunk.choices[0].delta.content:
                chunk_count += 1
                yield chunk.choices[0].delta.content

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "LLM stream complete (%s): %.0fms, %d chunks",
            resolved, elapsed, chunk_count,
        )

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        logger.error(
            "LLM stream failed (%s, %.0fms): %s: %s",
            resolved, elapsed, type(e).__name__, e,
        )

        fallback = _get_fallback(resolved)
        if fallback:
            logger.info("Stream fallback: %s → complete() with %s", resolved, fallback)
            try:
                result = await complete(
                    messages=messages,
                    model=fallback,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                if result:
                    yield result
                return
            except Exception:
                pass

        raise
