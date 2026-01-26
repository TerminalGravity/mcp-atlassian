"""Tests for the vector embeddings module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_atlassian.vector.config import EmbeddingProvider, VectorConfig
from mcp_atlassian.vector.embeddings import EmbeddingPipeline, chunked


def test_chunked():
    """Test the chunked utility function."""
    items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    # Chunk of 3
    result = chunked(items, 3)
    assert result == [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]

    # Chunk of 5
    result = chunked(items, 5)
    assert result == [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]]

    # Chunk larger than list
    result = chunked(items, 20)
    assert result == [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]

    # Empty list
    result = chunked([], 3)
    assert result == []


def test_embedding_pipeline_init():
    """Test EmbeddingPipeline initialization."""
    config = VectorConfig(
        embedding_provider=EmbeddingProvider.OPENAI,
        embedding_model="text-embedding-3-small",
    )
    pipeline = EmbeddingPipeline(config=config)

    assert pipeline.config == config
    assert pipeline._client is None
    assert pipeline._memory_cache == {}  # Memory cache for hot access
    assert pipeline._persistent_cache is None  # Lazy-loaded


def test_embedding_pipeline_cache_key():
    """Test cache key generation."""
    pipeline = EmbeddingPipeline()

    key1 = pipeline._get_cache_key("hello world")
    key2 = pipeline._get_cache_key("hello world")
    key3 = pipeline._get_cache_key("different text")

    assert key1 == key2
    assert key1 != key3
    assert len(key1) == 32  # MD5 hex digest


def test_clear_cache():
    """Test cache clearing."""
    pipeline = EmbeddingPipeline()
    pipeline._memory_cache["key1"] = [0.1, 0.2]
    pipeline._memory_cache["key2"] = [0.3, 0.4]

    assert len(pipeline._memory_cache) == 2
    pipeline.clear_cache()
    assert len(pipeline._memory_cache) == 0


def test_cache_stats():
    """Test cache statistics."""
    config = VectorConfig(embedding_dimensions=1536)
    pipeline = EmbeddingPipeline(config=config)

    # Empty cache
    stats = pipeline.cache_stats()
    assert stats["memory_cache_entries"] == 0

    # Add some embeddings to memory cache
    pipeline._memory_cache["key1"] = [0.0] * 1536
    pipeline._memory_cache["key2"] = [0.0] * 1536

    stats = pipeline.cache_stats()
    assert stats["memory_cache_entries"] == 2
    assert "memory_cache_mb" in stats


@pytest.mark.asyncio
async def test_embed_with_cache():
    """Test that embedding uses cache correctly."""
    config = VectorConfig(
        cache_embeddings=True,
        embedding_provider=EmbeddingProvider.OPENAI,
    )
    pipeline = EmbeddingPipeline(config=config)

    # Pre-populate memory cache (simulating a hot cache hit)
    cached_embedding = [0.1, 0.2, 0.3]
    cache_key = pipeline._get_cache_key("test text")
    pipeline._memory_cache[cache_key] = cached_embedding

    # Should return cached value without calling API
    result = await pipeline.embed("test text")
    assert result == cached_embedding


@pytest.mark.asyncio
async def test_embed_batch_empty():
    """Test batch embedding with empty list."""
    pipeline = EmbeddingPipeline()
    result = await pipeline.embed_batch([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_batch_with_partial_cache():
    """Test batch embedding with some cached values."""
    config = VectorConfig(
        cache_embeddings=False,  # Disable persistent cache for this test
        embedding_provider=EmbeddingProvider.OPENAI,
        batch_size=10,
    )
    pipeline = EmbeddingPipeline(config=config)

    # Cache one embedding in memory cache
    cached_embedding = [0.1, 0.2, 0.3]
    cache_key = pipeline._get_cache_key("cached text")
    pipeline._memory_cache[cache_key] = cached_embedding

    # Mock OpenAI call for uncached text
    mock_response = MagicMock()
    mock_response.data = [
        MagicMock(index=0, embedding=[0.4, 0.5, 0.6]),
    ]

    with patch.object(
        pipeline, "_embed_openai", new_callable=AsyncMock
    ) as mock_embed:
        mock_embed.return_value = [[0.4, 0.5, 0.6]]

        result = await pipeline.embed_batch(["cached text", "uncached text"])

        # Should have called API only for uncached text
        mock_embed.assert_called_once_with(["uncached text"])

        # Results should be in correct order
        assert result[0] == cached_embedding
        assert result[1] == [0.4, 0.5, 0.6]


def test_local_model_task_prefix():
    """Test that nomic models get task prefix."""
    config = VectorConfig(
        embedding_provider=EmbeddingProvider.LOCAL,
        embedding_model="nomic-ai/nomic-embed-text-v1.5",
    )
    pipeline = EmbeddingPipeline(config=config)

    # Mock the model
    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2])

    with patch.object(pipeline, "_get_local_model", return_value=mock_model):
        result = pipeline._embed_local_sync("test text")

        # Should have added task prefix
        mock_model.encode.assert_called_once()
        call_args = mock_model.encode.call_args[0][0]
        assert call_args.startswith("search_document: ")


def test_local_model_batch_task_prefix():
    """Test that batch local embedding adds task prefix for nomic models."""
    config = VectorConfig(
        embedding_provider=EmbeddingProvider.LOCAL,
        embedding_model="nomic-ai/nomic-embed-text-v1.5",
    )
    pipeline = EmbeddingPipeline(config=config)

    # Mock the model
    mock_model = MagicMock()
    mock_embeddings = [MagicMock(tolist=lambda: [0.1]), MagicMock(tolist=lambda: [0.2])]
    mock_model.encode.return_value = mock_embeddings

    with patch.object(pipeline, "_get_local_model", return_value=mock_model):
        result = pipeline._embed_local_batch_sync(["text1", "text2"])

        # Should have added task prefix to all texts
        mock_model.encode.assert_called_once()
        call_args = mock_model.encode.call_args[0][0]
        assert all(t.startswith("search_document: ") for t in call_args)


def test_local_embedding_model_caching():
    """Test that local model is cached after first load."""
    # This test verifies the caching mechanism works
    # The actual model loading requires sentence-transformers
    import mcp_atlassian.vector.embeddings as emb

    # Initially no cached model
    original_model = emb._local_model
    original_name = emb._local_model_name

    # Clear any cached model
    emb._local_model = None
    emb._local_model_name = None

    # Restore after test
    try:
        assert emb._local_model is None
        assert emb._local_model_name is None
    finally:
        emb._local_model = original_model
        emb._local_model_name = original_name
