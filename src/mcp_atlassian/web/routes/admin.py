"""Admin API routes for system health, sync management, and configuration."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:
    from mcp_atlassian.jira import JiraFacade
    from mcp_atlassian.vector.store import LanceDBStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Track server start time
_start_time = time.time()

# Track the currently running sync engine for cancellation support
_active_sync_engine: Any = None


def get_store() -> LanceDBStore:
    """Get the LanceDB store (lazy import to avoid circular deps)."""
    from mcp_atlassian.web.server import get_store as _get_store

    return _get_store()


def get_jira() -> JiraFacade:
    """Get the Jira facade (lazy import to avoid circular deps)."""
    from mcp_atlassian.web.server import get_jira as _get_jira

    return _get_jira()


def get_scheduler():
    """Get the sync scheduler (lazy import to avoid circular deps)."""
    from mcp_atlassian.web.server import _scheduler

    return _scheduler


# ---------------------------------------------------------------------------
# GET /api/admin/system — Combined system health
# ---------------------------------------------------------------------------


@router.get("/system")
async def get_system_health() -> dict[str, Any]:
    """Get combined system health: server, Jira, vector store, and sync."""
    # Server info
    server_info = {
        "status": "healthy",
        "uptime_seconds": round(time.time() - _start_time, 1),
    }

    # Jira connection info
    jira_info: dict[str, Any] = {"connected": False, "url": None, "user": None}
    try:
        jira = get_jira()
        jira_info["connected"] = True
        jira_info["url"] = os.getenv("JIRA_URL")
        jira_info["user"] = os.getenv("JIRA_USERNAME")
    except Exception:
        pass

    # Vector store info
    store_info: dict[str, Any] = {
        "total_issues": 0,
        "total_comments": 0,
        "projects": [],
        "project_counts": {},
        "db_path": "",
    }
    try:
        store = get_store()
        stats = store.get_stats()
        projects = stats.get("projects", [])
        # Get per-project issue counts for distribution chart
        project_counts: dict[str, int] = {}
        for proj in projects:
            try:
                ids = store.get_all_issue_ids(project_key=proj)
                project_counts[proj] = len(ids)
            except Exception:
                project_counts[proj] = 0
        store_info = {
            "total_issues": stats.get("total_issues", 0),
            "total_comments": stats.get("total_comments", 0),
            "projects": projects,
            "project_counts": project_counts,
            "db_path": stats.get("db_path", ""),
        }
    except Exception as e:
        logger.warning(f"Failed to get vector store stats: {e}")

    # Sync info
    scheduler = get_scheduler()
    if scheduler:
        sync_info = {"enabled": True, **scheduler.status}
    else:
        from mcp_atlassian.vector.config import VectorConfig

        config = VectorConfig.from_env()
        sync_info = {
            "enabled": False,
            "running": False,
            "interval_minutes": config.sync_interval_minutes,
            "last_sync": None,
            "sync_count": 0,
            "error_count": 0,
            "last_result": None,
        }

    return {
        "server": server_info,
        "jira": jira_info,
        "vector_store": store_info,
        "sync": sync_info,
    }


# ---------------------------------------------------------------------------
# GET /api/admin/config — Current VectorConfig
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Get current vector configuration (read-only)."""
    from mcp_atlassian.vector.config import VectorConfig

    config = VectorConfig.from_env()
    data = asdict(config)
    # Convert Path to string for JSON serialization
    data["db_path"] = str(data["db_path"])
    return data


# ---------------------------------------------------------------------------
# GET /api/admin/projects — Available Jira projects
# ---------------------------------------------------------------------------


@router.get("/projects")
async def get_projects() -> dict[str, Any]:
    """Get available Jira projects."""
    try:
        jira = get_jira()
        projects = jira.get_all_projects()
        return {
            "projects": [
                {"key": p.get("key", ""), "name": p.get("name", "")}
                for p in projects
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get projects: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# POST /api/admin/jira/test — Test Jira connection
# ---------------------------------------------------------------------------


@router.post("/jira/test")
async def test_jira_connection() -> dict[str, Any]:
    """Test the Jira connection and return status."""
    try:
        jira = get_jira()
        projects = jira.get_all_projects()
        return {
            "connected": True,
            "message": "Successfully connected to Jira",
            "projects_count": len(projects),
        }
    except Exception as e:
        return {
            "connected": False,
            "message": f"Connection failed: {e}",
            "projects_count": None,
        }


# ---------------------------------------------------------------------------
# POST /api/admin/sync/full — Trigger full sync
# ---------------------------------------------------------------------------


class FullSyncRequest(BaseModel):
    """Request body for full sync."""

    projects: list[str] | None = None
    start_date: str | None = None  # "YYYY-MM-DD"
    end_date: str | None = None  # "YYYY-MM-DD"


async def _run_full_sync(
    projects: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> None:
    """Run full sync in background."""
    global _active_sync_engine
    try:
        from mcp_atlassian.vector.sync import VectorSyncEngine

        jira = get_jira()
        engine = VectorSyncEngine(jira)
        _active_sync_engine = engine
        await engine.full_sync(
            projects=projects, start_date=start_date, end_date=end_date
        )
    except Exception as e:
        logger.error(f"Background full sync failed: {e}", exc_info=True)
    finally:
        _active_sync_engine = None


@router.post("/sync/full")
async def trigger_full_sync(
    request: FullSyncRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Trigger a full sync. Runs in the background — poll /api/sync/status."""
    background_tasks.add_task(
        _run_full_sync, request.projects, request.start_date, request.end_date
    )
    return {"started": True}


# ---------------------------------------------------------------------------
# POST /api/admin/sync/cancel — Cancel a running sync
# ---------------------------------------------------------------------------


@router.post("/sync/cancel")
async def cancel_sync() -> dict[str, Any]:
    """Cancel a running sync operation."""
    if _active_sync_engine is not None:
        _active_sync_engine.cancel()
        return {"cancelled": True, "message": "Cancellation requested"}
    return {"cancelled": False, "message": "No sync is currently running"}


# ---------------------------------------------------------------------------
# POST /api/admin/sync/preview — Preview issue counts before syncing
# ---------------------------------------------------------------------------


class SyncPreviewRequest(BaseModel):
    """Request body for sync preview."""

    projects: list[str]
    start_date: str | None = None
    end_date: str | None = None


@router.post("/sync/preview")
async def preview_sync(request: SyncPreviewRequest) -> dict[str, Any]:
    """Count issues per project that would be synced."""
    try:
        jira = get_jira()
        counts: dict[str, int] = {}
        for proj in request.projects:
            parts = [f'project = "{proj}"']
            if request.start_date:
                parts.append(f'updated >= "{request.start_date}"')
            else:
                # Default: 1 year lookback (matches full_sync default)
                from datetime import datetime

                from dateutil.relativedelta import relativedelta

                one_year_ago = (
                    datetime.utcnow().replace(day=1, month=1, hour=0, minute=0, second=0)
                    - relativedelta(years=1)
                )
                parts.append(f'updated >= "{one_year_ago.strftime("%Y-%m-%d")}"')
            if request.end_date:
                parts.append(f'updated <= "{request.end_date}"')
            jql = " AND ".join(parts)
            result = jira.search_issues(jql=jql, fields="key", limit=1)
            counts[proj] = result.total if hasattr(result, "total") and result.total >= 0 else len(result.issues)
        return {"counts": counts, "total": sum(counts.values())}
    except Exception as e:
        logger.error(f"Sync preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# POST /api/admin/sync/clear — Clear indexed data for specific projects
# ---------------------------------------------------------------------------


class ClearProjectsRequest(BaseModel):
    """Request body for clearing project data."""

    projects: list[str]


@router.post("/sync/clear")
async def clear_projects(request: ClearProjectsRequest) -> dict[str, Any]:
    """Clear indexed data for specific projects."""
    try:
        store = get_store()
        cleared: dict[str, int] = {}
        for proj in request.projects:
            count = store.clear_issues(project_key=proj)
            cleared[proj] = count
        return {"cleared": cleared, "total": sum(cleared.values())}
    except Exception as e:
        logger.error(f"Clear projects failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# POST /api/admin/db/compact — Compact vector store
# ---------------------------------------------------------------------------


@router.post("/db/compact")
async def compact_database() -> dict[str, Any]:
    """Compact the vector store to reduce storage and improve performance."""
    try:
        store = get_store()
        store.compact()
        return {"success": True, "message": "Database compacted successfully"}
    except Exception as e:
        logger.error(f"Compact failed: {e}")
        return {"success": False, "message": f"Compact failed: {e}"}
