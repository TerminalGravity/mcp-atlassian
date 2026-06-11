"""Tests for the v2 vector tool surface (knowledge / vector_sync_status)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_atlassian.servers import vector_tools


def test_v2_vector_surface_deletes_legacy_tools():
    for removed in (
        "jira_semantic_search", "jira_find_similar", "jira_detect_duplicates",
        "jira_vector_reload", "jira_knowledge_query", "jira_search_comments",
        "jira_project_insights", "jira_issue_clusters", "jira_issue_trends",
        "jira_bug_patterns", "jira_project_velocity", "jira_ai_summary",
        "jira_ai_query", "jira_resolution_patterns", "jira_cross_project_patterns",
        "jira_project_feature_matrix", "jira_vendor_capabilities",
        "jira_integration_knowledge", "jira_generate_faq", "jira_top_questions",
    ):
        assert not hasattr(vector_tools, removed), f"{removed} should be deleted"
    assert hasattr(vector_tools, "knowledge")
    assert hasattr(vector_tools, "vector_sync_status")
    assert hasattr(vector_tools, "semantic_search_impl")


@pytest.mark.anyio
async def test_semantic_search_impl_empty_index_hint():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 0}
    with patch.object(vector_tools, "_get_store", return_value=store):
        result = await vector_tools.semantic_search_impl("anything")
    assert "empty" in result["error"].lower()


@pytest.mark.anyio
async def test_semantic_search_impl_embed_failure_is_soft():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=RuntimeError("no api key"))
    config = MagicMock(); config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl("auth bug")
    assert "failed" in result["error"].lower()
    assert "hint" in result


@pytest.mark.anyio
async def test_semantic_search_impl_happy_path():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    store.hybrid_search.return_value = (
        [{"issue_id": "DS-1", "summary": "auth bug", "issue_type": "Bug",
          "status": "Open", "project_key": "DS", "score": 0.91}],
        1,
    )
    embedder = MagicMock(); embedder.embed = AsyncMock(return_value=[0.1] * 8)
    config = MagicMock(); config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl("auth bug", limit=5)
    assert result["returned"] == 1
    assert result["results"][0]["key"] == "DS-1"


@pytest.mark.anyio
async def test_semantic_search_impl_exclude_key_no_spurious_has_more():
    """has_more must not be set when the only 'extra' is the excluded source."""
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    # 2 returned (one is the excluded source), total_count=2
    store.hybrid_search.return_value = (
        [
            {"issue_id": "DS-1", "summary": "s", "issue_type": "Bug",
             "status": "Open", "project_key": "DS", "score": 0.99},
            {"issue_id": "DS-2", "summary": "s", "issue_type": "Bug",
             "status": "Open", "project_key": "DS", "score": 0.88},
        ],
        2,
    )
    embedder = MagicMock(); embedder.embed = AsyncMock(return_value=[0.1] * 8)
    config = MagicMock(); config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl("s", limit=5, exclude_key="DS-1")
    assert [r["key"] for r in result["results"]] == ["DS-2"]
    # total_count=2, minus the excluded source =1 effective; 1 result returned → no has_more
    assert "pagination" not in result


@pytest.mark.anyio
async def test_semantic_search_impl_exclude_key_absent_keeps_has_more():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    rows = [
        {"issue_id": f"DS-{i}", "summary": "s", "issue_type": "Bug",
         "status": "Open", "project_key": "DS", "score": 0.9} for i in range(1, 5)
    ]  # DS-1..DS-4, total_count=4; exclude_key DS-99 is NOT among them
    store.hybrid_search.return_value = (rows, 4)
    embedder = MagicMock(); embedder.embed = AsyncMock(return_value=[0.1] * 8)
    config = MagicMock(); config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl("s", limit=3, exclude_key="DS-99")
    assert len(result["results"]) == 3
    assert "pagination" in result  # 4 real matches, none excluded → page 2 exists
