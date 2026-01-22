"""Embedding pipeline for generating vector representations."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI

from mcp_atlassian.vector.config import EmbeddingProvider, VectorConfig

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default local embedding model
DEFAULT_LOCAL_MODEL = "nomic-ai/nomic-embed-text-v1.5"

# Lazy-loaded sentence transformers model
_local_model: Any = None
_local_model_name: str | None = None


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
                    # Use batch local embedding for efficiency
                    loop = asyncio.get_event_loop()
                    batch_embeddings = await loop.run_in_executor(
                        None, self._embed_local_batch_sync, batch_texts
                    )

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

        Uses sentence-transformers with nomic-embed-text or similar model
        for offline/air-gapped deployments.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._embed_local_sync, text)

    def _embed_local_sync(self, text: str) -> list[float]:
        """Synchronous local embedding generation.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        model = self._get_local_model()

        # Add task prefix for nomic model
        if "nomic" in self.config.embedding_model.lower():
            text = f"search_document: {text}"

        embedding = model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def _embed_local_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous batch local embedding generation.

        Args:
            texts: Texts to embed

        Returns:
            List of embedding vectors
        """
        model = self._get_local_model()

        # Add task prefix for nomic model
        if "nomic" in self.config.embedding_model.lower():
            texts = [f"search_document: {t}" for t in texts]

        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]

    def _get_local_model(self) -> Any:
        """Get or load local embedding model.

        Returns:
            Loaded SentenceTransformer model
        """
        global _local_model, _local_model_name

        model_name = self.config.embedding_model
        if model_name == "text-embedding-3-small":
            # Default local model when provider is local but model not specified
            model_name = DEFAULT_LOCAL_MODEL

        # Return cached model if same
        if _local_model is not None and _local_model_name == model_name:
            return _local_model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install with: pip install sentence-transformers"
            ) from e

        logger.info(f"Loading local embedding model: {model_name}")

        # Set cache directory
        cache_dir = self.config.db_path / "models"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Load model with trust_remote_code for nomic
        trust_remote_code = "nomic" in model_name.lower()
        _local_model = SentenceTransformer(
            model_name,
            cache_folder=str(cache_dir),
            trust_remote_code=trust_remote_code,
        )
        _local_model_name = model_name

        logger.info(f"Loaded model with dimension: {_local_model.get_sentence_embedding_dimension()}")
        return _local_model

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
