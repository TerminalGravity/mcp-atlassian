"""Aggregations API routes for project-level statistics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from mcp_atlassian.vector.store import LanceDBStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/aggregations", tags=["aggregations"])


def get_store() -> LanceDBStore:
    """Get the LanceDB store (lazy import to avoid circular deps)."""
    from mcp_atlassian.web.server import get_store as _get_store
    return _get_store()


class MultiAggregationRequest(BaseModel):
    """Request for aggregations across multiple projects."""
    project_keys: list[str]


class AggregationResponse(BaseModel):
    """Response containing project aggregation data."""
    project_key: str
    total_issues: int
    by_type: dict[str, int] = {}
    by_status_category: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    top_assignees: dict[str, int] = {}
    top_labels: dict[str, int] = {}
    top_components: dict[str, int] = {}
    error: str | None = None


@router.get("/{project_key}", response_model=AggregationResponse)
async def get_project_aggregations(project_key: str) -> AggregationResponse:
    """Get aggregated statistics for a single project.

    Returns distribution data for issue types, statuses, priorities,
    and top assignees/labels/components.
    """
    try:
        store = get_store()
        result = store.get_project_aggregations(project_key)

        return AggregationResponse(
            project_key=result.get("project_key", project_key),
            total_issues=result.get("total_issues", 0),
            by_type=result.get("by_type", {}),
            by_status_category=result.get("by_status_category", {}),
            by_priority=result.get("by_priority", {}),
            top_assignees=result.get("top_assignees", {}),
            top_labels=result.get("top_labels", {}),
            top_components=result.get("top_components", {}),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Error getting aggregations for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/multi", response_model=list[AggregationResponse])
async def get_multi_project_aggregations(
    request: MultiAggregationRequest
) -> list[AggregationResponse]:
    """Get aggregations for multiple projects at once.

    Useful for cross-project comparison queries.
    """
    if not request.project_keys:
        raise HTTPException(status_code=400, detail="At least one project key required")

    if len(request.project_keys) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 projects per request")

    results: list[AggregationResponse] = []
    store = get_store()

    for project_key in request.project_keys:
        try:
            result = store.get_project_aggregations(project_key)
            results.append(AggregationResponse(
                project_key=result.get("project_key", project_key),
                total_issues=result.get("total_issues", 0),
                by_type=result.get("by_type", {}),
                by_status_category=result.get("by_status_category", {}),
                by_priority=result.get("by_priority", {}),
                top_assignees=result.get("top_assignees", {}),
                top_labels=result.get("top_labels", {}),
                top_components=result.get("top_components", {}),
                error=result.get("error"),
            ))
        except Exception as e:
            logger.warning(f"Error getting aggregations for {project_key}: {e}")
            results.append(AggregationResponse(
                project_key=project_key,
                total_issues=0,
                error=str(e),
            ))

    return results


@router.get("/{project_key}/assignees")
async def get_assignee_distribution(
    project_key: str, limit: int = 20
) -> dict[str, Any]:
    """Get assignee distribution for a project.

    Returns a sorted list of assignees with their issue counts.
    """
    try:
        store = get_store()
        result = store.get_project_aggregations(project_key)

        assignees = result.get("top_assignees", {})
        # Sort and limit
        sorted_assignees = sorted(
            assignees.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]

        return {
            "project_key": project_key,
            "total_issues": result.get("total_issues", 0),
            "assignees": [
                {"name": name, "count": count}
                for name, count in sorted_assignees
            ]
        }
    except Exception as e:
        logger.error(f"Error getting assignee distribution for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_key}/types")
async def get_type_distribution(project_key: str) -> dict[str, Any]:
    """Get issue type distribution for a project."""
    try:
        store = get_store()
        result = store.get_project_aggregations(project_key)

        types = result.get("by_type", {})
        sorted_types = sorted(
            types.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return {
            "project_key": project_key,
            "total_issues": result.get("total_issues", 0),
            "types": [
                {"name": name, "count": count}
                for name, count in sorted_types
            ]
        }
    except Exception as e:
        logger.error(f"Error getting type distribution for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_key}/statuses")
async def get_status_distribution(project_key: str) -> dict[str, Any]:
    """Get status category distribution for a project."""
    try:
        store = get_store()
        result = store.get_project_aggregations(project_key)

        statuses = result.get("by_status_category", {})
        sorted_statuses = sorted(
            statuses.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return {
            "project_key": project_key,
            "total_issues": result.get("total_issues", 0),
            "statuses": [
                {"name": name, "count": count}
                for name, count in sorted_statuses
            ]
        }
    except Exception as e:
        logger.error(f"Error getting status distribution for {project_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
