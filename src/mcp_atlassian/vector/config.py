"""Configuration for vector search functionality."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""

    OPENAI = "openai"
    LOCAL = "local"


@dataclass
class VectorConfig:
    """Configuration for vector search functionality.

    Environment variables:
        VECTOR_DB_PATH: Path to LanceDB storage directory
        VECTOR_EMBEDDING_PROVIDER: 'openai' or 'local'
        VECTOR_EMBEDDING_MODEL: Model name for embeddings
        VECTOR_SYNC_ENABLED: Enable background sync
        VECTOR_SYNC_INTERVAL_MINUTES: Sync interval
        VECTOR_SYNC_PROJECTS: Comma-separated project keys or '*'
        VECTOR_SYNC_COMMENTS: Enable comment indexing (default: true)
        VECTOR_BATCH_SIZE: Batch size for embedding operations
        VECTOR_SELF_QUERY_MODEL: LLM model for self-query parsing
        MCP_MAX_RESPONSE_TOKENS: Max tokens in MCP responses
    """

    # Storage
    db_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("VECTOR_DB_PATH", "./data/lancedb")
        )
    )

    # Embeddings
    embedding_provider: EmbeddingProvider = field(
        default_factory=lambda: EmbeddingProvider(
            os.getenv("VECTOR_EMBEDDING_PROVIDER", "openai")
        )
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "VECTOR_EMBEDDING_MODEL", "text-embedding-3-small"
        )
    )
    embedding_dimensions: int = field(
        default_factory=lambda: int(os.getenv("VECTOR_EMBEDDING_DIMENSIONS", "1536"))
    )

    # Sync
    sync_enabled: bool = field(
        default_factory=lambda: os.getenv("VECTOR_SYNC_ENABLED", "true").lower()
        == "true"
    )
    sync_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("VECTOR_SYNC_INTERVAL_MINUTES", "30"))
    )
    sync_projects: list[str] = field(
        default_factory=lambda: _parse_projects(
            os.getenv("VECTOR_SYNC_PROJECTS", "*")
        )
    )
    sync_comments: bool = field(
        default_factory=lambda: os.getenv("VECTOR_SYNC_COMMENTS", "true").lower()
        == "true"
    )

    # Performance
    batch_size: int = field(
        default_factory=lambda: int(os.getenv("VECTOR_BATCH_SIZE", "100"))
    )
    max_concurrent_embeddings: int = field(
        default_factory=lambda: int(os.getenv("VECTOR_MAX_CONCURRENT_EMBEDDINGS", "5"))
    )
    cache_embeddings: bool = field(
        default_factory=lambda: os.getenv("VECTOR_CACHE_EMBEDDINGS", "true").lower()
        == "true"
    )

    # Self-query
    self_query_model: str = field(
        default_factory=lambda: os.getenv("VECTOR_SELF_QUERY_MODEL", "gpt-4o-mini")
    )

    # Response limits
    max_response_tokens: int = field(
        default_factory=lambda: int(os.getenv("MCP_MAX_RESPONSE_TOKENS", "2000"))
    )
    compact_responses: bool = field(
        default_factory=lambda: os.getenv("MCP_COMPACT_RESPONSES", "true").lower()
        == "true"
    )

    # Hybrid search weights
    fts_weight: float = field(
        default_factory=lambda: float(os.getenv("VECTOR_FTS_WEIGHT", "0.3"))
    )

    # Search quality thresholds
    default_min_score: float = field(
        default_factory=lambda: float(os.getenv("VECTOR_DEFAULT_MIN_SCORE", "0.3"))
    )
    duplicate_threshold: float = field(
        default_factory=lambda: float(os.getenv("VECTOR_DUPLICATE_THRESHOLD", "0.85"))
    )
    similar_threshold: float = field(
        default_factory=lambda: float(os.getenv("VECTOR_SIMILAR_THRESHOLD", "0.5"))
    )

    @classmethod
    def from_env(cls) -> VectorConfig:
        """Create config from environment variables."""
        return cls()

    def ensure_db_path(self) -> Path:
        """Ensure the database path exists and return it."""
        self.db_path.mkdir(parents=True, exist_ok=True)
        return self.db_path


def _parse_projects(value: str) -> list[str]:
    """Parse comma-separated project keys or '*' for all."""
    if value.strip() == "*":
        return []  # Empty list means all projects
    return [p.strip() for p in value.split(",") if p.strip()]
