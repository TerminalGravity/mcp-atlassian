"""Vector search MCP tools for semantic Jira search.

These tools provide semantic search capabilities over indexed Jira issues
using vector embeddings and hybrid search.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from mcp_atlassian.servers.jira import jira_mcp
from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.embeddings import EmbeddingPipeline
from mcp_atlassian.vector.self_query import SelfQueryParser
from mcp_atlassian.vector.store import LanceDBStore

logger = logging.getLogger(__name__)


def _json(data: Any) -> Any:
    # Tools return STRUCTURED content (dicts), not pre-stringified JSON.
    # FastMCP serializes a dict return into structuredContent natively, so the
    # Claude Code TUI renders it as a nested, readable object. Returning a JSON
    # *string* instead makes FastMCP wrap it as {"result": "<escaped JSON>"},
    # which renders as an unreadable wall of \n and \" escapes. Identity
    # passthrough kept at the return boundary as the single tool-result marker.
    return data


# Lazy-initialized singletons
_vector_store: LanceDBStore | None = None
_embedder: EmbeddingPipeline | None = None
_config: VectorConfig | None = None
_self_query_parser: SelfQueryParser | None = None


def _reset_singletons() -> None:
    """Reset all singletons to force reconnection to fresh data.

    Call this after a sync operation to ensure the MCP server
    connects to the updated LanceDB tables.
    """
    global _vector_store, _embedder, _config, _self_query_parser
    _vector_store = None
    _embedder = None
    _config = None
    _self_query_parser = None


def _get_config() -> VectorConfig:
    """Get or create vector config singleton."""
    global _config
    if _config is None:
        _config = VectorConfig.from_env()
    return _config


def _get_store() -> LanceDBStore:
    """Get or create vector store singleton."""
    global _vector_store
    if _vector_store is None:
        _vector_store = LanceDBStore(config=_get_config())
    return _vector_store


def _get_embedder() -> EmbeddingPipeline:
    """Get or create embedding pipeline singleton."""
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingPipeline(config=_get_config())
    return _embedder


def _get_parser() -> SelfQueryParser:
    """Get or create self-query parser singleton."""
    global _self_query_parser
    if _self_query_parser is None:
        _self_query_parser = SelfQueryParser()
    return _self_query_parser


async def semantic_search_impl(
    query: str,
    *,
    projects: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
    min_score: float = 0.3,
    exclude_key: str | None = None,
) -> dict[str, Any]:
    """Hybrid vector+FTS search. Plain coroutine shared by jira_find and tools here."""
    store = _get_store()
    config = _get_config()

    stats = store.get_stats()
    if stats["total_issues"] == 0:
        return {
            "error": "Vector index is empty. Run sync first.",
            "hint": "uv run python -m mcp_atlassian.vector.cli sync --full",
        }

    try:
        embedder = _get_embedder()
        query_vector = await embedder.embed(query)
        filters: dict[str, Any] = {}
        if projects:
            filters["project_key"] = {"$in": projects}

        results, total_count = store.hybrid_search(
            query_vector=query_vector,
            query_text=query,
            limit=limit + (1 if exclude_key else 0),
            offset=offset,
            filters=filters or None,
            fts_weight=config.fts_weight,
            min_score=min_score,
        )
    except Exception as e:
        return {
            "error": f"Vector search failed: {e}",
            "hint": "Check OPENAI_API_KEY and that the index is synced (jira_vector_sync_status).",
        }

    # Whether the excluded source was actually among the raw matches (it isn't
    # always — it may be filtered by project or fall below min_score). Capture
    # this BEFORE the trim below reassigns `results` and drops the source.
    source_present = bool(exclude_key) and any(
        r["issue_id"] == exclude_key for r in results
    )

    if exclude_key:
        results = [r for r in results if r["issue_id"] != exclude_key][:limit]

    effective_total = total_count - 1 if source_present else total_count

    response: dict[str, Any] = {
        "total_matches": total_count,
        "returned": len(results),
        "results": [
            {
                "key": r["issue_id"],
                "summary": r["summary"][:120],
                "type": r["issue_type"],
                "status": r["status"],
                "project": r["project_key"],
                "score": round(r.get("score", 0), 3),
            }
            for r in results
        ],
        "hint": "Use jira_get with the keys for details",
    }
    if effective_total > offset + len(results):
        response["pagination"] = {
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit,
            "has_more": True,
        }
    return response


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Vector Sync Status", "readOnlyHint": True},
)
async def vector_sync_status(
    ctx: Context,
) -> dict:
    """
    Get the current status of the vector search index.

    Shows when the last sync occurred, how many issues are indexed,
    and which projects are included.

    Args:
        ctx: The FastMCP context.

    Returns:
        JSON string with sync status information.
    """
    try:
        store = _get_store()
        stats = store.get_stats()
        config = _get_config()

        # Load sync state if available
        state_path = config.db_path / "sync_state.json"
        sync_info: dict[str, Any] = {
            "last_sync": None,
            "projects_synced": [],
        }

        if state_path.exists():
            import json as json_module
            try:
                state_data = json_module.loads(state_path.read_text())
                sync_info["last_sync"] = state_data.get("last_sync_at")
                sync_info["projects_synced"] = state_data.get("projects_synced", [])
            except Exception:
                pass

        response = {
            "index_status": {
                "total_issues": stats["total_issues"],
                "total_comments": stats["total_comments"],
                "projects_indexed": stats["projects"],
                "db_path": stats["db_path"],
            },
            "sync_status": sync_info,
            "config": {
                "embedding_provider": config.embedding_provider.value,
                "embedding_model": config.embedding_model,
                "sync_enabled": config.sync_enabled,
                "sync_interval_minutes": config.sync_interval_minutes,
            },
        }

        return _json(response)

    except Exception as e:
        logger.error(f"Sync status error: {e}", exc_info=True)
        return _json({
            "error": str(e),
        })


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Knowledge Query", "readOnlyHint": True},
)
async def knowledge(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language query with optional filters. Examples:\n"
                "- 'auth bugs from last month'\n"
                "- 'open stories in PLATFORM project'\n"
                "- 'high priority issues assigned to john'\n"
                "- 'API performance problems in Q4'"
            )
        ),
    ],
    limit: Annotated[
        int,
        Field(
            description="Maximum results to return (1-20)",
            ge=1,
            le=20,
            default=10,
        ),
    ] = 10,
) -> dict:
    """Ask the synced Jira knowledge base a natural-language question.

    The ONLY knowledge/analytics tool. Parses the question into semantic
    terms + structured filters (project, type, status, assignee, dates)
    automatically — 'auth bugs from last month in DS' just works. For plain
    issue search use jira_find; for issue content use jira_get.
    """
    try:
        store = _get_store()
        embedder = _get_embedder()
        parser = _get_parser()
        config = _get_config()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_issues"] == 0:
            return _json({
                "error": "Vector index is empty. Run sync first.",
                "hint": "uv run python -m mcp_atlassian.vector.cli sync --full",
            })

        # Parse the query using LLM
        parsed = await parser.parse(query)

        # Generate query embedding if there's a semantic query
        results = []
        if parsed.semantic_query:
            query_vector = await embedder.embed(parsed.semantic_query)

            # Translate filters to LanceDB format
            lancedb_filters = parser.translate_to_lancedb_filters(parsed.filters)

            # Perform hybrid search
            results, total_count = store.hybrid_search(
                query_vector=query_vector,
                query_text=parsed.semantic_query,
                limit=limit,
                offset=0,
                filters=lancedb_filters if lancedb_filters else None,
                fts_weight=config.fts_weight,
            )
        elif parsed.filters:
            # Filter-only query (no semantic search)
            # Use a generic vector search with filters
            # Generate embedding for a neutral query
            query_vector = await embedder.embed("issue")
            lancedb_filters = parser.translate_to_lancedb_filters(parsed.filters)

            results, total_count = store.search_issues(
                query_vector=query_vector,
                limit=limit,
                offset=0,
                filters=lancedb_filters,
            )
        else:
            # No filters and no semantic query - return error
            return _json({
                "error": "Could not understand query",
                "query": query,
                "hint": "Try a more specific query like 'bugs in PROJECT' or 'issues about authentication'",
            })

        # Format response (token-optimized)
        response = {
            "query": query,
            "parsed": {
                "semantic_search": parsed.semantic_query or "(none)",
                "filters": parsed.filters or {},
                "interpretation": parsed.interpretation,
                "confidence": parsed.confidence,
            },
            "total_matches": total_count,
            "returned": len(results),
            "results": [
                {
                    "key": r["issue_id"],
                    "summary": r["summary"][:120],
                    "type": r["issue_type"],
                    "status": r["status"],
                    "project": r["project_key"],
                    "score": round(r.get("score", 0), 3),
                }
                for r in results
            ],
            "hint": "Use jira_get with issue keys for full details",
        }

        return _json(response)

    except Exception as e:
        logger.error(f"Knowledge query error: {e}", exc_info=True)
        return _json({
            "error": str(e),
            "query": query,
        })
