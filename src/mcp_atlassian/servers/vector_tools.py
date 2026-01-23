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


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Search Comments", "readOnlyHint": True},
)
async def jira_search_comments(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language search query for comments. "
                "Examples: 'workaround for the timeout issue', 'deployment steps', "
                "'mentioned by john about performance'"
            )
        ),
    ],
    issue_key: Annotated[
        str | None,
        Field(
            description="Filter to comments on a specific issue (e.g., 'PROJ-123')",
            default=None,
        ),
    ] = None,
    project: Annotated[
        str | None,
        Field(
            description="Filter to comments in a specific project",
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
    Semantic search across Jira issue comments.

    Find comments by meaning, not just keywords. Useful for:
    - Finding workarounds or solutions mentioned in comments
    - Locating discussions about specific topics
    - Finding deployment instructions or technical details

    Returns comment previews with parent issue context.

    Args:
        ctx: The FastMCP context.
        query: Natural language search query.
        issue_key: Optional issue key filter.
        project: Optional project filter.
        limit: Maximum number of results.

    Returns:
        JSON string with matching comments and relevance scores.
    """
    try:
        store = _get_store()
        embedder = _get_embedder()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_comments"] == 0:
            return json.dumps({
                "error": "No comments indexed yet",
                "hint": "Run sync with comments enabled: mcp-atlassian-vector sync --full",
            }, indent=2)

        # Generate query embedding
        query_vector = await embedder.embed(query)

        # Build filters
        filters: dict[str, Any] = {}
        if issue_key:
            filters["issue_key"] = issue_key
        if project:
            filters["project_key"] = project

        # Search comments
        results = store.search_comments(
            query_vector=query_vector,
            limit=limit,
            filters=filters if filters else None,
        )

        # Format response
        response = {
            "query": query,
            "total_matches": len(results),
            "results": [
                {
                    "comment_id": r["comment_id"],
                    "issue_key": r["issue_key"],
                    "project": r["project_key"],
                    "author": r["author"],
                    "preview": r["body_preview"][:200],
                    "score": round(r.get("score", 0), 3),
                }
                for r in results
            ],
            "hint": "Use jira_get_issue with issue key for full context",
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Comment search error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "query": query,
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Project Insights", "readOnlyHint": True},
)
async def jira_project_insights(
    ctx: Context,
    project: Annotated[
        str,
        Field(description="Project key to analyze (e.g., 'PROJ')"),
    ],
    include_recent: Annotated[
        bool,
        Field(
            description="Include recently updated issues",
            default=True,
        ),
    ] = True,
    days: Annotated[
        int,
        Field(
            description="Days to look back for recent activity (1-30)",
            ge=1,
            le=30,
            default=7,
        ),
    ] = 7,
) -> str:
    """
    Get insights and aggregations for a Jira project.

    Provides:
    - Issue distribution by type, status, priority
    - Top assignees and their workload
    - Common labels and components
    - Recent activity summary

    Useful for understanding project health and identifying patterns.

    Args:
        ctx: The FastMCP context.
        project: Project key to analyze.
        include_recent: Whether to include recent issues.
        days: Days to look back for recent activity.

    Returns:
        JSON string with project insights and aggregations.
    """
    try:
        store = _get_store()

        # Check if project has indexed data
        stats = store.get_stats()
        if project not in stats.get("projects", []):
            return json.dumps({
                "error": f"Project {project} not found in index",
                "indexed_projects": stats.get("projects", []),
                "hint": "Run sync to index this project",
            }, indent=2)

        # Get aggregations
        aggregations = store.get_project_aggregations(project)

        # Get recent issues if requested
        recent_issues = []
        if include_recent:
            recent = store.get_recent_issues(project_key=project, days=days, limit=10)
            recent_issues = [
                {
                    "key": r["issue_id"],
                    "summary": r["summary"][:80],
                    "type": r["issue_type"],
                    "status": r["status"],
                    "updated": r.get("updated_at", ""),
                }
                for r in recent
            ]

        response = {
            "project": project,
            "summary": {
                "total_issues": aggregations.get("total_issues", 0),
                "by_type": aggregations.get("by_type", {}),
                "by_status": aggregations.get("by_status_category", {}),
                "by_priority": aggregations.get("by_priority", {}),
            },
            "top_assignees": aggregations.get("top_assignees", {}),
            "top_labels": aggregations.get("top_labels", {}),
            "top_components": aggregations.get("top_components", {}),
        }

        if include_recent:
            response["recent_activity"] = {
                "days": days,
                "count": len(recent_issues),
                "issues": recent_issues,
            }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Project insights error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "project": project,
        }, indent=2)


# Insights engine singleton
_insights_engine: Any = None


def _get_insights_engine() -> Any:
    """Get or create insights engine singleton."""
    global _insights_engine
    if _insights_engine is None:
        from mcp_atlassian.vector.insights import InsightsEngine
        _insights_engine = InsightsEngine(_get_store())
    return _insights_engine


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Issue Clusters", "readOnlyHint": True},
)
async def jira_issue_clusters(
    ctx: Context,
    project: Annotated[
        str | None,
        Field(
            description="Project key to analyze (e.g., 'PROJ'). Omit for all projects.",
            default=None,
        ),
    ] = None,
    n_clusters: Annotated[
        int,
        Field(
            description="Number of clusters to find (2-10)",
            ge=2,
            le=10,
            default=5,
        ),
    ] = 5,
) -> str:
    """
    Find natural groupings/themes in issues using semantic clustering.

    Groups similar issues together based on their content meaning.
    Useful for:
    - Identifying recurring themes or problem areas
    - Finding related issues that should be linked
    - Understanding common patterns across the codebase

    Returns clusters with representative issues and common attributes.

    Args:
        ctx: The FastMCP context.
        project: Optional project filter.
        n_clusters: Number of clusters to find.

    Returns:
        JSON string with cluster analysis results.
    """
    try:
        engine = _get_insights_engine()
        clusters = engine.cluster_issues(
            project_key=project,
            n_clusters=n_clusters,
        )

        if not clusters:
            return json.dumps({
                "error": "Not enough issues for clustering",
                "hint": "Need at least 15 issues for meaningful clusters",
            }, indent=2)

        response = {
            "project": project or "all",
            "clusters_found": len(clusters),
            "clusters": [
                {
                    "id": c.cluster_id,
                    "size": c.size,
                    "theme_keywords": c.theme_keywords,
                    "representative_issues": c.representative_issues,
                    "common_labels": c.common_labels,
                    "common_components": c.common_components,
                }
                for c in clusters
            ],
            "hint": "Use jira_get_issue to explore representative issues",
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Clustering error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Issue Trends", "readOnlyHint": True},
)
async def jira_issue_trends(
    ctx: Context,
    project: Annotated[
        str | None,
        Field(
            description="Project key to analyze (e.g., 'PROJ'). Omit for all projects.",
            default=None,
        ),
    ] = None,
    days: Annotated[
        int,
        Field(
            description="Total days to analyze (7-90)",
            ge=7,
            le=90,
            default=30,
        ),
    ] = 30,
    period_days: Annotated[
        int,
        Field(
            description="Days per period for grouping (1-14)",
            ge=1,
            le=14,
            default=7,
        ),
    ] = 7,
) -> str:
    """
    Analyze issue creation and resolution trends over time.

    Shows how issue volume changes over time periods.
    Useful for:
    - Understanding team velocity
    - Identifying periods of high bug activity
    - Tracking backlog growth/reduction

    Returns metrics per period with trending labels.

    Args:
        ctx: The FastMCP context.
        project: Optional project filter.
        days: Total days to analyze.
        period_days: Days per period.

    Returns:
        JSON string with trend analysis.
    """
    try:
        engine = _get_insights_engine()
        trends = engine.analyze_trends(
            project_key=project,
            days=days,
            period_days=period_days,
        )

        if not trends:
            return json.dumps({
                "error": "No data for trend analysis",
                "hint": "Ensure issues are indexed with created_at timestamps",
            }, indent=2)

        response = {
            "project": project or "all",
            "analysis_period": f"{days} days",
            "period_size": f"{period_days} days",
            "periods": [
                {
                    "start": t.period_start.strftime("%Y-%m-%d"),
                    "end": t.period_end.strftime("%Y-%m-%d"),
                    "created": t.total_created,
                    "resolved": t.total_resolved,
                    "net_change": t.net_change,
                    "by_type": t.by_type,
                    "trending_labels": [
                        {"label": label, "count": count}
                        for label, count in t.trending_labels
                    ],
                }
                for t in trends
            ],
            "totals": {
                "total_created": sum(t.total_created for t in trends),
                "total_resolved": sum(t.total_resolved for t in trends),
                "net_backlog_change": sum(t.net_change for t in trends),
            },
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Trend analysis error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Bug Patterns", "readOnlyHint": True},
)
async def jira_bug_patterns(
    ctx: Context,
    project: Annotated[
        str | None,
        Field(
            description="Project key to analyze (e.g., 'PROJ'). Omit for all projects.",
            default=None,
        ),
    ] = None,
    min_similarity: Annotated[
        float,
        Field(
            description="Minimum similarity threshold (0.7-0.95)",
            ge=0.7,
            le=0.95,
            default=0.8,
        ),
    ] = 0.8,
) -> str:
    """
    Find recurring bug patterns based on semantic similarity.

    Groups similar bugs together to identify systemic issues.
    Useful for:
    - Finding bugs that might have a common root cause
    - Identifying areas with recurring problems
    - Prioritizing fixes that address multiple issues

    Returns groups of similar bugs with common characteristics.

    Args:
        ctx: The FastMCP context.
        project: Optional project filter.
        min_similarity: Minimum similarity to group bugs.

    Returns:
        JSON string with bug pattern analysis.
    """
    try:
        engine = _get_insights_engine()
        patterns = engine.find_bug_patterns(
            project_key=project,
            min_similarity=min_similarity,
        )

        if not patterns:
            return json.dumps({
                "message": "No recurring bug patterns found",
                "hint": "Try lowering min_similarity or checking more projects",
            }, indent=2)

        response = {
            "project": project or "all",
            "similarity_threshold": min_similarity,
            "patterns_found": len(patterns),
            "patterns": [
                {
                    "pattern_id": p["pattern_id"],
                    "bug_count": p["bug_count"],
                    "sample_bugs": p["bugs"],
                    "common_terms": p["common_summary_terms"],
                    "statuses": p["statuses"],
                }
                for p in patterns
            ],
            "hint": "Similar bugs may share a root cause - consider linking them",
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Bug patterns error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
        }, indent=2)


@jira_mcp.tool(
    tags={"jira", "vector", "read"},
    annotations={"title": "Project Velocity", "readOnlyHint": True},
)
async def jira_project_velocity(
    ctx: Context,
    project: Annotated[
        str,
        Field(description="Project key to analyze (e.g., 'PROJ')"),
    ],
    weeks: Annotated[
        int,
        Field(
            description="Number of weeks to analyze (2-12)",
            ge=2,
            le=12,
            default=4,
        ),
    ] = 4,
) -> str:
    """
    Calculate velocity metrics for a project.

    Shows weekly creation/resolution rates and backlog trends.
    Useful for:
    - Sprint planning and capacity estimation
    - Tracking team throughput over time
    - Identifying workload imbalances

    Returns weekly metrics with averages and trend direction.

    Args:
        ctx: The FastMCP context.
        project: Project key to analyze.
        weeks: Number of weeks to analyze.

    Returns:
        JSON string with velocity metrics.
    """
    try:
        engine = _get_insights_engine()
        metrics = engine.get_velocity_metrics(
            project_key=project,
            weeks=weeks,
        )

        if "error" in metrics:
            return json.dumps(metrics, indent=2)

        return json.dumps(metrics, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Velocity metrics error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "project": project,
        }, indent=2)


# =============================================================================
# AI-Powered Tools (LLM-based synthesis)
# =============================================================================

# OpenAI client singleton for AI tools
_openai_client: Any = None


def _get_openai_client() -> Any:
    """Get or create OpenAI client singleton."""
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI()
    return _openai_client


@jira_mcp.tool(
    tags={"jira", "vector", "ai", "read"},
    annotations={"title": "AI Summary", "readOnlyHint": True},
)
async def jira_ai_summary(
    ctx: Context,
    issue_keys: Annotated[
        str,
        Field(
            description=(
                "Jira issue key(s) to summarize. Single key (e.g., 'PROJ-123') "
                "or comma-separated list (e.g., 'PROJ-123,PROJ-124,PROJ-125')"
            )
        ),
    ],
    summary_type: Annotated[
        str,
        Field(
            description=(
                "Type of summary: 'brief' (2-3 sentences), 'detailed' (full analysis), "
                "'technical' (implementation focus), 'executive' (business impact)"
            ),
            default="brief",
        ),
    ] = "brief",
    include_comments: Annotated[
        bool,
        Field(
            description="Include comment analysis in the summary",
            default=False,
        ),
    ] = False,
) -> str:
    """
    Generate AI-powered summaries for one or more Jira issues.

    Uses an LLM to analyze issue content and generate human-readable summaries.
    Useful for:
    - Quickly understanding complex issues
    - Creating executive briefings
    - Extracting key technical details
    - Summarizing comment threads and discussions

    Args:
        ctx: The FastMCP context.
        issue_keys: Single key or comma-separated list of issue keys.
        summary_type: Type of summary to generate.
        include_comments: Whether to include comments in analysis.

    Returns:
        JSON string with AI-generated summaries for each issue.
    """
    from mcp_atlassian.servers.dependencies import get_jira_fetcher

    try:
        # Parse issue keys
        keys = [k.strip() for k in issue_keys.split(",") if k.strip()]
        if not keys:
            return json.dumps({
                "error": "No valid issue keys provided",
                "hint": "Provide one or more issue keys, e.g., 'PROJ-123' or 'PROJ-123,PROJ-124'",
            }, indent=2)

        # Validate summary type
        valid_types = ["brief", "detailed", "technical", "executive"]
        if summary_type not in valid_types:
            return json.dumps({
                "error": f"Invalid summary_type '{summary_type}'",
                "valid_types": valid_types,
            }, indent=2)

        # Get Jira client and OpenAI client
        jira = await get_jira_fetcher(ctx)
        client = _get_openai_client()
        config = _get_config()

        # Fetch issues
        summaries = []
        for key in keys:
            try:
                # Fetch issue with full details
                issue = jira.get_issue(
                    issue_key=key,
                    fields="summary,description,status,priority,assignee,reporter,labels,components,created,updated,issuetype",
                    comment_limit=10 if include_comments else 0,
                )

                # Build context for LLM
                issue_context = _build_issue_context(issue, include_comments)

                # Generate summary
                ai_summary = await _generate_summary(
                    client=client,
                    issue_context=issue_context,
                    summary_type=summary_type,
                    model=config.self_query_model,
                )

                summaries.append({
                    "key": key,
                    "title": issue.summary[:100] if issue.summary else "",
                    "status": issue.status.name if issue.status else "Unknown",
                    "type": issue.issue_type.name if issue.issue_type else "Unknown",
                    "ai_summary": ai_summary,
                    "summary_type": summary_type,
                })

            except Exception as e:
                logger.error(f"Failed to summarize {key}: {e}")
                summaries.append({
                    "key": key,
                    "error": str(e),
                })

        response = {
            "total_requested": len(keys),
            "successful": len([s for s in summaries if "ai_summary" in s]),
            "failed": len([s for s in summaries if "error" in s]),
            "summaries": summaries,
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"AI summary error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "issue_keys": issue_keys,
        }, indent=2)


def _build_issue_context(issue: Any, include_comments: bool) -> str:
    """Build context string from issue for LLM consumption."""
    parts = [
        f"Issue: {issue.key}",
        f"Type: {issue.issue_type.name if issue.issue_type else 'Unknown'}",
        f"Status: {issue.status.name if issue.status else 'Unknown'}",
        f"Priority: {issue.priority.name if issue.priority else 'Not set'}",
        f"Summary: {issue.summary}",
    ]

    if issue.assignee:
        assignee_name = issue.assignee.display_name if hasattr(issue.assignee, 'display_name') else str(issue.assignee)
        parts.append(f"Assignee: {assignee_name}")

    if issue.reporter:
        reporter_name = issue.reporter.display_name if hasattr(issue.reporter, 'display_name') else str(issue.reporter)
        parts.append(f"Reporter: {reporter_name}")

    if issue.labels:
        parts.append(f"Labels: {', '.join(issue.labels)}")

    if issue.components:
        parts.append(f"Components: {', '.join(issue.components)}")

    if issue.description:
        # Truncate long descriptions
        desc = issue.description[:2000] if len(issue.description) > 2000 else issue.description
        parts.append(f"\nDescription:\n{desc}")

    if include_comments and issue.comments:
        parts.append(f"\nComments ({len(issue.comments)}):")
        for i, comment in enumerate(issue.comments[:5]):  # Limit to 5 comments
            author = "Unknown"
            if hasattr(comment, 'author') and comment.author:
                author = comment.author.display_name if hasattr(comment.author, 'display_name') else str(comment.author)
            body = comment.body[:300] if hasattr(comment, 'body') and comment.body else ""
            parts.append(f"  [{i+1}] {author}: {body}")

    return "\n".join(parts)


async def _generate_summary(
    client: Any,
    issue_context: str,
    summary_type: str,
    model: str,
) -> str:
    """Generate AI summary using OpenAI."""
    system_prompts = {
        "brief": (
            "You are a technical assistant that creates concise summaries of Jira issues. "
            "Provide a 2-3 sentence summary that captures the essence of the issue. "
            "Focus on: what the issue is about, its current state, and any key details."
        ),
        "detailed": (
            "You are a technical assistant that creates detailed summaries of Jira issues. "
            "Provide a comprehensive analysis including:\n"
            "- Problem/feature description\n"
            "- Current status and progress\n"
            "- Key stakeholders involved\n"
            "- Any blockers or dependencies mentioned\n"
            "- Proposed solutions or next steps (if any)"
        ),
        "technical": (
            "You are a senior software engineer reviewing a Jira issue. "
            "Focus on technical details:\n"
            "- What technical problem or feature is being addressed\n"
            "- Implementation considerations\n"
            "- Potential technical risks or challenges\n"
            "- Dependencies on other systems or components\n"
            "Be specific and technical in your analysis."
        ),
        "executive": (
            "You are creating an executive summary of a Jira issue for leadership. "
            "Focus on business impact:\n"
            "- What is the business value or risk\n"
            "- Who is affected (customers, teams)\n"
            "- Current status in simple terms\n"
            "- Any decisions or escalations needed\n"
            "Keep it concise and jargon-free."
        ),
    }

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompts.get(summary_type, system_prompts["brief"])},
                {"role": "user", "content": f"Please summarize the following Jira issue:\n\n{issue_context}"},
            ],
            temperature=0.3,
            max_tokens=500 if summary_type == "brief" else 1000,
        )

        return response.choices[0].message.content or "(No summary generated)"

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        msg = f"Failed to generate summary: {e!s}"
        raise ValueError(msg) from e


@jira_mcp.tool(
    tags={"jira", "vector", "ai", "read"},
    annotations={"title": "AI Query", "readOnlyHint": True},
)
async def jira_ai_query(
    ctx: Context,
    question: Annotated[
        str,
        Field(
            description=(
                "Natural language question about your Jira issues. Examples:\n"
                "- 'What tickets relate to authentication problems?'\n"
                "- 'What do we know about the payment processing issues?'\n"
                "- 'Summarize recent bugs in the API'\n"
                "- 'What work has been done on performance optimization?'"
            )
        ),
    ],
    project: Annotated[
        str | None,
        Field(
            description="Optional project key to focus the search (e.g., 'PROJ')",
            default=None,
        ),
    ] = None,
    max_issues: Annotated[
        int,
        Field(
            description="Maximum issues to analyze for the answer (3-15)",
            ge=3,
            le=15,
            default=7,
        ),
    ] = 7,
    include_comments: Annotated[
        bool,
        Field(
            description="Search and include comments in the analysis",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Ask natural language questions about your Jira issues and get synthesized answers.

    This tool searches for relevant issues using semantic search, then uses an LLM
    to synthesize a comprehensive answer based on the found issues.

    Unlike simple search tools that return lists, this tool:
    - Understands your question's intent
    - Finds semantically relevant issues
    - Reads and analyzes their content
    - Synthesizes a coherent answer with citations

    Useful for:
    - "What do we know about X?" questions
    - Understanding the state of a feature/bug area
    - Getting context on historical decisions
    - Summarizing work across multiple tickets

    Args:
        ctx: The FastMCP context.
        question: Natural language question to answer.
        project: Optional project filter.
        max_issues: Maximum issues to include in analysis.
        include_comments: Whether to also search comments.

    Returns:
        JSON with synthesized answer and source citations.
    """
    from mcp_atlassian.servers.dependencies import get_jira_fetcher

    try:
        store = _get_store()
        embedder = _get_embedder()
        client = _get_openai_client()
        config = _get_config()

        # Check if index has data
        stats = store.get_stats()
        if stats["total_issues"] == 0:
            return json.dumps({
                "error": "Vector index is empty. Run sync first.",
                "hint": "Use CLI: mcp-atlassian vector sync --full",
            }, indent=2)

        # Generate query embedding
        query_vector = await embedder.embed(question)

        # Build filters
        filters: dict[str, Any] = {}
        if project:
            filters["project_key"] = project

        # Search for relevant issues
        issue_results = store.hybrid_search(
            query_vector=query_vector,
            query_text=question,
            limit=max_issues,
            filters=filters if filters else None,
            fts_weight=config.fts_weight,
        )

        # Also search comments if enabled
        comment_results = []
        if include_comments and stats["total_comments"] > 0:
            comment_results = store.search_comments(
                query_vector=query_vector,
                limit=5,
                filters=filters if filters else None,
            )

        if not issue_results and not comment_results:
            return json.dumps({
                "question": question,
                "answer": "I couldn't find any relevant issues matching your question.",
                "sources": [],
                "hint": "Try rephrasing your question or broadening your search",
            }, indent=2)

        # Fetch full issue details for context
        jira = await get_jira_fetcher(ctx)
        issue_contexts = []

        for result in issue_results:
            try:
                issue = jira.get_issue(
                    issue_key=result["issue_id"],
                    fields="summary,description,status,priority,labels,issuetype",
                    comment_limit=3 if include_comments else 0,
                )
                context = _build_issue_context(issue, include_comments=False)
                issue_contexts.append({
                    "key": result["issue_id"],
                    "summary": result["summary"][:100],
                    "context": context,
                    "score": result.get("score", 0),
                })
            except Exception as e:
                logger.warning(f"Failed to fetch issue {result['issue_id']}: {e}")
                # Use indexed data as fallback
                issue_contexts.append({
                    "key": result["issue_id"],
                    "summary": result["summary"][:100],
                    "context": f"Issue: {result['issue_id']}\nSummary: {result['summary']}\nType: {result.get('issue_type', 'Unknown')}\nStatus: {result.get('status', 'Unknown')}",
                    "score": result.get("score", 0),
                })

        # Add comment context
        comment_contexts = []
        for result in comment_results[:3]:  # Limit to top 3 comments
            comment_contexts.append({
                "issue_key": result["issue_key"],
                "author": result.get("author", "Unknown"),
                "preview": result["body_preview"][:200],
            })

        # Generate synthesized answer
        answer = await _generate_answer(
            client=client,
            question=question,
            issue_contexts=issue_contexts,
            comment_contexts=comment_contexts,
            model=config.self_query_model,
        )

        # Build response with sources
        response = {
            "question": question,
            "answer": answer,
            "sources": {
                "issues": [
                    {
                        "key": ic["key"],
                        "summary": ic["summary"],
                        "relevance": round(ic["score"], 3),
                    }
                    for ic in issue_contexts
                ],
                "comments": [
                    {
                        "issue": cc["issue_key"],
                        "author": cc["author"],
                        "preview": cc["preview"][:80] + "...",
                    }
                    for cc in comment_contexts
                ] if comment_contexts else [],
            },
            "metadata": {
                "issues_analyzed": len(issue_contexts),
                "comments_analyzed": len(comment_contexts),
                "project_filter": project,
            },
        }

        return json.dumps(response, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"AI query error: {e}", exc_info=True)
        return json.dumps({
            "error": str(e),
            "question": question,
        }, indent=2)


async def _generate_answer(
    client: Any,
    question: str,
    issue_contexts: list[dict[str, Any]],
    comment_contexts: list[dict[str, Any]],
    model: str,
) -> str:
    """Generate synthesized answer from issue contexts."""
    # Build context for LLM
    context_parts = ["# Relevant Jira Issues\n"]

    for ic in issue_contexts:
        context_parts.append(f"## {ic['key']} (relevance: {ic['score']:.2f})")
        context_parts.append(ic["context"])
        context_parts.append("")

    if comment_contexts:
        context_parts.append("\n# Relevant Comments\n")
        for cc in comment_contexts:
            context_parts.append(f"- [{cc['issue_key']}] {cc['author']}: {cc['preview']}")

    full_context = "\n".join(context_parts)

    system_prompt = """You are a helpful assistant that answers questions about Jira issues.

Based on the provided issue contexts, synthesize a comprehensive answer to the user's question.

Guidelines:
- Answer the question directly and concisely
- Reference specific issue keys when citing information (e.g., "According to PROJ-123...")
- If information is uncertain or incomplete, say so
- Highlight key patterns or themes across multiple issues
- Keep the answer focused and actionable
- If the issues don't fully answer the question, acknowledge what's missing"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Question: {question}\n\n{full_context}"},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        return response.choices[0].message.content or "(No answer generated)"

    except Exception as e:
        logger.error(f"OpenAI API error generating answer: {e}")
        msg = f"Failed to generate answer: {e!s}"
        raise ValueError(msg) from e
