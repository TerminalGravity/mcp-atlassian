"""Confluence FastMCP server instance and tool definitions."""

import json
import logging
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import BeforeValidator, Field

from mcp_atlassian.servers.dependencies import get_confluence_fetcher
from mcp_atlassian.utils.decorators import (
    check_write_access,
)

logger = logging.getLogger(__name__)

confluence_mcp = FastMCP(
    name="Confluence MCP Service",
    instructions="Provides tools for interacting with Atlassian Confluence.",
)

_GET_INCLUDES = {"children", "comments", "labels"}


@confluence_mcp.tool(
    tags={"confluence", "read"},
    annotations={"title": "Find Content", "readOnlyHint": True},
)
async def find(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Simple text or CQL ('type=page AND space=DEV', 'title~\"Notes\"', 'label=docs'). "
                "Simple text is wrapped in siteSearch automatically. "
                "With search_users=true, finds people instead."
            )
        ),
    ],
    spaces: Annotated[
        str | None,
        Field(description="(Optional) Comma-separated space keys to filter.", default=None),
    ] = None,
    search_users: Annotated[
        bool,
        Field(description="Search users instead of content.", default=False),
    ] = False,
    limit: Annotated[
        int,
        Field(description="Max results (1-50)", default=10, ge=1, le=50),
    ] = 10,
) -> str:
    """Search Confluence content (or users). Replaces search / search_user."""
    confluence_fetcher = await get_confluence_fetcher(ctx)
    if search_users:
        if query and not any(
            x in query for x in ["=", "~", ">", "<", " AND ", " OR ", "user."]
        ):
            query = f'user.fullname ~ "{query}"'
        users = confluence_fetcher.search_user(query, limit=limit)
        return json.dumps(
            {"results": [u.to_simplified_dict() for u in users]},
            indent=2,
            ensure_ascii=False,
        )
    if query and not any(
        x in query for x in ["=", "~", ">", "<", " AND ", " OR ", "currentUser()"]
    ):
        original = query
        try:
            query = f'siteSearch ~ "{original}"'
            pages = confluence_fetcher.search(query, limit=limit, spaces_filter=spaces)
        except Exception as e:
            logger.warning(f"siteSearch failed ('{e}'), falling back to text search.")
            query = f'text ~ "{original}"'
            pages = confluence_fetcher.search(query, limit=limit, spaces_filter=spaces)
    else:
        pages = confluence_fetcher.search(query, limit=limit, spaces_filter=spaces)
    return json.dumps(
        {"results": [p.to_simplified_dict() for p in pages]},
        indent=2,
        ensure_ascii=False,
    )


@confluence_mcp.tool(
    tags={"confluence", "read"},
    annotations={"title": "Get Page", "readOnlyHint": True},
)
async def get(
    ctx: Context,
    page_id: Annotated[
        str | int | None,
        Field(
            description="Page ID (from URL). Provide this OR title+space_key.",
            default=None,
        ),
    ] = None,
    title: Annotated[
        str | None,
        Field(description="Exact page title (with space_key).", default=None),
    ] = None,
    space_key: Annotated[
        str | None,
        Field(description="Space key (with title).", default=None),
    ] = None,
    include: Annotated[
        str | None,
        Field(
            description="(Optional) Extras, comma-separated: 'children', 'comments', 'labels'.",
            default=None,
        ),
    ] = None,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Markdown (default) or raw HTML (token-heavy).",
            default=True,
        ),
    ] = True,
) -> str:
    """Get a Confluence page with optional children/comments/labels in ONE call.

    Replaces get_page / get_page_children / get_comments / get_labels.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    includes = {i.strip() for i in (include or "").split(",") if i.strip()}
    invalid = includes - _GET_INCLUDES
    if invalid:
        raise ValueError(
            f"Invalid include value(s): {sorted(invalid)}. Valid: {sorted(_GET_INCLUDES)}."
        )
    page_object = None
    if page_id:
        page_object = confluence_fetcher.get_page_content(
            str(page_id), convert_to_markdown=convert_to_markdown
        )
    elif title and space_key:
        page_object = confluence_fetcher.get_page_by_title(
            space_key, title, convert_to_markdown=convert_to_markdown
        )
    else:
        raise ValueError("Provide page_id OR both title and space_key.")
    if not page_object:
        return json.dumps(
            {"error": "Page not found with the provided identifiers."},
            indent=2,
            ensure_ascii=False,
        )
    resolved_id = str(page_id or getattr(page_object, "id", "") or "")
    result: dict = {"metadata": page_object.to_simplified_dict()}
    if "children" in includes:
        children = confluence_fetcher.get_page_children(
            page_id=resolved_id,
            start=0,
            limit=25,
            expand="version",
            convert_to_markdown=convert_to_markdown,
            include_folders=True,
        )
        result["children"] = [c.to_simplified_dict() for c in children]
        if len(children) >= 25:
            result["children_truncated"] = "Showing first 25 children; more exist."
    if "comments" in includes:
        result["comments"] = [
            c.to_simplified_dict()
            for c in confluence_fetcher.get_page_comments(resolved_id)
        ]
    if "labels" in includes:
        result["labels"] = [
            label.to_simplified_dict()
            for label in confluence_fetcher.get_page_labels(resolved_id)
        ]
    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(
    tags={"confluence", "write"},
    annotations={"title": "Write Page", "destructiveHint": True},
)
@check_write_access
async def write(
    ctx: Context,
    page_id: Annotated[
        str | None,
        Field(
            description="Existing page ID → update (or delete). Omit → create.",
            default=None,
        ),
    ] = None,
    space_key: Annotated[
        str | None,
        Field(description="(create) Space key, e.g. 'DEV'.", default=None),
    ] = None,
    title: Annotated[
        str | None,
        Field(description="Page title (required for create and update).", default=None),
    ] = None,
    content: Annotated[
        str | None,
        Field(description="Page body; format per content_format.", default=None),
    ] = None,
    parent_id: Annotated[
        str | None,
        Field(description="(Optional) Parent page ID.", default=None),
        BeforeValidator(lambda x: str(x) if x is not None else None),
    ] = None,
    content_format: Annotated[
        str,
        Field(
            description="'markdown' (default), 'wiki', or 'storage'.",
            default="markdown",
        ),
    ] = "markdown",
    labels: Annotated[
        str | None,
        Field(
            description="(Optional) Comma-separated labels to add after writing.",
            default=None,
        ),
    ] = None,
    version_comment: Annotated[
        str | None,
        Field(description="(update) Version comment.", default=None),
    ] = None,
    delete: Annotated[
        bool,
        Field(
            description="Delete the page (requires page_id and confirm=true).",
            default=False,
        ),
    ] = False,
    confirm: Annotated[
        bool,
        Field(description="Required true for delete.", default=False),
    ] = False,
) -> str:
    """Create, update, or delete a Confluence page (one tool).

    Replaces create_page / update_page / delete_page / add_label.
    page_id present → update; absent → create; delete=true → delete.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    if delete:
        if not page_id:
            raise ValueError("delete=true requires page_id.")
        if not confirm:
            raise ValueError("Deleting a page requires confirm=true.")
        ok = confluence_fetcher.delete_page(page_id=page_id)
        return json.dumps(
            {"success": bool(ok), "action": "deleted", "page_id": page_id},
            indent=2,
            ensure_ascii=False,
        )
    if content_format not in ("markdown", "wiki", "storage"):
        raise ValueError(
            f"Invalid content_format: {content_format}. Must be 'markdown', 'wiki', or 'storage'."
        )
    if not title or content is None:
        raise ValueError("title and content are required for create/update.")
    is_markdown = content_format == "markdown"
    content_representation = None if is_markdown else content_format
    if page_id:
        page = confluence_fetcher.update_page(
            page_id=page_id,
            title=title,
            body=content,
            is_minor_edit=False,
            version_comment=version_comment or "",
            is_markdown=is_markdown,
            parent_id=parent_id,
            content_representation=content_representation,
        )
        action = "updated"
    else:
        if not space_key:
            raise ValueError("space_key is required to create a page.")
        page = confluence_fetcher.create_page(
            space_key=space_key,
            title=title,
            body=content,
            parent_id=parent_id,
            is_markdown=is_markdown,
            content_representation=content_representation,
        )
        action = "created"
    result: dict = {"action": action, "page": page.to_simplified_dict()}
    if labels:
        applied = []
        for name in [s.strip() for s in labels.split(",") if s.strip()]:
            try:
                confluence_fetcher.add_page_label(
                    str(page_id or result["page"].get("id")), name
                )
                applied.append(name)
            except Exception as e:
                logger.warning(f"confluence_write: label '{name}' failed: {e}")
        result["labels_added"] = applied
    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(
    tags={"confluence", "write"},
    annotations={"title": "Comment on Page", "destructiveHint": True},
)
@check_write_access
async def comment(
    ctx: Context,
    page_id: Annotated[str, Field(description="The page to comment on.")],
    body: Annotated[str, Field(description="Comment content (Markdown).")],
) -> str:
    """Add a comment to a Confluence page. Replaces add_comment."""
    confluence_fetcher = await get_confluence_fetcher(ctx)
    created = confluence_fetcher.add_comment(page_id=page_id, content=body)
    if created:
        return json.dumps(
            {"success": True, "comment": created.to_simplified_dict()},
            indent=2,
            ensure_ascii=False,
        )
    return json.dumps(
        {"success": False, "message": f"Unable to add comment to page {page_id}."},
        indent=2,
        ensure_ascii=False,
    )
