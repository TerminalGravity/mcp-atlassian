"""Embedding pipeline for generating vector representations."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from mcp_atlassian.vector.config import EmbeddingProvider, VectorConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def chunked(iterable: list, size: int) -> list[list]:
    """Split a list into chunks of specified size."""
    return [iterable[i : i + size] for i in range(0, len(iterable), size)]


class EmbeddingPipeline:
    """Pipeline for generating embeddings with batching and caching.

    Supports OpenAI embeddings with plans for local model support.
    Includes rate limiting, batching, and content-hash-based caching.
    """

    def __init__(self, config: VectorConfig | None = None) -> None:
        """Initialize the embedding pipeline.

        Args:
            config: Vector configuration. Uses defaults from env if not provided.
        """
        self.config = config or VectorConfig.from_env()
        self._client: AsyncOpenAI | None = None
        self._cache: dict[str, list[float]] = {}
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI()
        return self._client

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Get or create rate limiting semaphore."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent_embeddings)
        return self._semaphore

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text content."""
        return hashlib.md5(text.encode()).hexdigest()

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        # Check cache
        if self.config.cache_embeddings:
            cache_key = self._get_cache_key(text)
            if cache_key in self._cache:
                logger.debug("Cache hit for embedding")
                return self._cache[cache_key]

        # Generate embedding
        if self.config.embedding_provider == EmbeddingProvider.OPENAI:
            embedding = await self._embed_openai([text])
            result = embedding[0]
        else:
            result = await self._embed_local(text)

        # Cache result
        if self.config.cache_embeddings:
            self._cache[cache_key] = result

        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts with batching.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []

        # Check cache for each text
        if self.config.cache_embeddings:
            for i, text in enumerate(texts):
                cache_key = self._get_cache_key(text)
                if cache_key in self._cache:
                    results[i] = self._cache[cache_key]
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)
        else:
            uncached_texts = texts
            uncached_indices = list(range(len(texts)))

        # Embed uncached texts in batches
        if uncached_texts:
            for batch_texts, batch_indices in zip(
                chunked(uncached_texts, self.config.batch_size),
                chunked(uncached_indices, self.config.batch_size), strict=False,
            ):
                if self.config.embedding_provider == EmbeddingProvider.OPENAI:
                    batch_embeddings = await self._embed_openai(batch_texts)
                else:
                    batch_embeddings = [
                        await self._embed_local(t) for t in batch_texts
                    ]

                # Store results and cache
                for idx, text, embedding in zip(
                    batch_indices, batch_texts, batch_embeddings, strict=False
                ):
                    results[idx] = embedding
                    if self.config.cache_embeddings:
                        cache_key = self._get_cache_key(text)
                        self._cache[cache_key] = embedding

        # Type assertion - all slots should be filled
        return [r for r in results if r is not None]

    async def embed_stream(
        self,
        texts: AsyncIterator[str],
    ) -> AsyncIterator[tuple[str, list[float]]]:
        """Stream embeddings for large datasets.

        Yields (text, embedding) pairs as they are computed.

        Args:
            texts: Async iterator of texts to embed

        Yields:
            Tuples of (text, embedding)
        """
        buffer: list[str] = []

        async for text in texts:
            buffer.append(text)

            if len(buffer) >= self.config.batch_size:
                embeddings = await self.embed_batch(buffer)
                for t, emb in zip(buffer, embeddings, strict=False):
                    yield (t, emb)
                buffer = []

        # Process remaining
        if buffer:
            embeddings = await self.embed_batch(buffer)
            for t, emb in zip(buffer, embeddings, strict=False):
                yield (t, emb)

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API.

        Args:
            texts: Texts to embed

        Returns:
            List of embedding vectors
        """
        async with self.semaphore:
            try:
                response = await self.client.embeddings.create(
                    model=self.config.embedding_model,
                    input=texts,
                )

                # Sort by index to maintain order
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return [item.embedding for item in sorted_data]

            except Exception as e:
                logger.error(f"OpenAI embedding error: {e}")
                raise

    async def _embed_local(self, text: str) -> list[float]:
        """Generate embedding using local model.

        TODO: Implement local embedding support with sentence-transformers
        or similar library for offline/air-gapped deployments.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        raise NotImplementedError(
            "Local embeddings not yet implemented. "
            "Set VECTOR_EMBEDDING_PROVIDER=openai to use OpenAI embeddings."
        )

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()
        logger.info("Embedding cache cleared")

    def cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        return {
            "cached_embeddings": len(self._cache),
            "estimated_memory_mb": len(self._cache)
            * self.config.embedding_dimensions
            * 4
            // (1024 * 1024),
        }
