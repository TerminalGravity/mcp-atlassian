"""Unit tests for the Jira FastMCP server implementation."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client import FastMCPTransport
from fastmcp.exceptions import ToolError
from starlette.requests import Request

from src.mcp_atlassian.jira import JiraFetcher
from src.mcp_atlassian.jira.config import JiraConfig
from src.mcp_atlassian.servers.context import MainAppContext
from src.mcp_atlassian.servers.main import AtlassianMCP
from src.mcp_atlassian.utils.oauth import OAuthConfig
from tests.fixtures.jira_mocks import (
    MOCK_JIRA_COMMENTS_SIMPLIFIED,
    MOCK_JIRA_ISSUE_RESPONSE_SIMPLIFIED,
    MOCK_JIRA_JQL_RESPONSE_SIMPLIFIED,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_jira_fetcher():
    """Create a mock JiraFetcher using predefined responses from fixtures."""
    mock_fetcher = MagicMock(spec=JiraFetcher)
    mock_fetcher.config = MagicMock()
    mock_fetcher.config.read_only = False
    mock_fetcher.config.url = "https://test.atlassian.net"
    mock_fetcher.config.projects_filter = None  # Explicitly set to None by default

    # Configure common methods
    mock_fetcher.get_current_user_account_id.return_value = "test-account-id"
    mock_fetcher.jira = MagicMock()

    # Configure get_issue to return fixture data
    def mock_get_issue(
        issue_key,
        fields=None,
        expand=None,
        comment_limit=10,
        properties=None,
        update_history=True,
    ):
        if not issue_key:
            raise ValueError("Issue key is required")
        mock_issue = MagicMock()
        response_data = MOCK_JIRA_ISSUE_RESPONSE_SIMPLIFIED.copy()
        response_data["key"] = issue_key
        response_data["fields_queried"] = fields
        response_data["expand_param"] = expand
        response_data["comment_limit"] = comment_limit
        response_data["properties_param"] = properties
        response_data["update_history"] = update_history
        response_data["id"] = MOCK_JIRA_ISSUE_RESPONSE_SIMPLIFIED["id"]
        response_data["summary"] = MOCK_JIRA_ISSUE_RESPONSE_SIMPLIFIED["fields"][
            "summary"
        ]
        response_data["status"] = {
            "name": MOCK_JIRA_ISSUE_RESPONSE_SIMPLIFIED["fields"]["status"]["name"]
        }
        mock_issue.to_simplified_dict.return_value = response_data
        return mock_issue

    mock_fetcher.get_issue.side_effect = mock_get_issue

    # Configure get_issue_comments to return fixture data
    def mock_get_issue_comments(issue_key, limit=10):
        return MOCK_JIRA_COMMENTS_SIMPLIFIED["comments"][:limit]

    mock_fetcher.get_issue_comments.side_effect = mock_get_issue_comments

    # Configure search_issues to return fixture data
    def mock_search_issues(jql, **kwargs):
        mock_search_result = MagicMock()
        issues = []
        for issue_data in MOCK_JIRA_JQL_RESPONSE_SIMPLIFIED["issues"]:
            mock_issue = MagicMock()
            mock_issue.to_simplified_dict.return_value = issue_data
            issues.append(mock_issue)
        mock_search_result.issues = issues
        mock_search_result.total = len(issues)
        mock_search_result.start_at = kwargs.get("start", 0)
        mock_search_result.max_results = kwargs.get("limit", 50)
        mock_search_result.to_simplified_dict.return_value = {
            "total": len(issues),
            "start_at": kwargs.get("start", 0),
            "max_results": kwargs.get("limit", 50),
            "issues": [issue.to_simplified_dict() for issue in issues],
        }
        return mock_search_result

    mock_fetcher.search_issues.side_effect = mock_search_issues

    # Configure create_issue
    def mock_create_issue(
        project_key,
        summary,
        issue_type,
        description=None,
        assignee=None,
        components=None,
        **additional_fields,
    ):
        if not project_key or project_key.strip() == "":
            raise ValueError("valid project is required")
        components_list = None
        if components:
            if isinstance(components, str):
                components_list = components.split(",")
            elif isinstance(components, list):
                components_list = components
        mock_issue = MagicMock()
        response_data = {
            "key": f"{project_key}-456",
            "summary": summary,
            "description": description,
            "issue_type": {"name": issue_type},
            "status": {"name": "Open"},
            "components": [{"name": comp} for comp in components_list]
            if components_list
            else [],
            **additional_fields,
        }
        mock_issue.to_simplified_dict.return_value = response_data
        return mock_issue

    mock_fetcher.create_issue.side_effect = mock_create_issue

    # Configure batch_create_issues
    def mock_batch_create_issues(issues, validate_only=False):
        if not isinstance(issues, list):
            try:
                parsed_issues = json.loads(issues)
                if not isinstance(parsed_issues, list):
                    raise ValueError(
                        "Issues must be a list or a valid JSON array string."
                    )
                issues = parsed_issues
            except (json.JSONDecodeError, TypeError):
                raise ValueError("Issues must be a list or a valid JSON array string.")
        mock_issues = []
        for idx, issue_data in enumerate(issues, 1):
            mock_issue = MagicMock()
            mock_issue.to_simplified_dict.return_value = {
                "key": f"{issue_data['project_key']}-{idx}",
                "summary": issue_data["summary"],
                "issue_type": {"name": issue_data["issue_type"]},
                "status": {"name": "To Do"},
            }
            mock_issues.append(mock_issue)
        return mock_issues

    mock_fetcher.batch_create_issues.side_effect = mock_batch_create_issues

    # Configure get_epic_issues
    def mock_get_epic_issues(epic_key, start=0, limit=50):
        mock_issues = []
        for i in range(1, 4):
            mock_issue = MagicMock()
            mock_issue.to_simplified_dict.return_value = {
                "key": f"TEST-{i}",
                "summary": f"Epic Issue {i}",
                "issue_type": {"name": "Task" if i % 2 == 0 else "Bug"},
                "status": {"name": "To Do" if i % 2 == 0 else "In Progress"},
            }
            mock_issues.append(mock_issue)
        return mock_issues[start : start + limit]

    mock_fetcher.get_epic_issues.side_effect = mock_get_epic_issues

    # Configure get_all_projects
    def mock_get_all_projects(include_archived=False):
        projects = [
            {
                "id": "10000",
                "key": "TEST",
                "name": "Test Project",
                "description": "Project for testing",
                "lead": {"name": "admin", "displayName": "Administrator"},
                "projectTypeKey": "software",
                "archived": False,
            }
        ]
        if include_archived:
            projects.append(
                {
                    "id": "10001",
                    "key": "ARCHIVED",
                    "name": "Archived Project",
                    "description": "Archived project",
                    "lead": {"name": "admin", "displayName": "Administrator"},
                    "projectTypeKey": "software",
                    "archived": True,
                }
            )
        return projects

    # Set default side_effect to respect include_archived parameter
    mock_fetcher.get_all_projects.side_effect = mock_get_all_projects

    mock_fetcher.jira.jql.return_value = {
        "issues": [
            {
                "fields": {
                    "project": {
                        "key": "TEST",
                        "name": "Test Project",
                        "description": "Project for testing",
                    }
                }
            }
        ]
    }

    from src.mcp_atlassian.models.jira.common import JiraUser

    mock_user = MagicMock(spec=JiraUser)
    mock_user.to_simplified_dict.return_value = {
        "display_name": "Test User (test.profile@example.com)",
        "name": "Test User (test.profile@example.com)",
        "email": "test.profile@example.com",
        "avatar_url": "https://test.atlassian.net/avatar/test.profile@example.com",
    }
    mock_get_user_profile = MagicMock()

    def side_effect_func(identifier):
        if identifier == "nonexistent@example.com":
            raise ValueError(f"User '{identifier}' not found.")
        return mock_user

    mock_get_user_profile.side_effect = side_effect_func
    mock_fetcher.get_user_profile_by_identifier = mock_get_user_profile
    return mock_fetcher


@pytest.fixture
def mock_base_jira_config():
    """Create a mock base JiraConfig for MainAppContext using OAuth for multi-user scenario."""
    mock_oauth_config = OAuthConfig(
        client_id="server_client_id",
        client_secret="server_client_secret",
        redirect_uri="http://localhost",
        scope="read:jira-work",
        cloud_id="mock_jira_cloud_id",
    )
    return JiraConfig(
        url="https://mock-jira.atlassian.net",
        auth_type="oauth",
        oauth_config=mock_oauth_config,
    )


@pytest.fixture
def test_jira_mcp(mock_jira_fetcher, mock_base_jira_config):
    """Create a test FastMCP instance with standard configuration."""

    @asynccontextmanager
    async def test_lifespan(app: FastMCP) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(
                full_jira_config=mock_base_jira_config, read_only=False
            )
        finally:
            pass

    test_mcp = AtlassianMCP(
        "TestJira", instructions="Test Jira MCP Server", lifespan=test_lifespan
    )
    from src.mcp_atlassian.servers.jira import (
        agile, assign, attach, comment, create, delete, find, get, handoff,
        link, projects, transition, update, versions, worklog,
    )

    jira_sub_mcp = FastMCP(name="TestJiraSubMCP")
    for _tool in (agile, assign, attach, comment, create, delete, find, get,
                  handoff, link, projects, transition, update, versions, worklog):
        jira_sub_mcp.add_tool(_tool)
    test_mcp.mount(jira_sub_mcp, prefix="jira")
    return test_mcp


@pytest.fixture
def no_fetcher_test_jira_mcp(mock_base_jira_config):
    """Create a test FastMCP instance that simulates missing Jira fetcher."""

    @asynccontextmanager
    async def no_fetcher_test_lifespan(
        app: FastMCP,
    ) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(full_jira_config=None, read_only=False)
        finally:
            pass

    test_mcp = AtlassianMCP(
        "NoFetcherTestJira",
        instructions="No Fetcher Test Jira MCP Server",
        lifespan=no_fetcher_test_lifespan,
    )
    from src.mcp_atlassian.servers.jira import get

    jira_sub_mcp = FastMCP(name="NoFetcherTestJiraSubMCP")
    jira_sub_mcp.add_tool(get)
    test_mcp.mount(jira_sub_mcp, prefix="jira")
    return test_mcp


@pytest.fixture
def mock_request():
    """Provides a mock Starlette Request object with a state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.jira_fetcher = None
    request.state.user_atlassian_auth_type = None
    request.state.user_atlassian_token = None
    request.state.user_atlassian_email = None
    return request


@pytest.fixture
async def jira_client(test_jira_mcp, mock_jira_fetcher, mock_request):
    """Create a FastMCP client with mocked Jira fetcher and request state."""
    with (
        patch(
            "src.mcp_atlassian.servers.jira.get_jira_fetcher",
            AsyncMock(return_value=mock_jira_fetcher),
        ),
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            return_value=mock_request,
        ),
    ):
        async with Client(transport=FastMCPTransport(test_jira_mcp)) as client_instance:
            yield client_instance


@pytest.fixture
async def no_fetcher_client_fixture(no_fetcher_test_jira_mcp, mock_request):
    """Create a client that simulates missing Jira fetcher configuration."""
    async with Client(
        transport=FastMCPTransport(no_fetcher_test_jira_mcp)
    ) as client_for_no_fetcher:
        yield client_for_no_fetcher






@pytest.mark.anyio
async def test_create_issue(jira_client, mock_jira_fetcher):
    """Test the create_issue tool with fixture data."""
    response = await jira_client.call_tool(
        "jira_create",
        {
            "project_key": "TEST",
            "summary": "New Issue",
            "issue_type": "Task",
            "description": "This is a new task",
            "components": "Frontend,API",
            "additional_fields": {"priority": {"name": "Medium"}},
            # summary is the default (D2 token-bloat fix); the full echo this
            # test asserts is now opt-in.
            "return_mode": "full",
        },
    )
    assert hasattr(response, "content")
    assert len(response.content) > 0
    text_content = response.content[0]
    assert text_content.type == "text"
    content = json.loads(text_content.text)
    assert content["message"] == "Issue created successfully"
    assert "issue" in content
    assert content["issue"]["key"] == "TEST-456"
    assert content["issue"]["summary"] == "New Issue"
    assert content["issue"]["description"] == "This is a new task"
    assert "components" in content["issue"]
    component_names = [comp["name"] for comp in content["issue"]["components"]]
    assert "Frontend" in component_names
    assert "API" in component_names
    assert content["issue"]["priority"] == {"name": "Medium"}
    mock_jira_fetcher.create_issue.assert_called_once_with(
        project_key="TEST",
        summary="New Issue",
        issue_type="Task",
        description="This is a new task",
        assignee=None,
        components=["Frontend", "API"],
        priority={"name": "Medium"},
    )


@pytest.mark.anyio
async def test_create_issue_accepts_json_string(jira_client, mock_jira_fetcher):
    """Ensure additional_fields can be a JSON string."""
    response = await jira_client.call_tool(
        "jira_create",
        {
            "project_key": "TEST",
            "summary": "JSON Issue",
            "issue_type": "Task",
            "additional_fields": '{"labels": ["ai", "test"]}',
        },
    )
    assert hasattr(response, "content")
    assert len(response.content) > 0
    text_content = response.content[0]
    assert text_content.type == "text"
    content = json.loads(text_content.text)
    assert content["message"] == "Issue created successfully"
    assert "issue" in content
    mock_jira_fetcher.create_issue.assert_called_with(
        project_key="TEST",
        summary="JSON Issue",
        issue_type="Task",
        description=None,
        assignee=None,
        components=None,
        labels=["ai", "test"],
    )


@pytest.mark.anyio
async def test_create_issue_additional_fields_empty_string(jira_client):
    """Test that empty string additional_fields raises ValueError."""
    with pytest.raises(ToolError) as excinfo:
        await jira_client.call_tool(
            "jira_create",
            {
                "project_key": "TEST",
                "summary": "Test issue",
                "issue_type": "Task",
                "additional_fields": "",
            },
        )
    assert "not valid JSON" in str(excinfo.value)


@pytest.mark.anyio
async def test_create_issue_additional_fields_invalid_json(jira_client):
    """Test that invalid JSON additional_fields raises ValueError."""
    with pytest.raises(ToolError) as excinfo:
        await jira_client.call_tool(
            "jira_create",
            {
                "project_key": "TEST",
                "summary": "Test issue",
                "issue_type": "Task",
                "additional_fields": "{invalid json",
            },
        )
    assert "not valid JSON" in str(excinfo.value)


@pytest.mark.anyio
async def test_create_issue_additional_fields_non_dict_json(jira_client):
    """Test that JSON array additional_fields raises ValueError."""
    with pytest.raises(ToolError) as excinfo:
        await jira_client.call_tool(
            "jira_create",
            {
                "project_key": "TEST",
                "summary": "Test issue",
                "issue_type": "Task",
                "additional_fields": '["item1", "item2"]',
            },
        )
    assert "not a JSON object" in str(excinfo.value)


@pytest.mark.anyio
async def test_create_issue_bad_type_lists_valid_types(jira_client, mock_jira_fetcher):
    """When create_issue fails because the project rejects the issue_type, the
    error must list the project's creatable types so the agent self-corrects in
    one shot (no jira_get discovery round-trips)."""
    mock_jira_fetcher.create_issue.side_effect = ValueError(
        "issue type Epic is not valid for project AI"
    )
    mock_jira_fetcher.get_project_issue_types.return_value = [
        {"id": "1", "name": "Story"},
        {"id": "2", "name": "Task"},
        {"id": "3", "name": "Bug"},
        {"id": "4", "name": "Sub-task"},
    ]
    with pytest.raises(ToolError) as excinfo:
        await jira_client.call_tool(
            "jira_create",
            {"project_key": "AI", "summary": "X", "issue_type": "Epic", "force": True},
        )
    msg = str(excinfo.value)
    # All valid types surfaced for self-correction.
    for name in ("Story", "Task", "Bug", "Sub-task"):
        assert name in msg
    assert "AI" in msg
    mock_jira_fetcher.get_project_issue_types.assert_called_once_with("AI")


@pytest.mark.anyio
async def test_create_issue_success_skips_issue_type_lookup(
    jira_client, mock_jira_fetcher
):
    """Happy path must NOT pay the issue-type lookup round-trip — the enrich
    step only runs when create_issue fails."""
    response = await jira_client.call_tool(
        "jira_create",
        {"project_key": "TEST", "summary": "Fine", "issue_type": "Task"},
    )
    text_content = response.content[0]
    content = json.loads(text_content.text)
    assert content["message"] == "Issue created successfully"
    mock_jira_fetcher.get_project_issue_types.assert_not_called()








@pytest.mark.anyio
async def test_no_fetcher_get_issue(no_fetcher_client_fixture, mock_request):
    """Test that get_issue fails when Jira client is not configured (global config missing)."""

    async def mock_get_fetcher_error(*args, **kwargs):
        raise ValueError(
            "Mocked: Jira client (fetcher) not available. Ensure server is configured correctly."
        )

    with (
        patch(
            "src.mcp_atlassian.servers.jira.get_jira_fetcher",
            AsyncMock(side_effect=mock_get_fetcher_error),
        ),
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            return_value=mock_request,
        ),
    ):
        with pytest.raises(ToolError) as excinfo:
            await no_fetcher_client_fixture.call_tool(
                "jira_get",
                {
                    "keys": "TEST-123",
                },
            )
    assert "Error calling tool 'get'" in str(excinfo.value)


@pytest.mark.anyio
async def test_get_issue_with_user_specific_fetcher_in_state(
    test_jira_mcp, mock_jira_fetcher, mock_base_jira_config
):
    """Test jira_get uses fetcher from request.state if UserTokenMiddleware provided it."""
    _mock_request_with_fetcher_in_state = MagicMock(spec=Request)
    _mock_request_with_fetcher_in_state.state = MagicMock()
    _mock_request_with_fetcher_in_state.state.jira_fetcher = mock_jira_fetcher
    _mock_request_with_fetcher_in_state.state.user_atlassian_auth_type = "oauth"
    _mock_request_with_fetcher_in_state.state.user_atlassian_token = (
        "user_specific_token"
    )

    # Define the specific fields we expect for this test case
    test_fields_str = "summary,status,issuetype"
    expected_fields_list = ["summary", "status", "issuetype"]

    # Import the real get_jira_fetcher to test its interaction with request.state
    from src.mcp_atlassian.servers.dependencies import (
        get_jira_fetcher as get_jira_fetcher_real,
    )

    with (
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            return_value=_mock_request_with_fetcher_in_state,
        ) as mock_get_http,
        patch(
            "src.mcp_atlassian.servers.jira.get_jira_fetcher",
            side_effect=AsyncMock(wraps=get_jira_fetcher_real),
        ),
    ):
        async with Client(transport=FastMCPTransport(test_jira_mcp)) as client_instance:
            response = await client_instance.call_tool(
                "jira_get",
                {"keys": "USER-STATE-1", "fields": test_fields_str},
            )

    mock_get_http.assert_called()
    mock_jira_fetcher.get_issue.assert_called_with(
        issue_key="USER-STATE-1",
        fields=expected_fields_list,
        expand=None,
        comment_limit=10,
        properties=None,
        update_history=False,
    )
    result_data = json.loads(response.content[0].text)
    assert "USER-STATE-1" in result_data
    assert result_data["USER-STATE-1"]["key"] == "USER-STATE-1"






























# --- v2 surface: jira_get -------------------------------------------------

from src.mcp_atlassian.servers.jira import _issue_card, _truncate_tagged, TRUNC_HINT


class _StubIssue:
    """Minimal stand-in for a JiraIssue model."""

    def __init__(self, data):
        self._data = data

    def to_simplified_dict(self):
        return dict(self._data)


class _StubJira:
    class config:
        url = "https://test.example.com"


def test_truncate_tagged_short_text_untouched():
    assert _truncate_tagged("hello world", 500) == "hello world"


def test_truncate_tagged_long_text_gets_steering_hint():
    text = "word " * 300  # 1500 chars
    out = _truncate_tagged(text, 500)
    assert len(out) < 600
    assert out.endswith(TRUNC_HINT)


def test_issue_card_summary_truncates_description_and_comments():
    issue = _StubIssue(
        {
            "key": "DS-1",
            "summary": "Big ticket",
            "description": "lorem " * 500,  # 3000 chars
            "status": {"name": "In Progress"},
            "priority": {"name": "P2"},
            "assignee": {"display_name": "Jack"},
            "updated": "2026-06-09T10:00:00.000+0000",
            "comments": [
                {
                    "author": {"display_name": f"U{i}"},
                    "created": "2026-06-09T10:00:00.000+0000",
                    "body": "blah " * 200,
                }
                for i in range(5)
            ],
        }
    )
    card = _issue_card(_StubJira(), issue, response_format="summary")
    assert card["key"] == "DS-1"
    assert card["description"].endswith(TRUNC_HINT)
    assert len(card["description"]) < 600
    assert card["comments_total"] == 5
    assert len(card["latest_comments"]) == 2
    assert card["latest_comments"][0]["body"].endswith(TRUNC_HINT)
    # comment timestamps must be relative, consistent with the card's 'updated'
    created = card["latest_comments"][0]["created"]
    assert created == "just now" or created.endswith("ago")
    assert card["url"] == "https://test.example.com/browse/DS-1"
    # the whole card must be small — this is the D3 budget
    assert len(json.dumps(card)) < 1500


def test_issue_card_full_returns_everything():
    issue = _StubIssue({"key": "DS-1", "summary": "s", "description": "d" * 2000})
    card = _issue_card(_StubJira(), issue, response_format="full")
    assert card["description"] == "d" * 2000


@pytest.mark.anyio
async def test_jira_get_single_key(jira_client, mock_jira_fetcher):
    response = await jira_client.call_tool("jira_get", {"keys": "TEST-123"})
    content = json.loads(response.content[0].text)
    assert "TEST-123" in content
    assert content["TEST-123"]["key"] == "TEST-123"
    assert content["TEST-123"]["summary"] == "Test Issue Summary"


@pytest.mark.anyio
async def test_jira_get_rejects_bad_include(jira_client):
    with pytest.raises(Exception, match="include"):
        await jira_client.call_tool(
            "jira_get", {"keys": "TEST-123", "include": "bogus"}
        )


def test_issue_card_extras_from_raw_carries_changelogs():
    issue = _StubIssue(
        {
            "key": "DS-1",
            "summary": "s",
            "changelogs": [
                {
                    "created": "c",
                    "items": [
                        {"field": "status", "from": "To Do", "to": "In Progress"}
                    ],
                }
            ],
        }
    )
    card = _issue_card(
        _StubJira(), issue, response_format="summary", extras_from_raw=("changelogs",)
    )
    assert card["changelogs"] == [
        {
            "created": "c",
            "items": [{"field": "status", "from": "To Do", "to": "In Progress"}],
        }
    ]
    # without the opt-in, summary mode must not carry changelogs
    card_plain = _issue_card(_StubJira(), issue, response_format="summary")
    assert "changelogs" not in card_plain


@pytest.mark.anyio
async def test_jira_get_include_changelog_summary_mode(jira_client, mock_jira_fetcher):
    """include='changelog' must surface changelogs even in summary mode."""

    def mock_get_issue_with_changelogs(
        issue_key,
        fields=None,
        expand=None,
        comment_limit=10,
        properties=None,
        update_history=True,
    ):
        mock_issue = MagicMock()
        data = {
            "key": issue_key,
            "summary": "Test Issue Summary",
            "status": {"name": "In Progress"},
        }
        if expand == "changelog":
            data["changelogs"] = [
                {
                    "created": "c",
                    "items": [
                        {"field": "status", "from": "To Do", "to": "In Progress"}
                    ],
                }
            ]
        mock_issue.to_simplified_dict.return_value = data
        return mock_issue

    mock_jira_fetcher.get_issue.side_effect = mock_get_issue_with_changelogs

    response = await jira_client.call_tool(
        "jira_get", {"keys": "TEST-123", "include": "changelog"}
    )
    content = json.loads(response.content[0].text)
    assert "changelogs" in content["TEST-123"]
    assert content["TEST-123"]["changelogs"][0]["items"][0]["field"] == "status"


@pytest.mark.anyio
async def test_jira_get_per_key_isolation(jira_client, mock_jira_fetcher):
    """One bad key never fails the batch — good keys still return cards."""
    original_side_effect = mock_jira_fetcher.get_issue.side_effect

    def mock_get_issue_one_bad(issue_key, **kwargs):
        if issue_key == "TEST-BAD":
            raise ValueError("Issue does not exist")
        return original_side_effect(issue_key, **kwargs)

    mock_jira_fetcher.get_issue.side_effect = mock_get_issue_one_bad

    response = await jira_client.call_tool(
        "jira_get", {"keys": "TEST-123,TEST-BAD"}
    )
    content = json.loads(response.content[0].text)
    assert content["TEST-123"]["key"] == "TEST-123"
    assert content["TEST-123"]["summary"] == "Test Issue Summary"
    assert "error" in content["TEST-BAD"]
    assert "does not exist" in content["TEST-BAD"]["error"]


# --- v2 surface: jira_find ------------------------------------------------

from src.mcp_atlassian.servers.jira import _looks_like_jql


@pytest.mark.parametrize(
    "query,expected",
    [
        ("project = DS AND status = 'In Progress'", True),
        ("assignee = currentUser() ORDER BY updated DESC", True),
        ("key in (DS-1, DS-2)", True),
        ("text ~ 'payment'", True),
        ("authentication failures in the checkout flow", False),
        ("slow database queries", False),
        ("payment and refund failures", False),
        ("login or signup errors", False),
        ("labels = frontend AND project = DS", True),
    ],
)
def test_looks_like_jql(query, expected):
    assert _looks_like_jql(query) is expected


@pytest.mark.anyio
async def test_jira_find_jql_path(jira_client, mock_jira_fetcher):
    response = await jira_client.call_tool(
        "jira_find", {"query": "project = TEST ORDER BY updated DESC"}
    )
    content = json.loads(response.content[0].text)
    assert content["mode"] == "jql"
    assert "issues" in content
    mock_jira_fetcher.search_issues.assert_called()


@pytest.mark.anyio
async def test_jira_find_semantic_path(jira_client, mock_jira_fetcher):
    fake = {"query": "auth bugs", "total_matches": 1, "returned": 1, "results": []}
    # NOTE: no `src.` prefix — find() lazy-imports `mcp_atlassian.servers.vector_tools`,
    # which is a different module object than the src-prefixed test import.
    with patch(
        "mcp_atlassian.servers.vector_tools.semantic_search_impl",
        AsyncMock(return_value=fake),
    ):
        response = await jira_client.call_tool(
            "jira_find", {"query": "auth bugs in checkout"}
        )
    content = json.loads(response.content[0].text)
    assert content["mode"] == "semantic"
    assert content["total_matches"] == 1


@pytest.mark.anyio
async def test_jira_find_similar_to_path(jira_client, mock_jira_fetcher):
    fake = {"total_matches": 2, "returned": 2, "results": []}
    # NOTE: no `src.` prefix — see test_jira_find_semantic_path.
    mock_impl = AsyncMock(return_value=fake)
    with patch(
        "mcp_atlassian.servers.vector_tools.semantic_search_impl", mock_impl
    ):
        response = await jira_client.call_tool(
            "jira_find", {"similar_to": "TEST-123"}
        )
    content = json.loads(response.content[0].text)
    assert content["mode"] == "similar"
    assert content["similar_to"] == "TEST-123"
    assert content["total_matches"] == 2
    mock_impl.assert_awaited_once()
    assert mock_impl.call_args.kwargs["exclude_key"] == "TEST-123"
    assert mock_jira_fetcher.get_issue.call_args.kwargs["comment_limit"] == 0


@pytest.mark.anyio
async def test_jira_find_rejects_bogus_mode(jira_client):
    with pytest.raises(Exception, match="mode"):
        await jira_client.call_tool(
            "jira_find", {"query": "project = TEST", "mode": "bogus"}
        )


@pytest.mark.anyio
async def test_jira_find_requires_query_or_similar_to(jira_client):
    with pytest.raises(Exception, match="query"):
        await jira_client.call_tool("jira_find", {})


# --- v2 surface: jira_transition -------------------------------------------


@pytest.mark.anyio
async def test_jira_transition_single_by_name(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Ready for QA", "to_status": "Ready for QA"},
    ]
    # A real to_simplified_dict() payload keeps this on the success path —
    # with the fixture's default (unspec'd MagicMock) the envelope degrades
    # to the last-resort fallback, which drops next_transitions.
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = {
        "key": "TEST-123",
        "status": {"name": "Ready for QA"},
    }
    mock_jira_fetcher.transition_issue.return_value = mock_issue
    response = await jira_client.call_tool(
        "jira_transition", {"keys": "TEST-123", "to_status": "ready for qa"}
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-123"
    assert "next_transitions" in content
    mock_jira_fetcher.transition_issue.assert_called_once()
    _, kwargs = mock_jira_fetcher.transition_issue.call_args
    assert kwargs["transition_id"] == "41"


@pytest.mark.anyio
async def test_jira_transition_batch(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"},
    ]
    response = await jira_client.call_tool(
        "jira_transition", {"keys": "TEST-1,TEST-2,TEST-3", "to_status": "Done"}
    )
    content = json.loads(response.content[0].text)
    assert content["summary"]["total"] == 3
    assert content["summary"]["ok"] == 3
    assert mock_jira_fetcher.transition_issue.call_count == 3


@pytest.mark.anyio
async def test_jira_transition_invalid_name_lists_options(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"},
    ]
    with pytest.raises(Exception, match="Done"):
        await jira_client.call_tool(
            "jira_transition", {"keys": "TEST-123", "to_status": "Nonexistent"}
        )


def test_operation_response_never_fails_on_unserializable_issue():
    """B2 guarantee: a completed write always gets a success envelope,
    even when shaping AND the shaped key are garbage."""
    from src.mcp_atlassian.servers.jira import _operation_response

    class _Unserializable:
        def __repr__(self):
            return "<unserializable>"

    class _WeirdIssue:
        key = _Unserializable()

        def to_simplified_dict(self):
            # shaping path: returns a dict whose key value cannot be JSON-dumped
            return {"key": _Unserializable(), "summary": "x"}

    class _StubJiraCfg:
        class config:
            url = "https://test.example.com"

    out = _operation_response(
        _StubJiraCfg(),
        message="Issue transitioned successfully",
        issue=_WeirdIssue(),
        issue_key="DS-1",
        return_mode="summary",
    )
    # Tools now return structured dicts (FastMCP serializes to structuredContent).
    parsed = out
    assert isinstance(parsed, dict)
    assert parsed["message"] == "Issue transitioned successfully"
    assert parsed["key"] == "DS-1"  # explicit issue_key wins over garbage


def test_operation_response_degrades_when_shaping_raises_and_key_is_garbage():
    """The shaping-exception branch must not adopt a non-string issue.key."""
    from src.mcp_atlassian.servers.jira import _operation_response

    class _ExplodingIssue:
        key = MagicMock()  # garbage, must NOT be adopted

        def to_simplified_dict(self):
            raise RuntimeError("boom")

    class _StubJiraCfg:
        class config:
            url = "https://test.example.com"

    out = _operation_response(
        _StubJiraCfg(),
        message="Issue created successfully",
        issue=_ExplodingIssue(),
        issue_key=None,  # the create_issue call-site shape
        return_mode="summary",
    )
    # Tools now return structured dicts (FastMCP serializes to structuredContent).
    parsed = out
    assert isinstance(parsed, dict)
    assert parsed["message"] == "Issue created successfully"
    assert "response_shaping_error" in parsed
    assert "key" not in parsed or parsed["key"] is None or isinstance(parsed["key"], str)


@pytest.mark.anyio
async def test_jira_transition_rejects_bogus_return_mode(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"},
    ]
    with pytest.raises(Exception, match="return_mode"):
        await jira_client.call_tool(
            "jira_transition",
            {"keys": "TEST-123", "to_status": "Done", "return_mode": "bogus"},
        )


# --- v2 surface: jira_comment ----------------------------------------------


@pytest.mark.anyio
async def test_jira_comment_add_returns_preview(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.add_comment.return_value = {
        "id": "10001",
        "body": "stored body text",
        "created": "2026-06-10T10:00:00.000+0000",
        "author": "Jack",
    }
    response = await jira_client.call_tool(
        "jira_comment", {"issue_key": "TEST-123", "body": "stored body text"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    assert content["action"] == "added"
    assert content["body_preview"] == "stored body text"
    mock_jira_fetcher.add_comment.assert_called_once()


@pytest.mark.anyio
async def test_jira_comment_edit_path(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.edit_comment.return_value = {
        "id": "10001",
        "body": "edited body",
        "updated": "2026-06-10T10:00:00.000+0000",
    }
    response = await jira_client.call_tool(
        "jira_comment",
        {"issue_key": "TEST-123", "body": "edited body", "comment_id": "10001"},
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "edited"
    assert content["body_preview"] == "edited body"
    assert content["updated"] == "2026-06-10T10:00:00.000+0000"
    assert "created" not in content
    mock_jira_fetcher.edit_comment.assert_called_once_with(
        "TEST-123", "10001", "edited body", None
    )


@pytest.mark.anyio
async def test_jira_comment_preview_is_stored_not_input(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.add_comment.return_value = {
        "id": "1",
        "body": "*bold*",  # converted Wiki, not the input
        "created": "c",
    }
    response = await jira_client.call_tool(
        "jira_comment", {"issue_key": "TEST-123", "body": "**bold**"}
    )
    content = json.loads(response.content[0].text)
    assert content["body_preview"] == "*bold*"  # stored post-conversion, not input


@pytest.mark.anyio
async def test_jira_comment_warns_on_markdown(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.add_comment.return_value = {"id": "1", "body": "x", "created": "c"}
    response = await jira_client.call_tool(
        "jira_comment", {"issue_key": "TEST-123", "body": "**bold** text"}
    )
    content = json.loads(response.content[0].text)
    assert any("Markdown" in w for w in content.get("warnings", []))


@pytest.mark.anyio
async def test_jira_comment_rejects_bogus_format(jira_client, mock_jira_fetcher):
    with pytest.raises(Exception, match="format"):
        await jira_client.call_tool(
            "jira_comment",
            {"issue_key": "TEST-123", "body": "some text", "format": "bogus"},
        )


# --- v2 surface: jira_link --------------------------------------------------


@pytest.mark.anyio
async def test_jira_link_epic(jira_client, mock_jira_fetcher):
    response = await jira_client.call_tool(
        "jira_link",
        {"issue_key": "TEST-123", "to": "TEST-100", "link_type": "epic"},
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-123"
    mock_jira_fetcher.link_issue_to_epic.assert_called_once_with("TEST-123", "TEST-100")


@pytest.mark.anyio
async def test_jira_link_web(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.create_remote_issue_link.return_value = {"success": True}
    response = await jira_client.call_tool(
        "jira_link",
        {
            "issue_key": "TEST-123",
            "to": "https://github.com/org/repo/pull/1",
            "link_type": "web",
            "title": "PR #1",
        },
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.create_remote_issue_link.assert_called_once_with(
        "TEST-123",
        {"object": {"url": "https://github.com/org/repo/pull/1", "title": "PR #1"}},
    )


@pytest.mark.anyio
async def test_jira_link_issue_link_success(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_issue_link_types.return_value = [
        {"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
    ]
    mock_jira_fetcher.create_issue_link.return_value = {"success": True}
    response = await jira_client.call_tool(
        "jira_link",
        {"issue_key": "TEST-1", "to": "TEST-2", "link_type": "blocks"},  # case-insensitive NAME match ("blocks" == "Blocks".casefold())
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    assert content["key"] == "TEST-1"
    mock_jira_fetcher.create_issue_link.assert_called_once_with(
        {"type": {"name": "Blocks"}, "inwardIssue": {"key": "TEST-1"}, "outwardIssue": {"key": "TEST-2"}}
    )


@pytest.mark.anyio
async def test_jira_link_issue_link_matches_by_phrase(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_issue_link_types.return_value = [
        {"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
    ]
    mock_jira_fetcher.create_issue_link.return_value = {"success": True}
    response = await jira_client.call_tool(
        "jira_link",
        {"issue_key": "TEST-1", "to": "TEST-2", "link_type": "is blocked by"},  # phrase, not a name
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.create_issue_link.assert_called_once_with(
        {"type": {"name": "Blocks"}, "inwardIssue": {"key": "TEST-1"}, "outwardIssue": {"key": "TEST-2"}}
    )


@pytest.mark.anyio
async def test_jira_link_issue_link_ambiguous_phrase_raises(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_issue_link_types.return_value = [
        {"id": "1", "name": "Relates", "inward": "relates to", "outward": "relates to"},
        {"id": "2", "name": "Mentions", "inward": "relates to", "outward": "relates to"},
    ]
    with pytest.raises(Exception, match="[Aa]mbiguous"):
        await jira_client.call_tool(
            "jira_link",
            {"issue_key": "TEST-1", "to": "TEST-2", "link_type": "relates to"},
        )


@pytest.mark.anyio
async def test_jira_link_issue_link_unknown_type_lists_valid(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_issue_link_types.return_value = [
        {"id": "1", "name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        {"id": "2", "name": "Relates", "inward": "relates to", "outward": "relates to"},
    ]
    with pytest.raises(Exception, match="Blocks"):
        await jira_client.call_tool(
            "jira_link",
            {"issue_key": "TEST-123", "to": "TEST-124", "link_type": "Bogus"},
        )


@pytest.mark.anyio
async def test_jira_link_remove(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.remove_issue_link.return_value = {"success": True}
    response = await jira_client.call_tool(
        "jira_link", {"issue_key": "TEST-123", "remove": True, "link_id": "10500"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.remove_issue_link.assert_called_once_with("10500")


# --- v2 surface: jira_attach ------------------------------------------------


@pytest.mark.anyio
async def test_jira_attach_single(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.upload_attachment.return_value = {
        "success": True, "filename": "x.png", "size": 123, "id": "10001",
    }
    response = await jira_client.call_tool(
        "jira_attach", {"issue_key": "TEST-1", "file_path": "/tmp/x.png"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    assert content["filename"] == "x.png"
    mock_jira_fetcher.upload_attachment.assert_called_once_with(
        issue_key="TEST-1", file_path="/tmp/x.png"
    )


@pytest.mark.anyio
async def test_jira_attach_accepts_key_alias(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.upload_attachment.return_value = {"success": True, "filename": "a"}
    response = await jira_client.call_tool(
        "jira_attach", {"key": "TEST-2", "file_path": "/tmp/a"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.upload_attachment.assert_called_once_with(
        issue_key="TEST-2", file_path="/tmp/a"
    )


@pytest.mark.anyio
async def test_jira_attach_multiple_files(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.upload_attachment.side_effect = [
        {"success": True, "filename": "a"},
        {"success": False, "error": "File not found: /tmp/b"},
    ]
    response = await jira_client.call_tool(
        "jira_attach", {"issue_key": "TEST-3", "file_path": "/tmp/a,/tmp/b"}
    )
    content = json.loads(response.content[0].text)
    assert content["summary"] == {"ok": 1, "fail": 1, "total": 2}
    assert mock_jira_fetcher.upload_attachment.call_count == 2


@pytest.mark.anyio
async def test_jira_attach_requires_file_path(jira_client):
    with pytest.raises(Exception, match="file_path"):
        await jira_client.call_tool("jira_attach", {"issue_key": "TEST-1"})


# --- v2 surface: jira_worklog -----------------------------------------------


@pytest.mark.anyio
async def test_jira_worklog_read(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_worklogs.return_value = [
        {"id": "1", "timeSpent": "1h", "comment": "did stuff"}
    ]
    response = await jira_client.call_tool("jira_worklog", {"issue_key": "TEST-123"})
    content = json.loads(response.content[0].text)
    assert content["worklogs"][0]["timeSpent"] == "1h"
    mock_jira_fetcher.get_worklogs.assert_called_once_with("TEST-123")


@pytest.mark.anyio
async def test_jira_worklog_add(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.add_worklog.return_value = {"id": "2", "timeSpent": "30m"}
    response = await jira_client.call_tool(
        "jira_worklog", {"issue_key": "TEST-123", "time_spent": "30m"}
    )
    content = json.loads(response.content[0].text)
    assert content["worklog"]["timeSpent"] == "30m"
    mock_jira_fetcher.add_worklog.assert_called_once()


# --- v2 surface: admin tools -------------------------------------------------


@pytest.mark.anyio
async def test_jira_agile_boards(jira_client, mock_jira_fetcher):
    board = MagicMock()
    board.to_simplified_dict.return_value = {
        "id": 1, "name": "DS board", "type": "scrum", "project_key": "DS",
    }
    mock_jira_fetcher.get_all_agile_boards_model.return_value = [board]
    response = await jira_client.call_tool("jira_agile", {"action": "boards"})
    content = json.loads(response.content[0].text)
    assert content["boards"][0]["name"] == "DS board"


@pytest.mark.anyio
async def test_jira_agile_sprints_requires_board_id(jira_client):
    with pytest.raises(Exception, match="board_id"):
        await jira_client.call_tool("jira_agile", {"action": "sprints"})


@pytest.mark.anyio
async def test_jira_agile_rejects_unknown_action(jira_client):
    with pytest.raises(Exception, match="boards"):
        await jira_client.call_tool("jira_agile", {"action": "bogus"})


@pytest.mark.anyio
async def test_jira_versions_list(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_project_versions.return_value = [{"name": "v1.0"}]
    response = await jira_client.call_tool("jira_versions", {"project_key": "TEST"})
    content = json.loads(response.content[0].text)
    assert content["versions"][0]["name"] == "v1.0"


@pytest.mark.anyio
async def test_jira_versions_create(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.create_project_version.return_value = {"name": "v2.0"}
    response = await jira_client.call_tool(
        "jira_versions", {"project_key": "TEST", "name": "v2.0"}
    )
    content = json.loads(response.content[0].text)
    assert content["version"]["name"] == "v2.0"
    mock_jira_fetcher.create_project_version.assert_called_once()


@pytest.mark.anyio
async def test_jira_projects_user_lookup(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_user_profile_by_identifier.return_value.to_simplified_dict.return_value = {"account_id": "x", "display_name": "Test User"}
    response = await jira_client.call_tool(
        "jira_projects", {"user": "user@example.com"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.get_user_profile_by_identifier.assert_called_once_with(
        "user@example.com"
    )


@pytest.mark.anyio
async def test_jira_projects_field_search(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.search_fields.return_value = [{"id": "duedate", "name": "Due date"}]
    response = await jira_client.call_tool(
        "jira_projects", {"field_keyword": "due"}
    )
    content = json.loads(response.content[0].text)
    assert content["fields"][0]["id"] == "duedate"


@pytest.mark.anyio
async def test_jira_projects_issue_types(jira_client, mock_jira_fetcher):
    """issue_types mode returns the creatable types for a project, compacted."""
    mock_jira_fetcher.get_project_issue_types.return_value = [
        {"id": "10044", "name": "Initiative", "subtask": False, "description": "Big bet"},
        {"id": "10001", "name": "Story", "subtask": False, "description": ""},
    ]
    response = await jira_client.call_tool("jira_projects", {"issue_types": "AI"})
    content = json.loads(response.content[0].text)
    mock_jira_fetcher.get_project_issue_types.assert_called_once_with("AI")
    assert content["project"] == "AI"
    names = [t["name"] for t in content["issue_types"]]
    assert names == ["Initiative", "Story"]
    assert content["issue_types"][0]["id"] == "10044"
    assert content["issue_types"][0]["subtask"] is False


@pytest.mark.anyio
async def test_jira_projects_list(jira_client, mock_jira_fetcher):
    """Default (no-arg) path lists projects via get_all_projects."""
    response = await jira_client.call_tool("jira_projects", {})
    content = json.loads(response.content[0].text)
    assert "projects" in content
    assert isinstance(content["projects"], list)
    assert any(p.get("key") == "TEST" for p in content["projects"])
    mock_jira_fetcher.get_all_projects.assert_called_once_with(include_archived=False)


# --- v2 surface: read-only write-guard on mixed admin tools ------------------


class _ROContext:
    def __init__(self):
        self.request_context = MagicMock()
        self.request_context.lifespan_context = {
            "app_lifespan_context": MagicMock(read_only=True)
        }


@pytest.mark.anyio
async def test_jira_agile_create_sprint_blocked_in_read_only(mock_jira_fetcher):
    from src.mcp_atlassian.servers.jira import agile
    with patch("src.mcp_atlassian.servers.jira.get_jira_fetcher", AsyncMock(return_value=mock_jira_fetcher)):
        with pytest.raises(ValueError, match="read-only"):
            await agile.fn(_ROContext(), action="create_sprint", board_id="1", sprint_name="S", start_date="2026-01-01", end_date="2026-01-14")
    mock_jira_fetcher.create_sprint.assert_not_called()


@pytest.mark.anyio
async def test_jira_agile_update_sprint_blocked_in_read_only(mock_jira_fetcher):
    from src.mcp_atlassian.servers.jira import agile
    with patch("src.mcp_atlassian.servers.jira.get_jira_fetcher", AsyncMock(return_value=mock_jira_fetcher)):
        with pytest.raises(ValueError, match="read-only"):
            await agile.fn(_ROContext(), action="update_sprint", sprint_id="42", state="closed")
    mock_jira_fetcher.update_sprint.assert_not_called()


@pytest.mark.anyio
async def test_jira_agile_boards_allowed_in_read_only(mock_jira_fetcher):
    from src.mcp_atlassian.servers.jira import agile
    board = MagicMock(); board.to_simplified_dict.return_value = {"id":1,"name":"B","type":"scrum","project_key":"DS"}
    mock_jira_fetcher.get_all_agile_boards_model.return_value = [board]
    with patch("src.mcp_atlassian.servers.jira.get_jira_fetcher", AsyncMock(return_value=mock_jira_fetcher)):
        out = await agile.fn(_ROContext(), action="boards")  # read must NOT raise in read-only
    assert "boards" in out


@pytest.mark.anyio
async def test_jira_versions_create_blocked_in_read_only(mock_jira_fetcher):
    from src.mcp_atlassian.servers.jira import versions
    with patch("src.mcp_atlassian.servers.jira.get_jira_fetcher", AsyncMock(return_value=mock_jira_fetcher)):
        with pytest.raises(ValueError, match="read-only"):
            await versions.fn(_ROContext(), project_key="TEST", name="v9.9")
    mock_jira_fetcher.create_project_version.assert_not_called()


@pytest.mark.anyio
async def test_jira_versions_list_allowed_in_read_only(mock_jira_fetcher):
    from src.mcp_atlassian.servers.jira import versions
    mock_jira_fetcher.get_project_versions.return_value = [{"name": "v1.0"}]
    with patch("src.mcp_atlassian.servers.jira.get_jira_fetcher", AsyncMock(return_value=mock_jira_fetcher)):
        out = await versions.fn(_ROContext(), project_key="TEST")  # read must NOT raise
    assert out["versions"][0]["name"] == "v1.0"


# --- v2 surface: jira_handoff ------------------------------------------------


@pytest.mark.anyio
async def test_jira_handoff_snapshot(jira_client, mock_jira_fetcher):
    response = await jira_client.call_tool("jira_handoff", {})
    content = json.loads(response.content[0].text)
    assert "open_issues" in content
    assert "recently_updated" in content
    # two JQL queries: open + recent
    assert mock_jira_fetcher.search_issues.call_count >= 2
    first_jql = mock_jira_fetcher.search_issues.call_args_list[0].kwargs["jql"]
    assert "currentUser()" in first_jql
    # budget: snapshot stays compact
    assert len(response.content[0].text) < 8000


@pytest.mark.anyio
async def test_jira_handoff_project_scope(jira_client, mock_jira_fetcher):
    await jira_client.call_tool("jira_handoff", {"projects": "DS,AI"})
    first_jql = mock_jira_fetcher.search_issues.call_args_list[0].kwargs["jql"]
    assert 'project in ("DS", "AI")' in first_jql


@pytest.mark.anyio
async def test_jira_handoff_budget_is_real(jira_client, mock_jira_fetcher):
    # Worst case: a full section of long-summary, long-status cards at the DEFAULT limit.
    def big_result(jql, **kwargs):
        n = kwargs.get("limit", 10)
        issues = []
        for i in range(n):
            m = MagicMock()
            m.to_simplified_dict.return_value = {
                "key": f"DS-{10000+i}",
                "summary": "X" * 200,  # longer than the cap; tool must truncate
                "status": {"name": "Waiting for Customer Response"},
                "priority": {"name": "Highest"},
                "updated": "2026-06-10T10:00:00.000+0000",
            }
            issues.append(m)
        r = MagicMock(); r.issues = issues
        return r
    mock_jira_fetcher.search_issues.side_effect = big_result
    response = await jira_client.call_tool("jira_handoff", {})
    text = response.content[0].text
    assert len(text) < 8000  # default snapshot stays under budget even worst-case
    # prove truncation actually happened (summary capped)
    content = json.loads(text)
    assert all(len(c["summary"]) <= 80 for c in content["open_issues"])


@pytest.mark.anyio
async def test_jira_handoff_rejects_bad_project_key(jira_client, mock_jira_fetcher):
    with pytest.raises(Exception, match="Invalid project key"):
        await jira_client.call_tool("jira_handoff", {"projects": 'DS") OR x'})


# === v2 token-budget evals (miner friction patterns) ===
# These pin the consolidation's measured wins. Each maps to a friction
# pattern from the 1,624-transcript corpus analysis.


@pytest.mark.anyio
async def test_eval_triage_sweep_is_one_call(jira_client, mock_jira_fetcher):
    """C1/C4: inspect 8 issues in ONE jira_get call, not 8 search→get round-trips."""
    response = await jira_client.call_tool(
        "jira_get", {"keys": ",".join(f"TEST-{i}" for i in range(1, 9))}
    )
    content = json.loads(response.content[0].text)
    assert len(content) == 8  # 8 issues, one MCP call
    assert mock_jira_fetcher.get_issue.call_count == 8  # server-side fan-out, not agent-side


@pytest.mark.anyio
async def test_eval_transition_five_by_name_zero_lookups(jira_client, mock_jira_fetcher):
    """C3: transition 5 issues by status NAME — no get_transitions tool exists at all."""
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"}
    ]
    await jira_client.call_tool(
        "jira_transition",
        {"keys": "T-1,T-2,T-3,T-4,T-5", "to_status": "Done"},
    )
    assert mock_jira_fetcher.transition_issue.call_count == 5


def test_eval_no_transition_lookup_tool_exists():
    """C3: the 103 get_transitions round-trips are structurally impossible — no such tool."""
    import asyncio

    from src.mcp_atlassian.servers.jira import jira_mcp

    tools = asyncio.run(jira_mcp.get_tools())
    tool_names = set(tools.keys())
    assert "get_transitions" not in tool_names
    assert "transition" in tool_names  # the merged replacement


@pytest.mark.anyio
async def test_eval_comment_one_call_with_preview(jira_client, mock_jira_fetcher):
    """C2: post a comment and verify rendering from body_preview — no follow-up get."""
    mock_jira_fetcher.add_comment.return_value = {
        "id": "1",
        "body": "stored",
        "created": "2026-06-10T10:00:00.000+0000",
    }
    response = await jira_client.call_tool(
        "jira_comment", {"issue_key": "T-1", "body": "stored"}
    )
    content = json.loads(response.content[0].text)
    assert content["body_preview"] == "stored"  # rendering verifiable in-band
    assert mock_jira_fetcher.add_comment.call_count == 1
    assert mock_jira_fetcher.get_issue.call_count == 0  # NO verification re-fetch


# === Part 2 — server-layer tests for jira_update / jira_assign / jira_delete ===


@pytest.mark.anyio
async def test_jira_update_calls_update_issue(jira_client, mock_jira_fetcher):
    """jira_update routes through the fetcher's update_issue method."""
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = {
        "key": "TEST-999",
        "summary": "Updated summary",
        "status": {"name": "In Progress"},
    }
    mock_jira_fetcher.update_issue.return_value = mock_issue

    response = await jira_client.call_tool(
        "jira_update",
        {
            "issue_key": "TEST-999",
            "fields": {"summary": "Updated summary"},
        },
    )
    content = json.loads(response.content[0].text)
    assert content["message"] == "Issue updated successfully"
    assert content["key"] == "TEST-999"
    mock_jira_fetcher.update_issue.assert_called_once_with(
        issue_key="TEST-999", summary="Updated summary"
    )


@pytest.mark.anyio
async def test_jira_assign_calls_assign_issue(jira_client, mock_jira_fetcher):
    """jira_assign routes through the fetcher's assign_issue method."""
    mock_jira_fetcher.assign_issue.return_value = ("Jack Felke", "Stan Ulmasov")

    response = await jira_client.call_tool(
        "jira_assign",
        {"issue_key": "TEST-100", "assignee": "stan@example.com"},
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    assert content["key"] == "TEST-100"
    assert content["prior_assignee"] == "Jack Felke"
    assert content["new_assignee"] == "Stan Ulmasov"
    mock_jira_fetcher.assign_issue.assert_called_once_with("TEST-100", "stan@example.com")


@pytest.mark.anyio
async def test_jira_delete_calls_delete_issue(jira_client, mock_jira_fetcher):
    """jira_delete routes through the fetcher's delete_issue method."""
    mock_jira_fetcher.delete_issue.return_value = True

    response = await jira_client.call_tool(
        "jira_delete", {"issue_key": "TEST-777"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    assert "deleted" in content["message"].lower()
    mock_jira_fetcher.delete_issue.assert_called_once_with("TEST-777")


# === Part 3 — jira_projects filter/error-path coverage ===


@pytest.mark.anyio
async def test_jira_projects_include_archived_passes_through(
    jira_client, mock_jira_fetcher
):
    """include_archived=True must reach get_all_projects with the flag set."""
    response = await jira_client.call_tool(
        "jira_projects", {"include_archived": True}
    )
    content = json.loads(response.content[0].text)
    assert "projects" in content
    project_keys = [p["key"] for p in content["projects"]]
    assert "ARCHIVED" in project_keys
    mock_jira_fetcher.get_all_projects.assert_called_with(include_archived=True)


@pytest.mark.anyio
async def test_jira_projects_user_lookup_error_returns_failure(
    jira_client, mock_jira_fetcher
):
    """A user-lookup exception must return success=False, not raise."""
    response = await jira_client.call_tool(
        "jira_projects", {"user": "nonexistent@example.com"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is False
    assert "error" in content
    assert content["user_identifier"] == "nonexistent@example.com"


# === Part 4 — key/verbosity parameter aliases (no keys/issue_key friction) ===
#
# The single-issue write tools accept the issue identifier under any of
# `issue_key` (canonical), `key`, or `keys`. The verbosity param is accepted
# under both `return_mode` (write tools) and `response_format` (jira_get), with
# each tool keeping its own canonical spelling.


@pytest.mark.anyio
async def test_jira_update_accepts_keys_alias(jira_client, mock_jira_fetcher):
    """jira_update with `keys=` works the same as `issue_key=`."""
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = {"key": "TEST-1", "summary": "x"}
    mock_jira_fetcher.update_issue.return_value = mock_issue

    response = await jira_client.call_tool(
        "jira_update", {"keys": "TEST-1", "fields": {"summary": "x"}}
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-1"
    mock_jira_fetcher.update_issue.assert_called_once_with(
        issue_key="TEST-1", summary="x"
    )


@pytest.mark.anyio
async def test_jira_update_accepts_key_alias(jira_client, mock_jira_fetcher):
    """jira_update with `key=` works the same as `issue_key=`."""
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = {"key": "TEST-2", "summary": "y"}
    mock_jira_fetcher.update_issue.return_value = mock_issue

    response = await jira_client.call_tool(
        "jira_update", {"key": "TEST-2", "fields": {"summary": "y"}}
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-2"
    mock_jira_fetcher.update_issue.assert_called_once_with(
        issue_key="TEST-2", summary="y"
    )


@pytest.mark.anyio
async def test_jira_update_response_format_aliases_return_mode(
    jira_client, mock_jira_fetcher
):
    """response_format='full' behaves like return_mode='full' (full payload)."""
    full_payload = {"key": "TEST-3", "summary": "s", "description": "big body"}
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = full_payload
    mock_jira_fetcher.update_issue.return_value = mock_issue

    via_alias = await jira_client.call_tool(
        "jira_update",
        {"issue_key": "TEST-3", "fields": {"summary": "s"}, "response_format": "full"},
    )
    via_canonical = await jira_client.call_tool(
        "jira_update",
        {"issue_key": "TEST-3", "fields": {"summary": "s"}, "return_mode": "full"},
    )
    alias_content = json.loads(via_alias.content[0].text)
    canonical_content = json.loads(via_canonical.content[0].text)
    # response_format='full' must produce the identical payload as
    # return_mode='full' — and 'full' surfaces the description (dropped in
    # the default 'summary' shaping).
    assert alias_content == canonical_content
    assert alias_content["issue"]["description"] == "big body"


@pytest.mark.anyio
async def test_jira_update_rejects_missing_key(jira_client):
    """No issue identifier under any spelling must fail loudly."""
    with pytest.raises(Exception, match="issue_key"):
        await jira_client.call_tool("jira_update", {"fields": {"summary": "s"}})


@pytest.mark.anyio
async def test_jira_comment_accepts_key_alias(jira_client, mock_jira_fetcher):
    """jira_comment with `key=` works the same as `issue_key=`."""
    mock_jira_fetcher.add_comment.return_value = {
        "id": "1",
        "body": "hello",
        "created": "c",
    }
    response = await jira_client.call_tool(
        "jira_comment", {"key": "TEST-9", "body": "hello"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    # the resolved key flows into the comment URL
    assert "TEST-9" in content["url"]
    mock_jira_fetcher.add_comment.assert_called_once()
    assert mock_jira_fetcher.add_comment.call_args.args[0] == "TEST-9"


@pytest.mark.anyio
async def test_jira_assign_accepts_keys_alias(jira_client, mock_jira_fetcher):
    """jira_assign with `keys=` works the same as `issue_key=`."""
    mock_jira_fetcher.assign_issue.return_value = ("Old", "New")
    response = await jira_client.call_tool(
        "jira_assign", {"keys": "TEST-5", "assignee": "new@example.com"}
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-5"
    mock_jira_fetcher.assign_issue.assert_called_once_with("TEST-5", "new@example.com")


@pytest.mark.anyio
async def test_jira_delete_accepts_key_alias(jira_client, mock_jira_fetcher):
    """jira_delete with `key=` works the same as `issue_key=`."""
    mock_jira_fetcher.delete_issue.return_value = True
    response = await jira_client.call_tool("jira_delete", {"key": "TEST-6"})
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_jira_fetcher.delete_issue.assert_called_once_with("TEST-6")


@pytest.mark.anyio
async def test_jira_worklog_accepts_keys_alias(jira_client, mock_jira_fetcher):
    """jira_worklog read path with `keys=` works the same as `issue_key=`."""
    mock_jira_fetcher.get_worklogs.return_value = [{"id": "1", "timeSpent": "1h"}]
    response = await jira_client.call_tool("jira_worklog", {"keys": "TEST-7"})
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-7"
    mock_jira_fetcher.get_worklogs.assert_called_once_with("TEST-7")


@pytest.mark.anyio
async def test_jira_link_accepts_key_alias(jira_client, mock_jira_fetcher):
    """jira_link with `key=` works the same as `issue_key=`."""
    response = await jira_client.call_tool(
        "jira_link",
        {"key": "TEST-8", "to": "TEST-100", "link_type": "epic"},
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-8"
    mock_jira_fetcher.link_issue_to_epic.assert_called_once_with("TEST-8", "TEST-100")


@pytest.mark.anyio
async def test_jira_create_response_format_aliases_return_mode(
    jira_client, mock_jira_fetcher
):
    """jira_create accepts response_format as an alias for return_mode."""
    via_alias = await jira_client.call_tool(
        "jira_create",
        {
            "project_key": "TEST",
            "summary": "Aliased create",
            "issue_type": "Task",
            "response_format": "minimal",
            "force": True,
        },
    )
    via_canonical = await jira_client.call_tool(
        "jira_create",
        {
            "project_key": "TEST",
            "summary": "Aliased create",
            "issue_type": "Task",
            "return_mode": "minimal",
            "force": True,
        },
    )
    alias_content = json.loads(via_alias.content[0].text)
    canonical_content = json.loads(via_canonical.content[0].text)
    assert alias_content["key"]
    # response_format alias must produce the same shape as canonical return_mode
    assert alias_content == canonical_content


@pytest.mark.anyio
async def test_jira_get_accepts_return_mode_alias(jira_client, mock_jira_fetcher):
    """jira_get accepts return_mode as an alias for response_format."""
    response = await jira_client.call_tool(
        "jira_get", {"keys": "TEST-123", "return_mode": "full"}
    )
    content = json.loads(response.content[0].text)
    assert "TEST-123" in content
    assert content["TEST-123"]["key"] == "TEST-123"


@pytest.mark.anyio
async def test_jira_get_return_mode_minimal_maps_to_summary(
    jira_client, mock_jira_fetcher
):
    """'minimal' has no read analogue, so it folds to summary (no error)."""
    response = await jira_client.call_tool(
        "jira_get", {"keys": "TEST-123", "return_mode": "minimal"}
    )
    content = json.loads(response.content[0].text)
    assert content["TEST-123"]["key"] == "TEST-123"


@pytest.mark.anyio
async def test_jira_transition_response_format_aliases_return_mode(
    jira_client, mock_jira_fetcher
):
    """jira_transition accepts response_format as an alias for return_mode."""
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"},
    ]
    mock_issue = MagicMock()
    mock_issue.to_simplified_dict.return_value = {"key": "TEST-123", "summary": "s"}
    mock_jira_fetcher.transition_issue.return_value = mock_issue
    # Should not raise on the aliased verbosity param.
    response = await jira_client.call_tool(
        "jira_transition",
        {"keys": "TEST-123", "to_status": "Done", "response_format": "minimal"},
    )
    content = json.loads(response.content[0].text)
    assert content["key"] == "TEST-123"
