"""Unit tests for the Confluence FastMCP server (4-tool surface: find/get/write/comment)."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client import FastMCPTransport
from starlette.requests import Request

from src.mcp_atlassian.confluence import ConfluenceFetcher
from src.mcp_atlassian.confluence.config import ConfluenceConfig
from src.mcp_atlassian.models.confluence.page import ConfluencePage
from src.mcp_atlassian.servers.context import MainAppContext
from src.mcp_atlassian.servers.main import AtlassianMCP
from src.mcp_atlassian.utils.oauth import OAuthConfig

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_confluence_fetcher():
    """Create a mocked ConfluenceFetcher instance for testing."""
    mock_fetcher = MagicMock(spec=ConfluenceFetcher)

    # Mock page for various methods
    mock_page = MagicMock(spec=ConfluencePage)
    mock_page.to_simplified_dict.return_value = {
        "id": "123456",
        "title": "Test Page Mock Title",
        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/123456/Test+Page",
        "content": {
            "value": "This is a test page content in Markdown",
            "format": "markdown",
        },
    }
    mock_page.content = "This is a test page content in Markdown"

    # Set up mock responses for each method
    mock_fetcher.search.return_value = [mock_page]
    mock_fetcher.get_page_content.return_value = mock_page
    mock_fetcher.get_page_children.return_value = [mock_page]
    mock_fetcher.create_page.return_value = mock_page
    mock_fetcher.update_page.return_value = mock_page
    mock_fetcher.delete_page.return_value = True

    # Mock comment
    mock_comment = MagicMock()
    mock_comment.to_simplified_dict.return_value = {
        "id": "789",
        "author": "Test User",
        "created": "2023-08-01T12:00:00.000Z",
        "body": "This is a test comment",
    }
    mock_fetcher.get_page_comments.return_value = [mock_comment]

    # Mock label
    mock_label = MagicMock()
    mock_label.to_simplified_dict.return_value = {"id": "lbl1", "name": "test-label"}
    mock_fetcher.get_page_labels.return_value = [mock_label]
    mock_fetcher.add_page_label.return_value = [mock_label]

    # Mock add_comment method
    mock_add_comment_result = MagicMock()
    mock_add_comment_result.to_simplified_dict.return_value = {
        "id": "987",
        "author": "Test User",
        "created": "2023-08-01T13:00:00.000Z",
        "body": "This is a test comment added via API",
    }
    mock_fetcher.add_comment.return_value = mock_add_comment_result

    # Mock search_user method
    mock_user_search_result = MagicMock()
    mock_user_search_result.to_simplified_dict.return_value = {
        "entity_type": "user",
        "title": "First Last",
        "score": 0.0,
        "user": {
            "account_id": "a031248587011jasoidf9832jd8j1",
            "display_name": "First Last",
            "email": "first.last@foo.com",
            "profile_picture": "/wiki/aa-avatar/a031248587011jasoidf9832jd8j1",
            "is_active": True,
        },
        "url": "/people/a031248587011jasoidf9832jd8j1",
        "last_modified": "2025-06-02T13:35:59.680Z",
        "excerpt": "",
    }
    mock_fetcher.search_user.return_value = [mock_user_search_result]

    return mock_fetcher


@pytest.fixture
def mock_base_confluence_config():
    """Create a mock base ConfluenceConfig for MainAppContext using OAuth for multi-user scenario."""
    mock_oauth_config = OAuthConfig(
        client_id="server_client_id",
        client_secret="server_client_secret",
        redirect_uri="http://localhost",
        scope="read:confluence",
        cloud_id="mock_cloud_id",
    )
    return ConfluenceConfig(
        url="https://mock.atlassian.net/wiki",
        auth_type="oauth",
        oauth_config=mock_oauth_config,
    )


@pytest.fixture
def test_confluence_mcp(mock_confluence_fetcher, mock_base_confluence_config):
    """Create a test FastMCP instance with standard configuration."""

    # Import and register the 4 new tool functions
    from src.mcp_atlassian.servers.confluence import (
        comment,
        find,
        get,
        write,
    )

    @asynccontextmanager
    async def test_lifespan(app: FastMCP) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(
                full_confluence_config=mock_base_confluence_config, read_only=False
            )
        finally:
            pass

    test_mcp = AtlassianMCP(
        "TestConfluence",
        instructions="Test Confluence MCP Server",
        lifespan=test_lifespan,
    )

    # Create and configure the sub-MCP for Confluence tools
    confluence_sub_mcp = FastMCP(name="TestConfluenceSubMCP")
    confluence_sub_mcp.add_tool(find)
    confluence_sub_mcp.add_tool(get)
    confluence_sub_mcp.add_tool(write)
    confluence_sub_mcp.add_tool(comment)

    test_mcp.mount(confluence_sub_mcp, prefix="confluence")

    return test_mcp


@pytest.fixture
def mock_request():
    """Provides a mock Starlette Request object with a state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    return request


@pytest.fixture
async def client(test_confluence_mcp, mock_confluence_fetcher):
    """Create a FastMCP client with mocked Confluence fetcher and request state."""
    with (
        patch(
            "src.mcp_atlassian.servers.confluence.get_confluence_fetcher",
            AsyncMock(return_value=mock_confluence_fetcher),
        ),
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            MagicMock(spec=Request, state=MagicMock()),
        ),
    ):
        client_instance = Client(transport=FastMCPTransport(test_confluence_mcp))
        async with client_instance as connected_client:
            yield connected_client


@pytest.mark.anyio
async def test_confluence_find_pages(client, mock_confluence_fetcher):
    """Test find tool with simple text query (searches pages)."""
    response = await client.call_tool("confluence_find", {"query": "test docs"})
    content = json.loads(response.content[0].text)
    assert "results" in content
    mock_confluence_fetcher.search.assert_called_once()


@pytest.mark.anyio
async def test_confluence_find_users(client, mock_confluence_fetcher):
    """Test find tool with search_users=True."""
    response = await client.call_tool(
        "confluence_find", {"query": "Jane Doe", "search_users": True}
    )
    content = json.loads(response.content[0].text)
    assert "results" in content
    mock_confluence_fetcher.search_user.assert_called_once()


@pytest.mark.anyio
async def test_confluence_get_with_includes(client, mock_confluence_fetcher):
    """Test get tool with all include options."""
    response = await client.call_tool(
        "confluence_get", {"page_id": "123", "include": "children,comments,labels"}
    )
    content = json.loads(response.content[0].text)
    assert "metadata" in content
    assert "children" in content
    assert "comments" in content
    assert "labels" in content


@pytest.mark.anyio
async def test_confluence_get_bad_include_rejected(client):
    """Test get tool rejects invalid include values."""
    with pytest.raises(Exception, match="include"):
        await client.call_tool("confluence_get", {"page_id": "123", "include": "bogus"})


@pytest.mark.anyio
async def test_confluence_write_create(client, mock_confluence_fetcher):
    """Test write tool creates a new page when no page_id is provided."""
    response = await client.call_tool(
        "confluence_write", {"space_key": "DEV", "title": "New", "content": "# hi"}
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "created"
    mock_confluence_fetcher.create_page.assert_called_once()


@pytest.mark.anyio
async def test_confluence_write_update(client, mock_confluence_fetcher):
    """Test write tool updates an existing page when page_id is provided."""
    response = await client.call_tool(
        "confluence_write", {"page_id": "123", "title": "Updated", "content": "# hi2"}
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "updated"
    mock_confluence_fetcher.update_page.assert_called_once()


@pytest.mark.anyio
async def test_confluence_write_delete_requires_confirm(client):
    """Test write tool requires confirm=true to delete a page."""
    with pytest.raises(Exception, match="confirm"):
        await client.call_tool("confluence_write", {"page_id": "123", "delete": True})


@pytest.mark.anyio
async def test_confluence_comment(client, mock_confluence_fetcher):
    """Test comment tool adds a comment to a page."""
    response = await client.call_tool(
        "confluence_comment", {"page_id": "123", "body": "nice page"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_confluence_fetcher.add_comment.assert_called_once_with(
        page_id="123", content="nice page"
    )
