"""Web API routes for Jira Knowledge."""

from mcp_atlassian.web.routes.admin import router as admin_router
from mcp_atlassian.web.routes.aggregations import router as aggregations_router
from mcp_atlassian.web.routes.insights import router as insights_router

__all__ = ["admin_router", "aggregations_router", "insights_router"]
