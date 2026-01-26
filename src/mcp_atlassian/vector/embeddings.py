"""Embedding pipeline for generating vector representations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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


class PersistentEmbeddingCache:
    """SQLite-backed persistent cache for embeddings.

    Survives restarts and implements LRU eviction to prevent unbounded growth.
    """

    def __init__(self, cache_path: Path, max_entries: int = 100_000) -> None:
        """Initialize the persistent cache.

        Args:
            cache_path: Path to SQLite database file
            max_entries: Maximum number of entries before LRU eviction
        """
        self.cache_path = cache_path
        self.max_entries = max_entries
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database schema."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                content_hash TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_accessed
            ON embeddings(last_accessed)
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.cache_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def get(self, content_hash: str) -> list[float] | None:
        """Get embedding from cache.

        Args:
            content_hash: MD5 hash of content

        Returns:
            Embedding vector or None if not found
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT embedding FROM embeddings WHERE content_hash = ?",
            (content_hash,)
        )
        row = cursor.fetchone()
        if row:
            # Update last accessed time
            conn.execute(
                "UPDATE embeddings SET last_accessed = ? WHERE content_hash = ?",
                (time.time(), content_hash)
            )
            conn.commit()
            return json.loads(row["embedding"])
        return None

    def set(self, content_hash: str, embedding: list[float]) -> None:
        """Store embedding in cache.

        Args:
            content_hash: MD5 hash of content
            embedding: Embedding vector to store
        """
        conn = self._get_conn()
        now = time.time()
        conn.execute("""
            INSERT OR REPLACE INTO embeddings
            (content_hash, embedding, created_at, last_accessed)
            VALUES (?, ?, ?, ?)
        """, (content_hash, json.dumps(embedding), now, now))
        conn.commit()

        # Evict old entries if over limit
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        """Evict least recently used entries if over max_entries."""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM embeddings")
        count = cursor.fetchone()[0]

        if count > self.max_entries:
            # Delete oldest 10% of entries
            to_delete = int(self.max_entries * 0.1)
            conn.execute("""
                DELETE FROM embeddings
                WHERE content_hash IN (
                    SELECT content_hash FROM embeddings
                    ORDER BY last_accessed ASC
                    LIMIT ?
                )
            """, (to_delete,))
            conn.commit()
            logger.debug(f"Evicted {to_delete} old cache entries")

    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) as count FROM embeddings")
        count = cursor.fetchone()["count"]

        # Get file size
        file_size_mb = 0
        if self.cache_path.exists():
            file_size_mb = self.cache_path.stat().st_size / (1024 * 1024)

        return {
            "cached_embeddings": count,
            "max_entries": self.max_entries,
            "file_size_mb": round(file_size_mb, 2),
            "cache_path": str(self.cache_path),
        }

    def clear(self) -> None:
        """Clear all cached embeddings."""
        conn = self._get_conn()
        conn.execute("DELETE FROM embeddings")
        conn.commit()
        logger.info("Embedding cache cleared")

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


class EmbeddingPipeline:
    """Pipeline for generating embeddings with batching and caching.

    Supports OpenAI embeddings with plans for local model support.
    Includes rate limiting, batching, retry logic, and persistent caching.
    """

    def __init__(self, config: VectorConfig | None = None) -> None:
        """Initialize the embedding pipeline.

        Args:
            config: Vector configuration. Uses defaults from env if not provided.
        """
        self.config = config or VectorConfig.from_env()
        self._client: AsyncOpenAI | None = None
        self._persistent_cache: PersistentEmbeddingCache | None = None
        self._memory_cache: dict[str, list[float]] = {}  # Hot cache for current session
        self._semaphore: asyncio.Semaphore | None = None

    @property
    def cache(self) -> PersistentEmbeddingCache:
        """Get or create persistent cache."""
        if self._persistent_cache is None:
            cache_path = self.config.db_path / "embedding_cache.db"
            self._persistent_cache = PersistentEmbeddingCache(
                cache_path=cache_path,
                max_entries=100_000,  # ~400MB with 1536-dim embeddings
            )
        return self._persistent_cache

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

    def _get_cached(self, cache_key: str) -> list[float] | None:
        """Get embedding from cache (memory first, then persistent).

        Args:
            cache_key: MD5 hash of content

        Returns:
            Cached embedding or None
        """
        # Check hot memory cache first
        if cache_key in self._memory_cache:
            return self._memory_cache[cache_key]

        # Check persistent cache
        if self.config.cache_embeddings:
            embedding = self.cache.get(cache_key)
            if embedding:
                # Promote to memory cache for fast access
                self._memory_cache[cache_key] = embedding
                return embedding

        return None

    def _set_cached(self, cache_key: str, embedding: list[float]) -> None:
        """Store embedding in both memory and persistent cache.

        Args:
            cache_key: MD5 hash of content
            embedding: Embedding vector to store
        """
        self._memory_cache[cache_key] = embedding
        if self.config.cache_embeddings:
            self.cache.set(cache_key, embedding)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        cache_key = self._get_cache_key(text)

        # Check cache
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.debug("Cache hit for embedding")
            return cached

        # Generate embedding
        if self.config.embedding_provider == EmbeddingProvider.OPENAI:
            embedding = await self._embed_openai([text])
            result = embedding[0]
        else:
            result = await self._embed_local(text)

        # Cache result
        self._set_cached(cache_key, result)

        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts with batching.

        Uses persistent cache and handles failures gracefully.

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
        cache_keys: list[str] = []

        # Check cache for each text
        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text)
            cache_keys.append(cache_key)
            cached = self._get_cached(cache_key)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        if uncached_texts:
            logger.debug(
                f"Cache hit: {len(texts) - len(uncached_texts)}/{len(texts)}, "
                f"embedding {len(uncached_texts)} texts"
            )

        # Embed uncached texts in batches
        if uncached_texts:
            for batch_texts, batch_indices in zip(
                chunked(uncached_texts, self.config.batch_size),
                chunked(uncached_indices, self.config.batch_size),
                strict=False,
            ):
                try:
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
                        cache_key = self._get_cache_key(text)
                        self._set_cached(cache_key, embedding)

                except Exception as e:
                    # Log error but continue with other batches
                    logger.error(f"Batch embedding failed: {e}")
                    # Mark failed items as None, they'll be filtered out
                    for idx in batch_indices:
                        if results[idx] is None:
                            logger.warning(f"Failed to embed text at index {idx}")

        # Return only successful embeddings
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

    @retry(
        retry=retry_if_exception_type((RateLimitError, TimeoutError, ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        before_sleep=lambda retry_state: logger.warning(
            f"Embedding API retry {retry_state.attempt_number}/5 "
            f"after {retry_state.outcome.exception() if retry_state.outcome else 'unknown error'}"
        ),
    )
    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API with retry logic.

        Automatically retries on rate limits and transient errors with
        exponential backoff.

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

            except RateLimitError:
                # Let tenacity handle retry
                raise
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
        """Clear both memory and persistent embedding caches."""
        self._memory_cache.clear()
        if self._persistent_cache:
            self._persistent_cache.clear()
        logger.info("Embedding caches cleared")

    def cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        stats = {
            "memory_cache_entries": len(self._memory_cache),
            "memory_cache_mb": round(
                len(self._memory_cache) * self.config.embedding_dimensions * 4 / (1024 * 1024),
                2
            ),
        }

        # Add persistent cache stats if initialized
        if self._persistent_cache:
            stats.update(self._persistent_cache.stats())

        return stats

    def close(self) -> None:
        """Close resources."""
        if self._persistent_cache:
            self._persistent_cache.close()
            self._persistent_cache = None
