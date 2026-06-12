"""Integration smoke test pinning the assembled v2 tool surface.

The consolidation's entire value is the 20-tool surface. The vector tools
register on jira_mcp via a try/except ImportError at the tail of jira.py — a
genuine bug there would silently drop the surface to 18 with only a debug log.
This test pins the exact assembled surface so any silent drop fails loudly.

NOTE: imports here use the NON-``src.``-prefixed module path
(``mcp_atlassian.servers.jira``), matching how the real server assembles in
main.py. The vector tools register on that module object; the ``src.``-prefixed
import is a *different* module object onto which they never register (would
show only 14 jira tools). Do not "fix" these to ``src.`` imports.
"""

import asyncio

EXPECTED_JIRA = {
    "agile", "assign", "comment", "create", "delete", "find", "get",
    "handoff", "knowledge", "link", "projects", "transition", "update",
    "vector_sync_status", "versions", "worklog",
}
EXPECTED_CONFLUENCE = {"comment", "find", "get", "write"}


def test_jira_surface_is_exactly_16_tools():
    from mcp_atlassian.servers.jira import jira_mcp

    tools = set(asyncio.run(jira_mcp.get_tools()))
    assert tools == EXPECTED_JIRA, (
        f"jira surface drifted. Missing: {EXPECTED_JIRA - tools}; "
        f"unexpected: {tools - EXPECTED_JIRA}"
    )


def test_confluence_surface_is_exactly_4_tools():
    from mcp_atlassian.servers.confluence import confluence_mcp

    tools = set(asyncio.run(confluence_mcp.get_tools()))
    assert tools == EXPECTED_CONFLUENCE, (
        f"confluence surface drifted. Missing: {EXPECTED_CONFLUENCE - tools}; "
        f"unexpected: {tools - EXPECTED_CONFLUENCE}"
    )


def test_vector_tools_registered_on_jira_mcp():
    """The knowledge + vector_sync_status tools must survive the tail import."""
    from mcp_atlassian.servers.jira import jira_mcp

    tools = set(asyncio.run(jira_mcp.get_tools()))
    assert {"knowledge", "vector_sync_status"} <= tools, (
        "vector tools failed to register — the tail ImportError in jira.py may "
        "have silently swallowed a real error."
    )


def test_total_v2_surface_is_20():
    from mcp_atlassian.servers.confluence import confluence_mcp
    from mcp_atlassian.servers.jira import jira_mcp

    total = len(asyncio.run(jira_mcp.get_tools())) + len(
        asyncio.run(confluence_mcp.get_tools())
    )
    assert total == 20, f"expected 20 v2 tools, assembled {total}"
