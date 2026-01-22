"""Tests for the vector config module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_atlassian.vector.config import EmbeddingProvider, VectorConfig


def test_from_env_defaults():
    """Test that from_env correctly loads default configuration."""
    with patch.dict(os.environ, {}, clear=True):
        config = VectorConfig.from_env()
        assert config.db_path == Path("./data/lancedb")
        assert config.embedding_provider == EmbeddingProvider.OPENAI
        assert config.embedding_model == "text-embedding-3-small"
        assert config.embedding_dimensions == 1536
        assert config.sync_enabled is True
        assert config.sync_interval_minutes == 30
        assert config.sync_projects == []  # Empty means all
        assert config.batch_size == 100
        assert config.self_query_model == "gpt-4o-mini"


def test_from_env_custom_values():
    """Test that from_env correctly loads custom configuration."""
    with patch.dict(
        os.environ,
        {
            "VECTOR_DB_PATH": "/custom/path/lancedb",
            "VECTOR_EMBEDDING_PROVIDER": "local",
            "VECTOR_EMBEDDING_MODEL": "nomic-ai/nomic-embed-text-v1.5",
            "VECTOR_EMBEDDING_DIMENSIONS": "768",
            "VECTOR_SYNC_ENABLED": "false",
            "VECTOR_SYNC_INTERVAL_MINUTES": "60",
            "VECTOR_SYNC_PROJECTS": "DS,ENG,PROJ",
            "VECTOR_BATCH_SIZE": "50",
            "VECTOR_SELF_QUERY_MODEL": "gpt-4",
            "VECTOR_SYNC_COMMENTS": "false",
        },
        clear=True,
    ):
        config = VectorConfig.from_env()
        assert config.db_path == Path("/custom/path/lancedb")
        assert config.embedding_provider == EmbeddingProvider.LOCAL
        assert config.embedding_model == "nomic-ai/nomic-embed-text-v1.5"
        assert config.embedding_dimensions == 768
        assert config.sync_enabled is False
        assert config.sync_interval_minutes == 60
        assert config.sync_projects == ["DS", "ENG", "PROJ"]
        assert config.batch_size == 50
        assert config.self_query_model == "gpt-4"
        assert config.sync_comments is False


def test_embedding_provider_openai():
    """Test OpenAI embedding provider."""
    with patch.dict(
        os.environ, {"VECTOR_EMBEDDING_PROVIDER": "openai"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.embedding_provider == EmbeddingProvider.OPENAI


def test_embedding_provider_local():
    """Test local embedding provider."""
    with patch.dict(
        os.environ, {"VECTOR_EMBEDDING_PROVIDER": "local"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.embedding_provider == EmbeddingProvider.LOCAL


def test_sync_projects_wildcard():
    """Test that '*' for projects results in empty list (all projects)."""
    with patch.dict(
        os.environ, {"VECTOR_SYNC_PROJECTS": "*"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.sync_projects == []


def test_sync_projects_comma_separated():
    """Test parsing comma-separated project keys."""
    with patch.dict(
        os.environ, {"VECTOR_SYNC_PROJECTS": "DS, ENG , PROJ"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.sync_projects == ["DS", "ENG", "PROJ"]


def test_ensure_db_path(tmp_path):
    """Test that ensure_db_path creates the directory."""
    db_path = tmp_path / "test_lancedb"
    config = VectorConfig(db_path=db_path)

    assert not db_path.exists()
    result = config.ensure_db_path()
    assert db_path.exists()
    assert result == db_path


def test_response_limits():
    """Test response limit configuration."""
    with patch.dict(
        os.environ,
        {
            "MCP_MAX_RESPONSE_TOKENS": "3000",
            "MCP_COMPACT_RESPONSES": "false",
        },
        clear=True,
    ):
        config = VectorConfig.from_env()
        assert config.max_response_tokens == 3000
        assert config.compact_responses is False


def test_hybrid_search_weights():
    """Test hybrid search weight configuration."""
    with patch.dict(
        os.environ, {"VECTOR_FTS_WEIGHT": "0.5"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.fts_weight == 0.5


def test_cache_embeddings_default():
    """Test that embedding caching is enabled by default."""
    with patch.dict(os.environ, {}, clear=True):
        config = VectorConfig.from_env()
        assert config.cache_embeddings is True


def test_cache_embeddings_disabled():
    """Test disabling embedding cache."""
    with patch.dict(
        os.environ, {"VECTOR_CACHE_EMBEDDINGS": "false"}, clear=True
    ):
        config = VectorConfig.from_env()
        assert config.cache_embeddings is False
