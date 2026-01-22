"""Vector search MCP tools for semantic Jira search.

These tools provide semantic search capabilities over indexed Jira issues
using vector embeddings and hybrid search.
"""

import json
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

# Lazy-initialized singletons
_vector_store: LanceDBStore | None = None
_embedder: EmbeddingPipeline | None = None
_config: VectorConfig | None = None
_self_query_parser: SelfQueryParser | None = None


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


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Semantic Search", "readOnlyHint": True},
)
async def jira_semantic_search(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language search query. Finds issues by meaning, not just keywords. "
                "Examples: 'authentication failures in the API', 'slow database queries', "
                "'customer-reported checkout bugs'"
            )
        ),
    ],
    projects: Annotated[
        str | None,
        Field(
            description="Comma-separated project keys to search within (e.g., 'PROJ,ENG')",
            default=None,
        ),
    ] = None,
    issue_types: Annotated[
        str | None,
        Field(
            description="Filter by issue type: Bug, Story, Task, Epic (comma-separated)",
            default=None,
        ),
    ] = None,
    status_category: Annotated[
        str | None,
        Field(
            description="Filter by status category: 'To Do', 'In Progress', 'Done'",
            default=None,
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Maximum results to return (1-20)",
            ge=1,
            le=20,
            default=10,
        ),
    ] = 10,
) -> str:
    """
    Semantic search across Jira issues using natural language.

    Finds issues by meaning, not just keywords. Use for conceptual searches like
    'performance issues with database queries' or 'authentication failures'.

    Returns compact results (~500-800 tokens). Use jira_get_issue for full details.

    Args:
        ctx: The FastMCP context.
        query: Natural language search query.
        projects: Comma-separated project keys to filter by.
        issue_types: Comma-separated issue types to filter by.
        status_category: Status category filter.
        limit: Maximum number of results.

    Returns:
        JSON string with matching issues and relevance scores.
    """
    try:
        store = _get_store()
        embedder = _get_embedder()
        config = _get_config()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_issues"] == 0:
            return json.dumps({
                "error": "Vector index is empty. Run sync first.",
                "hint": "Use CLI: mcp-atlassian vector sync --full",
            }, indent=2)

        # Generate query embedding
        query_vector = await embedder.embed(query)

        # Build filters
        filters: dict[str, Any] = {}
        if projects:
            filters["project_key"] = {"$in": [p.strip() for p in projects.split(",")]}
        if issue_types:
            filters["issue_type"] = {"$in": [t.strip() for t in issue_types.split(",")]}
        if status_category:
            filters["status_category"] = status_category

        # Perform hybrid search
        results = store.hybrid_search(
            query_vector=query_vector,
            query_text=query,
            limit=limit,
            filters=filters if filters else None,
            fts_weight=config.fts_weight,
        )

        # Format response (token-optimized)
        response = {
            "query": query,
            "total_matches": len(results),
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
            "hint": "Use jira_get_issue with issue key for full details",
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Semantic search error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "query": query,
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Find Similar Issues", "readOnlyHint": True},
)
async def jira_find_similar(
    ctx: Context,
    issue_key: Annotated[
        str,
        Field(description="Jira issue key to find similar issues for (e.g., 'PROJ-123')"),
    ],
    limit: Annotated[
        int,
        Field(
            description="Maximum similar issues to return (1-10)",
            ge=1,
            le=10,
            default=5,
        ),
    ] = 5,
    same_project_only: Annotated[
        bool,
        Field(
            description="Only find similar issues in the same project",
            default=False,
        ),
    ] = False,
    exclude_linked: Annotated[
        bool,
        Field(
            description="Exclude issues already linked to this issue",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Find issues semantically similar to a given issue.

    Use cases:
    - Detect potential duplicates before creating new issues
    - Find related work across projects
    - Discover patterns in similar bugs/features

    Returns top similar issues with similarity scores.

    Args:
        ctx: The FastMCP context.
        issue_key: Source issue key.
        limit: Maximum results to return.
        same_project_only: Restrict to same project.
        exclude_linked: Exclude already-linked issues.

    Returns:
        JSON string with similar issues and scores.
    """
    try:
        store = _get_store()

        # Get source issue
        source = store.get_issue_by_key(issue_key)
        if not source:
            return json.dumps({
                "error": f"Issue {issue_key} not found in index",
                "hint": "The issue may not be indexed yet. Run sync to update.",
            }, indent=2)

        # Build filters
        filters: dict[str, Any] = {"issue_id": {"$ne": issue_key}}
        if same_project_only:
            filters["project_key"] = source.project_key
        if exclude_linked and source.linked_issues:
            # Exclude source and linked issues
            exclude_ids = [issue_key] + source.linked_issues
            filters["issue_id"] = {"$nin": exclude_ids}

        # Search by source vector
        results = store.search_issues(
            query_vector=source.vector,
            limit=limit,
            filters=filters,
        )

        response = {
            "source_issue": {
                "key": issue_key,
                "summary": source.summary[:100],
                "project": source.project_key,
            },
            "similar_issues": [
                {
                    "key": r["issue_id"],
                    "summary": r["summary"][:100],
                    "project": r["project_key"],
                    "type": r["issue_type"],
                    "status": r["status"],
                    "similarity": round(r.get("score", 0), 3),
                }
                for r in results
            ],
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Find similar error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "issue_key": issue_key,
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Detect Duplicates", "readOnlyHint": True},
)
async def jira_detect_duplicates(
    ctx: Context,
    summary: Annotated[
        str,
        Field(description="Summary/title of the issue you plan to create"),
    ],
    description: Annotated[
        str | None,
        Field(
            description="Optional description of the issue",
            default=None,
        ),
    ] = None,
    project: Annotated[
        str | None,
        Field(
            description="Project key to search for duplicates in",
            default=None,
        ),
    ] = None,
    threshold: Annotated[
        float,
        Field(
            description="Similarity threshold (0.7-0.99). Higher = stricter matching.",
            ge=0.7,
            le=0.99,
            default=0.85,
        ),
    ] = 0.85,
) -> str:
    """
    Check if a potential new issue might be a duplicate before creation.

    Pass the summary (and optionally description) of an issue you're about to create.
    Returns potential duplicates above the similarity threshold.

    Use this BEFORE creating issues to avoid duplicates.

    Args:
        ctx: The FastMCP context.
        summary: Proposed issue summary.
        description: Optional proposed description.
        project: Project to search within.
        threshold: Similarity threshold.

    Returns:
        JSON with verdict and potential duplicate candidates.
    """
    try:
        store = _get_store()
        embedder = _get_embedder()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_issues"] == 0:
            return json.dumps({
                "verdict": "CANNOT_CHECK",
                "error": "Vector index is empty",
                "hint": "Run sync first to enable duplicate detection",
            }, indent=2)

        # Embed the proposed issue
        text = f"{summary}\n{description or ''}"
        query_vector = await embedder.embed(text)

        # Build filters
        filters: dict[str, Any] = {}
        if project:
            filters["project_key"] = project
        # Only check non-closed issues
        filters["status_category"] = {"$ne": "Done"}

        # Search
        results = store.search_issues(
            query_vector=query_vector,
            limit=10,
            filters=filters if filters else None,
        )

        # Filter by threshold
        duplicates = [r for r in results if r.get("score", 0) >= threshold]

        # Determine verdict
        if any(r.get("score", 0) > 0.92 for r in duplicates):
            verdict = "DUPLICATE_LIKELY"
        elif duplicates:
            verdict = "REVIEW_SUGGESTED"
        else:
            verdict = "NO_DUPLICATES_FOUND"

        response = {
            "proposed_summary": summary[:100],
            "duplicate_check": {
                "threshold": threshold,
                "potential_duplicates_found": len(duplicates),
            },
            "candidates": [
                {
                    "key": d["issue_id"],
                    "summary": d["summary"][:120],
                    "project": d["project_key"],
                    "status": d["status"],
                    "similarity": round(d.get("score", 0), 3),
                    "recommendation": "Likely duplicate" if d.get("score", 0) > 0.92 else "Review manually",
                }
                for d in duplicates
            ],
            "verdict": verdict,
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Duplicate detection error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "verdict": "ERROR",
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Vector Sync Status", "readOnlyHint": True},
)
async def jira_vector_sync_status(
    ctx: Context,
) -> str:
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

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Sync status error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Knowledge Query", "readOnlyHint": True},
)
async def jira_knowledge_query(
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
) -> str:
    """
    Smart search using natural language with automatic filter extraction.

    Automatically parses your query to extract:
    - Structured filters (project, type, status, assignee, dates, etc.)
    - Semantic search terms (what to find by meaning)

    More powerful than jira_semantic_search - understands context like:
    - "bugs from last week" → type=Bug, created>=7d ago
    - "open stories" → type=Story, status!=Done
    - "assigned to john" → assignee filter

    Returns compact results (~800 tokens) with parsed interpretation.

    Args:
        ctx: The FastMCP context.
        query: Natural language query with optional filters.
        limit: Maximum number of results.

    Returns:
        JSON string with matching issues, filters applied, and interpretation.
    """
    try:
        store = _get_store()
        embedder = _get_embedder()
        parser = _get_parser()
        config = _get_config()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_issues"] == 0:
            return json.dumps({
                "error": "Vector index is empty. Run sync first.",
                "hint": "Use CLI: mcp-atlassian-vector sync --full",
            }, indent=2)

        # Parse the query using LLM
        parsed = await parser.parse(query)

        # Generate query embedding if there's a semantic query
        results = []
        if parsed.semantic_query:
            query_vector = await embedder.embed(parsed.semantic_query)

            # Translate filters to LanceDB format
            lancedb_filters = parser.translate_to_lancedb_filters(parsed.filters)

            # Perform hybrid search
            results = store.hybrid_search(
                query_vector=query_vector,
                query_text=parsed.semantic_query,
                limit=limit,
                filters=lancedb_filters if lancedb_filters else None,
                fts_weight=config.fts_weight,
            )
        elif parsed.filters:
            # Filter-only query (no semantic search)
            # Use a generic vector search with filters
            # Generate embedding for a neutral query
            query_vector = await embedder.embed("issue")
            lancedb_filters = parser.translate_to_lancedb_filters(parsed.filters)

            results = store.search_issues(
                query_vector=query_vector,
                limit=limit,
                filters=lancedb_filters,
            )
        else:
            # No filters and no semantic query - return error
            return json.dumps({
                "error": "Could not understand query",
                "query": query,
                "hint": "Try a more specific query like 'bugs in PROJECT' or 'issues about authentication'",
            }, indent=2)

        # Format response (token-optimized)
        response = {
            "query": query,
            "parsed": {
                "semantic_search": parsed.semantic_query or "(none)",
                "filters": parsed.filters or {},
                "interpretation": parsed.interpretation,
                "confidence": parsed.confidence,
            },
            "total_matches": len(results),
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
            "hint": "Use jira_get_issue with issue key for full details",
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Knowledge query error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "query": query,
        }, indent=2)
