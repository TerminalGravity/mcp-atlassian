"""Insights API routes for trend analysis, velocity, and clustering."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

if TYPE_CHECKING:
    from mcp_atlassian.vector.insights import InsightsEngine
    from mcp_atlassian.vector.store import LanceDBStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])


def get_store() -> LanceDBStore:
    """Get the LanceDB store (lazy import to avoid circular deps)."""
    from mcp_atlassian.web.server import get_store as _get_store
    return _get_store()


def get_insights_engine() -> InsightsEngine:
    """Get or create the InsightsEngine."""
    from mcp_atlassian.vector.insights import InsightsEngine
    return InsightsEngine(get_store())


@router.get("/trends")
async def get_trends(
    project_key: str | None = Query(None, description="Optional project filter"),
    days: int = Query(30, ge=7, le=365, description="Days to analyze"),
    period_days: int = Query(7, ge=1, le=30, description="Days per period"),
) -> dict[str, Any]:
    """Analyze issue creation/resolution trends over time.

    Returns time-series data suitable for trend charts showing:
    - Issues created per period
    - Issues resolved per period
    - Net change (backlog growth/shrink)
    - Breakdown by type and priority
    """
    try:
        engine = get_insights_engine()
        trends = engine.analyze_trends(
            project_key=project_key,
            days=days,
            period_days=period_days
        )

        # Convert dataclasses to dicts for JSON serialization
        return {
            "project_key": project_key,
            "days_analyzed": days,
            "period_days": period_days,
            "periods": [
                {
                    "period_start": t.period_start.isoformat(),
                    "period_end": t.period_end.isoformat(),
                    "total_created": t.total_created,
                    "total_resolved": t.total_resolved,
                    "net_change": t.net_change,
                    "by_type": t.by_type,
                    "by_priority": t.by_priority,
                    "trending_labels": [
                        {"label": label, "count": count}
                        for label, count in t.trending_labels
                    ],
                }
                for t in trends
            ]
        }
    except Exception as e:
        logger.error(f"Error analyzing trends: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/velocity/{project_key}")
async def get_velocity(
    project_key: str,
    weeks: int = Query(4, ge=1, le=12, description="Weeks to analyze"),
) -> dict[str, Any]:
    """Get velocity metrics for a project.

    Returns weekly throughput data including:
    - Issues created/resolved per week
    - Average velocity metrics
    - Backlog trend direction
    """
    try:
        engine = get_insights_engine()
        velocity = engine.get_velocity_metrics(project_key, weeks=weeks)

        return velocity
    except Exception as e:
        logger.error(f"Error getting velocity for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/clusters")
async def get_clusters(
    project_key: str | None = Query(None, description="Optional project filter"),
    n_clusters: int = Query(5, ge=2, le=20, description="Number of clusters"),
    min_cluster_size: int = Query(3, ge=2, le=50, description="Min cluster size"),
) -> dict[str, Any]:
    """Cluster issues by semantic similarity.

    Uses K-means clustering on issue embeddings to identify
    natural groupings/themes. Useful for understanding what
    areas of work are most active.
    """
    try:
        engine = get_insights_engine()
        clusters = engine.cluster_issues(
            project_key=project_key,
            n_clusters=n_clusters,
            min_cluster_size=min_cluster_size
        )

        return {
            "project_key": project_key,
            "n_clusters": n_clusters,
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "size": c.size,
                    "representative_issues": c.representative_issues,
                    "common_labels": c.common_labels,
                    "common_components": c.common_components,
                    "theme_keywords": c.theme_keywords,
                }
                for c in clusters
            ]
        }
    except Exception as e:
        logger.error(f"Error clustering issues: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/bug-patterns")
async def get_bug_patterns(
    project_key: str | None = Query(None, description="Optional project filter"),
    min_similarity: float = Query(
        0.8, ge=0.5, le=1.0, description="Similarity threshold"
    ),
) -> dict[str, Any]:
    """Find recurring bug patterns based on semantic similarity.

    Groups similar bugs to identify patterns that might
    indicate systemic issues or areas needing attention.
    """
    try:
        engine = get_insights_engine()
        patterns = engine.find_bug_patterns(
            project_key=project_key,
            min_similarity=min_similarity
        )

        return {
            "project_key": project_key,
            "min_similarity": min_similarity,
            "patterns": patterns
        }
    except Exception as e:
        logger.error(f"Error finding bug patterns: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/summary/{project_key}")
async def get_project_summary(project_key: str) -> dict[str, Any]:
    """Get a comprehensive summary of project insights.

    Combines aggregations, velocity, and trends into a single response
    for dashboard-style display.
    """
    try:
        store = get_store()
        engine = get_insights_engine()

        # Get aggregations
        aggregations = store.get_project_aggregations(project_key)

        # Get velocity (last 4 weeks)
        velocity = engine.get_velocity_metrics(project_key, weeks=4)

        # Get recent trends (last 30 days, weekly)
        trends = engine.analyze_trends(
            project_key=project_key,
            days=30,
            period_days=7
        )

        return {
            "project_key": project_key,
            "aggregations": {
                "total_issues": aggregations.get("total_issues", 0),
                "by_type": aggregations.get("by_type", {}),
                "by_status_category": aggregations.get("by_status_category", {}),
                "by_priority": aggregations.get("by_priority", {}),
                "top_assignees": aggregations.get("top_assignees", {}),
            },
            "velocity": velocity,
            "trends": [
                {
                    "period_start": t.period_start.isoformat(),
                    "period_end": t.period_end.isoformat(),
                    "total_created": t.total_created,
                    "total_resolved": t.total_resolved,
                    "net_change": t.net_change,
                }
                for t in trends
            ]
        }
    except Exception as e:
        logger.error(f"Error getting project summary for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
