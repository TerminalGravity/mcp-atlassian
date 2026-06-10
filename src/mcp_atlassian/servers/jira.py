"""Jira FastMCP server instance and tool definitions."""

import json
import logging
import re
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field
from requests.exceptions import HTTPError

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError
from mcp_atlassian.jira.constants import DEFAULT_READ_JIRA_FIELDS
from mcp_atlassian.jira.response_formatter import ResponseFormatter
from mcp_atlassian.models.jira.common import JiraUser
from mcp_atlassian.servers.dependencies import get_jira_fetcher
from mcp_atlassian.utils.decorators import check_write_access

logger = logging.getLogger(__name__)

jira_mcp = FastMCP(
    name="Jira MCP Service",
    instructions="Provides tools for interacting with Atlassian Jira.",
)


SUMMARY_FIELDS = ["summary", "status", "priority", "assignee", "issuetype", "updated"]


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _issue_url(jira: Any, issue_key: str) -> str:
    return f"{jira.config.url.rstrip('/')}/browse/{issue_key}"


def _field_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key", "id"):
            if value.get(key) is not None:
                return value.get(key)
    return value


def _shape_issue_dict(
    issue: dict[str, Any] | None,
    *,
    return_mode: str = "summary",
    response_fields: str | None = None,
) -> dict[str, Any] | None:
    if issue is None:
        return None
    if return_mode == "full":
        return issue

    key = issue.get("key")
    shaped: dict[str, Any] = {
        "key": key,
        "url": issue.get("url"),
    }

    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    if return_mode == "minimal":
        return {k: v for k, v in shaped.items() if v is not None}

    wanted = _parse_csv(response_fields) or SUMMARY_FIELDS
    for field in wanted:
        if field == "key":
            shaped["key"] = key
        elif field == "url":
            shaped["url"] = issue.get("url")
        elif field in issue:
            shaped[field] = issue[field]
        elif field in fields:
            shaped[field] = _field_value(fields[field])

    return {k: v for k, v in shaped.items() if v is not None}


def _shape_issue_model(
    jira: Any,
    issue: Any,
    *,
    return_mode: str = "summary",
    response_fields: str | None = None,
) -> dict[str, Any] | None:
    if issue is None:
        return None
    raw = issue.to_simplified_dict()
    if raw.get("key") and not raw.get("url"):
        raw["url"] = _issue_url(jira, raw["key"])
    if return_mode == "full":
        return raw
    compressed = ResponseFormatter.compress_issue(raw, include_description=False)
    if compressed.get("key") and not compressed.get("url"):
        compressed["url"] = _issue_url(jira, compressed["key"])
    return _shape_issue_dict(
        compressed, return_mode=return_mode, response_fields=response_fields
    )


def _operation_response(
    jira: Any,
    *,
    message: str,
    issue: Any = None,
    issue_key: str | None = None,
    return_mode: str = "summary",
    response_fields: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    result: dict[str, Any] = {"message": message}
    key = issue_key
    # Response shaping must NEVER fail a write that already succeeded —
    # an error response after a completed write makes the agent retry and
    # duplicate the operation (observed 2026-05-12: assignee writes
    # succeeded while their responses errored; agent re-ran them).
    try:
        if issue is not None:
            shaped = _shape_issue_model(
                jira,
                issue,
                return_mode=return_mode,
                response_fields=response_fields,
            )
            if shaped:
                key = shaped.get("key") or key
                result["issue"] = shaped
    except Exception as e:
        logger.warning(f"_operation_response: shaping failed, degrading: {e}")
        result["response_shaping_error"] = str(e)
        if issue is not None and key is None:
            key = getattr(issue, "key", None)
    if key:
        result["key"] = key
        result["url"] = _issue_url(jira, key)
    if extra:
        try:
            result.update(extra)
        except Exception:
            pass
    try:
        return _json(result)
    except Exception as e:
        logger.warning(f"_operation_response: serialization failed: {e}")
        return json.dumps(
            {"message": message, "key": key, "serialization_error": str(e)}
        )


def _find_transition(
    transitions: list[dict[str, Any]], target_status: str
) -> dict[str, Any] | None:
    target = target_status.casefold()
    for transition in transitions:
        if str(transition.get("to_status", "")).casefold() == target:
            return transition
        to_data = transition.get("to")
        if isinstance(to_data, dict) and str(to_data.get("name", "")).casefold() == target:
            return transition
    for transition in transitions:
        if str(transition.get("name", "")).casefold() == target:
            return transition
    return None


def _resolve_transition_id(
    jira: Any, issue_key: str, status_name: str
) -> str:
    """Map a human-readable status/transition name to its transition id."""
    transitions = jira.get_available_transitions(issue_key)
    match = _find_transition(transitions, status_name)
    if match is None:
        available = ", ".join(
            f"'{t.get('to_status') or t.get('name')}' (id {t.get('id')})"
            for t in transitions
        )
        raise ValueError(
            f"No transition from {issue_key}'s current status matches "
            f"'{status_name}'. Available transitions: {available or 'none'}. "
            "Retry with one of those names as status_name, or pass the id "
            "as transition_id."
        )
    return str(match.get("id"))


def _next_transitions(jira: Any, issue_key: str) -> list[dict[str, Any]]:
    """Compact {id, to_status} list of moves valid from the issue's new status."""
    try:
        return [
            {"id": t.get("id"), "to_status": t.get("to_status") or t.get("name")}
            for t in jira.get_available_transitions(issue_key)
        ]
    except Exception:  # response enrichment must never fail the operation
        return []


def _find_recent_duplicate(
    jira: Any, project_key: str, summary: str
) -> str | None:
    """Key of an issue with the same summary created in the project within
    the last 10 minutes, else None. Fails open: a guard error never blocks
    creation. Summary comparison is exact (casefolded) client-side — the
    summary is deliberately kept out of the JQL to avoid fuzzy-match noise
    and quoting pitfalls."""
    try:
        result = jira.search_issues(
            jql=f'project = "{project_key}" AND created >= "-10m"',
            fields=["summary"],
            limit=20,
        )
        target = summary.strip().casefold()
        for issue in result.issues:
            raw = issue.to_simplified_dict()
            candidate = str(
                raw.get("summary")
                or (raw.get("fields") or {}).get("summary")
                or ""
            )
            if candidate.strip().casefold() == target:
                return raw.get("key")
    except Exception as e:
        logger.warning(f"create_issue duplicate guard skipped: {e}")
    return None


TRUNC_HINT = '… [truncated — use response_format="full" for complete text]'


def _truncate_tagged(text: str | None, limit: int) -> str | None:
    """Truncate with an explicit steering hint so the agent knows how to get more."""
    if not text:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + TRUNC_HINT


def _issue_card(
    jira: Any,
    issue: Any,
    *,
    response_format: str = "summary",
    extras_from_raw: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Token-budgeted issue view. summary ≈ 1 KB regardless of issue size.

    extras_from_raw: top-level keys copied verbatim from the simplified dict
    into the summary card after compression (e.g. 'changelogs', which
    compress_issue would otherwise drop).
    """
    raw = issue.to_simplified_dict()
    if raw.get("key") and not raw.get("url"):
        raw["url"] = _issue_url(jira, raw["key"])
    if response_format == "full":
        return raw

    card = ResponseFormatter.compress_issue(raw, include_description=False)
    for extra_key in extras_from_raw:
        if raw.get(extra_key) is not None:
            card[extra_key] = raw[extra_key]
    card["url"] = raw.get("url")
    if raw.get("description"):
        card["description"] = _truncate_tagged(raw["description"], 400)
    comments = raw.get("comments") or []
    if comments:
        card["comments_total"] = len(comments)
        card["latest_comments"] = [
            {
                "author": (
                    (c.get("author") or {}).get("display_name")
                    if isinstance(c.get("author"), dict)
                    else c.get("author")
                ),
                "created": ResponseFormatter._relative_timestamp(c.get("created")),
                "body": _truncate_tagged(str(c.get("body") or ""), 200),
            }
            for c in comments[-2:]
        ]
    return {k: v for k, v in card.items() if v is not None}


_GET_INCLUDES = {"changelog", "dates", "sla"}


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Issues", "readOnlyHint": True},
)
async def get(
    ctx: Context,
    keys: Annotated[
        str,
        Field(
            description=(
                "One Jira issue key or a comma-separated list (e.g. 'DS-123' or "
                "'DS-123,DS-124,DS-125'). Pass many keys in ONE call instead of "
                "calling once per key."
            )
        ),
    ],
    response_format: Annotated[
        str,
        Field(
            description=(
                "'summary' (default, ~1 KB/issue: triage fields + truncated "
                "description + latest 2 comments truncated) or 'full' (complete "
                "description and all fetched comments). summary answers "
                "status/assignee/triage questions — request full only when you "
                "need complete text."
            ),
            default="summary",
        ),
    ] = "summary",
    fields: Annotated[
        str,
        Field(
            description=(
                "(Optional) Comma-separated Jira fields to fetch. '*all' for "
                "everything. Default: essential fields."
            ),
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    comment_limit: Annotated[
        int,
        Field(description="Max comments fetched per issue (0 = none)", default=10, ge=0, le=100),
    ] = 10,
    include: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Extras, comma-separated: 'changelog' (status history), "
                "'dates' (created/updated/due/resolution + status durations), "
                "'sla' (cycle/lead time metrics)."
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Get one or many Jira issues in a token-budgeted form.

    Replaces get_issue / get_issue_summary / quick_status / batch_get_changelogs /
    get_issue_dates / get_issue_sla. For finding issues by query, use jira_find.
    Re-fetching with summary format is cheap — don't hoard full payloads.

    Returns:
        JSON object mapping each requested key to its issue card (or
        {"error": ...} for keys that failed — one bad key never fails the batch).
    """
    jira = await get_jira_fetcher(ctx)
    key_list = _parse_csv(keys) or []
    if not key_list:
        raise ValueError("keys is required (one key or comma-separated keys).")
    includes = set(_parse_csv(include) or [])
    invalid = includes - _GET_INCLUDES
    if invalid:
        raise ValueError(
            f"Invalid include value(s): {sorted(invalid)}. "
            f"Valid: {sorted(_GET_INCLUDES)}."
        )

    fields_list: str | list[str] | None = fields
    if fields and fields != "*all":
        fields_list = [f.strip() for f in fields.split(",")]
    expand = "changelog" if "changelog" in includes else None

    out: dict[str, Any] = {}
    for key in key_list:
        try:
            issue = jira.get_issue(
                issue_key=key,
                fields=fields_list,
                expand=expand,
                comment_limit=comment_limit,
                properties=None,
                update_history=False,
            )
            card = _issue_card(
                jira,
                issue,
                response_format=response_format,
                extras_from_raw=(
                    ("changelogs",) if "changelog" in includes else ()
                ),
            )
            if "dates" in includes:
                try:
                    card["dates"] = jira.get_issue_dates(
                        issue_key=key,
                        include_created=True,
                        include_updated=True,
                        include_due_date=True,
                        include_resolution_date=True,
                        include_status_changes=True,
                        include_status_summary=True,
                    ).to_simplified_dict()
                except Exception as e:  # extras never fail the read
                    card["dates"] = {"error": str(e)}
            if "sla" in includes:
                try:
                    card["sla"] = jira.get_issue_sla(
                        issue_key=key,
                        metrics=None,
                        working_hours_only=None,
                        include_raw_dates=False,
                    ).to_simplified_dict()
                except Exception as e:
                    card["sla"] = {"error": str(e)}
            out[key] = card
        except Exception as e:
            logger.warning(f"jira_get: {key} failed: {e}")
            out[key] = {"error": str(e)}
    return _json(out)


_JQL_MARKERS = re.compile(
    r"[=~<>]|\bORDER\s+BY\b|\bAND\b|\bOR\b|\bin\s*\(", re.IGNORECASE
)


def _looks_like_jql(query: str) -> bool:
    """Heuristic: JQL contains operators/keywords natural language doesn't."""
    return bool(_JQL_MARKERS.search(query or ""))


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Find Issues", "readOnlyHint": True},
)
async def find(
    ctx: Context,
    query: Annotated[
        str | None,
        Field(
            description=(
                "JQL ('project = DS AND status = \"In Progress\"') or natural "
                "language ('auth failures in checkout'). JQL is auto-detected; "
                "natural language uses semantic search over the synced index."
            ),
            default=None,
        ),
    ] = None,
    mode: Annotated[
        str,
        Field(
            description="'auto' (default — detect), 'jql', or 'semantic' to force a path.",
            default="auto",
        ),
    ] = "auto",
    similar_to: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) An issue key (e.g. 'DS-1234'); finds semantically "
                "similar issues (duplicate detection). Used instead of query."
            ),
            default=None,
        ),
    ] = None,
    fields: Annotated[
        str,
        Field(
            description="(Optional, JQL mode) Comma-separated fields per result. Default: triage set.",
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    limit: Annotated[
        int, Field(description="Max results (1-50)", default=10, ge=1, le=50)
    ] = 10,
    start_at: Annotated[
        int, Field(description="Pagination offset (0-based)", default=0, ge=0)
    ] = 0,
    projects_filter: Annotated[
        str | None,
        Field(description="(Optional) Comma-separated project keys to restrict results.", default=None),
    ] = None,
) -> str:
    """Find Jira issues — the ONLY search tool. JQL, semantic, or similar-to.

    Replaces search / list_issues / get_project_issues / semantic_search /
    find_similar / detect_duplicates. Results include the triage fields
    (status, assignee, priority, type, updated) so per-key follow-up
    jira_get calls are usually unnecessary. Narrow the query rather than
    paginating deeply.
    """
    jira = await get_jira_fetcher(ctx)
    projects = _parse_csv(projects_filter)

    if similar_to:
        issue = jira.get_issue(
            issue_key=similar_to,
            fields=["summary", "description"],
            comment_limit=0,
            update_history=False,
        )
        raw = issue.to_simplified_dict()
        text = f"{raw.get('summary') or ''}\n{(raw.get('description') or '')[:1000]}"
        from mcp_atlassian.servers.vector_tools import semantic_search_impl

        result = await semantic_search_impl(
            text, projects=projects, limit=limit, exclude_key=similar_to
        )
        result["mode"] = "similar"
        result["similar_to"] = similar_to
        return _json(result)

    if not query:
        raise ValueError("Provide query (JQL or natural language) or similar_to.")

    use_jql = mode == "jql" or (mode == "auto" and _looks_like_jql(query))
    if use_jql:
        fields_list: str | list[str] | None = fields
        if fields and fields != "*all":
            fields_list = [f.strip() for f in fields.split(",")]
        search_result = jira.search_issues(
            jql=query,
            fields=fields_list,
            limit=limit,
            start=start_at,
            projects_filter=projects_filter,
        )
        result = ResponseFormatter.compress_search_result(
            search_result.to_simplified_dict()
        )
        result["mode"] = "jql"
        if result.get("total", 0) > start_at + limit:
            result["hint"] = (
                "More results exist — narrow the JQL (project, status, updated) "
                "rather than paginating."
            )
        return _json(result)

    from mcp_atlassian.servers.vector_tools import semantic_search_impl

    result = await semantic_search_impl(
        query, projects=projects, limit=limit, offset=start_at
    )
    result["mode"] = "semantic"
    result["query"] = query
    return _json(result)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get User Profile", "readOnlyHint": True},
)
async def get_user_profile(
    ctx: Context,
    user_identifier: Annotated[
        str,
        Field(
            description="Identifier for the user (e.g., email address 'user@example.com', username 'johndoe', account ID 'accountid:...', or key for Server/DC)."
        ),
    ],
) -> str:
    """
    Retrieve profile information for a specific Jira user.

    Args:
        ctx: The FastMCP context.
        user_identifier: User identifier (email, username, key, or account ID).

    Returns:
        JSON string representing the Jira user profile object, or an error object if not found.

    Raises:
        ValueError: If the Jira client is not configured or available.
    """
    jira = await get_jira_fetcher(ctx)
    try:
        user: JiraUser = jira.get_user_profile_by_identifier(user_identifier)
        result = user.to_simplified_dict()
        response_data = {"success": True, "user": result}
    except Exception as e:
        error_message = ""
        log_level = logging.ERROR
        if isinstance(e, ValueError) and "not found" in str(e).lower():
            log_level = logging.WARNING
            error_message = str(e)
        elif isinstance(e, MCPAtlassianAuthenticationError):
            error_message = f"Authentication/Permission Error: {str(e)}"
        elif isinstance(e, OSError | HTTPError):
            error_message = f"Network or API Error: {str(e)}"
        else:
            error_message = (
                "An unexpected error occurred while fetching the user profile."
            )
            logger.exception(
                f"Unexpected error in get_user_profile for '{user_identifier}':"
            )
        error_result = {
            "success": False,
            "error": str(e),
            "user_identifier": user_identifier,
        }
        logger.log(
            log_level,
            f"get_user_profile failed for '{user_identifier}': {error_message}",
        )
        response_data = error_result
    return json.dumps(response_data, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Issue", "readOnlyHint": True},
)
async def get_issue(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    fields: Annotated[
        str,
        Field(
            description=(
                "(Optional) Comma-separated list of fields to return (e.g., 'summary,status,customfield_10010'). "
                "You may also provide a single field as a string (e.g., 'duedate'). "
                "Use '*all' for all fields (including custom fields), or omit for essential fields only."
            ),
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    expand: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Fields to expand. Examples: 'renderedFields' (for rendered content), "
                "'transitions' (for available status transitions), 'changelog' (for history)"
            ),
            default=None,
        ),
    ] = None,
    comment_limit: Annotated[
        int,
        Field(
            description="Maximum number of comments to include (0 or null for no comments)",
            default=10,
            ge=0,
            le=100,
        ),
    ] = 10,
    properties: Annotated[
        str | None,
        Field(
            description="(Optional) A comma-separated list of issue properties to return",
            default=None,
        ),
    ] = None,
    update_history: Annotated[
        bool,
        Field(
            description="Whether to update the issue view history for the requesting user",
            default=True,
        ),
    ] = True,
    return_mode: Annotated[
        str,
        Field(
            description="Response size mode: 'summary' (default), 'minimal', or 'full'. Use full for the legacy complete payload.",
            default="summary",
        ),
    ] = "summary",
    response_fields: Annotated[
        str | None,
        Field(
            description="Comma-separated fields to include when return_mode is summary. Examples: key,summary,status,assignee,updated",
            default=None,
        ),
    ] = None,
) -> str:
    """Get details of a specific Jira issue including its Epic links and relationship information.

    For a status/assignee-only check (e.g. polling a ticket in a sweep), use
    jira_quick_status instead — it returns a few fields for many keys in one
    call and costs a fraction of the context.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        fields: Comma-separated list of fields to return (e.g., 'summary,status,customfield_10010'), a single field as a string (e.g., 'duedate'), '*all' for all fields, or omitted for essentials.
        expand: Optional fields to expand.
        comment_limit: Maximum number of comments.
        properties: Issue properties to return.
        update_history: Whether to update issue view history.

    Returns:
        JSON string representing the Jira issue object.

    Raises:
        ValueError: If the Jira client is not configured or available.
    """
    jira = await get_jira_fetcher(ctx)
    fields_list: str | list[str] | None = fields
    if fields and fields != "*all":
        fields_list = [f.strip() for f in fields.split(",")]

    issue = jira.get_issue(
        issue_key=issue_key,
        fields=fields_list,
        expand=expand,
        comment_limit=comment_limit,
        properties=properties.split(",") if properties else None,
        update_history=update_history,
    )
    result = _shape_issue_model(
        jira,
        issue,
        return_mode=return_mode,
        response_fields=response_fields,
    )
    return _json(result)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Issue Summary", "readOnlyHint": True},
)
async def get_issue_summary(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
) -> str:
    """Get a compressed summary of a Jira issue for quick reference.

    Returns minimal fields: key, summary, status, priority, assignee, type, updated.
    Use jira_get_issue for full details.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.

    Returns:
        JSON string with compressed issue summary.

    Raises:
        ValueError: If the Jira client is not configured or available.
    """
    jira = await get_jira_fetcher(ctx)
    issue = jira.get_issue(
        issue_key=issue_key,
        fields=["summary", "status", "priority", "assignee", "issuetype", "updated"],
        comment_limit=0,
        update_history=False,
    )
    result = issue.to_simplified_dict()
    compressed = ResponseFormatter.compress_issue(result, include_description=False)
    return json.dumps(compressed, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Quick Status", "readOnlyHint": True},
)
async def quick_status(
    ctx: Context,
    keys: Annotated[
        str,
        Field(
            description=(
                "Comma-separated Jira issue keys (e.g., 'DS-12704,DS-12705'). "
                "Returns a minimal per-key status map. Use this as the cheap "
                "read-after-write verification step instead of jira_search."
            )
        ),
    ],
) -> str:
    """Get a minimal status map for one or more Jira issues.

    Returns ``{<key>: {status, assignee, priority}}`` for every requested
    key. Tickets not found are emitted with
    ``{status: null, error: "not found"}``.

    Args:
        ctx: The FastMCP context.
        keys: Comma-separated Jira issue keys.

    Returns:
        JSON object mapping each input key to its current status snapshot.
    """
    jira = await get_jira_fetcher(ctx)
    key_list = _parse_csv(keys) or []
    if not key_list:
        raise ValueError("keys is required (comma-separated Jira issue keys).")

    jql = f"key in ({', '.join(key_list)})"
    search_result = jira.search_issues(
        jql=jql,
        fields=["status", "assignee", "priority"],
        limit=max(len(key_list) * 2, 10),
    )

    found: dict[str, dict[str, Any]] = {}
    for issue in search_result.issues:
        raw = issue.to_simplified_dict()
        found[raw.get("key", "?")] = {
            "status": _field_value(raw.get("status")),
            "assignee": _field_value(raw.get("assignee")),
            "priority": _field_value(raw.get("priority")),
        }

    result: dict[str, Any] = {}
    for key in key_list:
        if key in found:
            result[key] = found[key]
        else:
            result[key] = {"status": None, "error": "not found"}
    return _json(result)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Keys From Text", "readOnlyHint": True},
)
async def keys_from_text(
    ctx: Context,
    text: Annotated[
        str,
        Field(
            description=(
                "Arbitrary text (PR title, branch name, commit message, etc.) "
                "to scan for Jira issue keys."
            )
        ),
    ],
    project_filter: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Comma-separated project prefixes to keep (e.g. 'DS,CM'). "
                "Default: keep all keys found."
            ),
            default=None,
        ),
    ] = None,
    dedupe: Annotated[
        bool,
        Field(
            description="If true (default), de-duplicate keys.",
            default=True,
        ),
    ] = True,
) -> str:
    """Extract Jira issue keys from arbitrary text.

    Useful for reconciling PR titles / branch names / commit messages
    against tickets in the queue.

    Args:
        ctx: The FastMCP context.
        text: The text to scan.
        project_filter: Optional comma-separated allowlist of project prefixes.
        dedupe: De-duplicate keys (default True).

    Returns:
        JSON ``{keys: [...], count: N}``.
    """
    _ = await get_jira_fetcher(ctx)  # validates session is configured
    pattern = re.compile(r"\b([A-Z][A-Z0-9]+)-(\d+)\b")
    keys = [f"{m.group(1)}-{m.group(2)}" for m in pattern.finditer(text or "")]
    if project_filter:
        allowed = {
            p.strip().upper() for p in project_filter.split(",") if p.strip()
        }
        keys = [k for k in keys if k.split("-", 1)[0] in allowed]
    if dedupe:
        seen: set[str] = set()
        keys = [k for k in keys if not (k in seen or seen.add(k))]
    return _json({"keys": keys, "count": len(keys)})


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Search Issues", "readOnlyHint": True},
)
async def search(
    ctx: Context,
    jql: Annotated[
        str,
        Field(
            description=(
                "JQL query string (Jira Query Language). Examples:\n"
                '- Find Epics: "issuetype = Epic AND project = PROJ"\n'
                '- Find issues in Epic: "parent = PROJ-123"\n'
                "- Find by status: \"status = 'In Progress' AND project = PROJ\"\n"
                '- Find by assignee: "assignee = currentUser()"\n'
                '- Find recently updated: "updated >= -7d AND project = PROJ"\n'
                '- Find by label: "labels = frontend AND project = PROJ"\n'
                '- Find by priority: "priority = High AND project = PROJ"'
            )
        ),
    ],
    fields: Annotated[
        str,
        Field(
            description=(
                "(Optional) Comma-separated fields to return in the results. "
                "Use '*all' for all fields, or specify individual fields like 'summary,status,assignee,priority'"
            ),
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1),
    ] = 10,
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    projects_filter: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Comma-separated list of project keys to filter results by. "
                "Overrides the environment variable JIRA_PROJECTS_FILTER if provided."
            ),
            default=None,
        ),
    ] = None,
    expand: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) fields to expand. Examples: 'renderedFields', 'transitions', 'changelog'"
            ),
            default=None,
        ),
    ] = None,
    compact: Annotated[
        bool,
        Field(
            description=(
                "If true (default), returns compressed response with truncated descriptions, "
                "flattened objects, and relative timestamps. Set to false for full API response."
            ),
            default=True,
        ),
    ] = True,
) -> str:
    """Search Jira issues using JQL (Jira Query Language).

    Args:
        ctx: The FastMCP context.
        jql: JQL query string.
        fields: Comma-separated fields to return.
        limit: Maximum number of results.
        start_at: Starting index for pagination.
        projects_filter: Comma-separated list of project keys to filter by.
        expand: Optional fields to expand.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing the search results including pagination info.
    """
    jira = await get_jira_fetcher(ctx)
    fields_list: str | list[str] | None = fields
    if fields and fields != "*all":
        fields_list = [f.strip() for f in fields.split(",")]

    search_result = jira.search_issues(
        jql=jql,
        fields=fields_list,
        limit=limit,
        start=start_at,
        expand=expand,
        projects_filter=projects_filter,
    )
    result = search_result.to_simplified_dict()

    if compact:
        result = ResponseFormatter.compress_search_result(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "List Issues", "readOnlyHint": True},
)
async def list_issues(
    ctx: Context,
    project: Annotated[
        str | None,
        Field(
            description="Project key to list issues from (e.g., 'PROJ'). If not provided, lists issues across all projects.",
            default=None,
        ),
    ] = None,
    status: Annotated[
        str | None,
        Field(
            description="Filter by status (e.g., 'In Progress', 'Done'). Case-insensitive.",
            default=None,
        ),
    ] = None,
    assignee: Annotated[
        str | None,
        Field(
            description="Filter by assignee. Use 'currentUser()' for your issues, or provide username/email.",
            default=None,
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1),
    ] = 10,
) -> str:
    """List Jira issues with simple filters. Returns compressed results for quick browsing.

    For complex queries, use jira_search with JQL instead.
    For full issue details, use jira_get_issue.

    Args:
        ctx: The FastMCP context.
        project: Project key to filter by.
        status: Status to filter by.
        assignee: Assignee to filter by.
        limit: Maximum number of results.

    Returns:
        JSON string with compressed issue list.
    """
    jira = await get_jira_fetcher(ctx)

    # Build JQL from simple filters
    conditions = []
    if project:
        conditions.append(f"project = {project}")
    if status:
        conditions.append(f"status = '{status}'")
    if assignee:
        if assignee.lower() == "currentuser()":
            conditions.append("assignee = currentUser()")
        else:
            conditions.append(f"assignee = '{assignee}'")

    jql = " AND ".join(conditions) if conditions else "ORDER BY updated DESC"
    if conditions:
        jql += " ORDER BY updated DESC"

    search_result = jira.search_issues(
        jql=jql,
        fields=["summary", "status", "priority", "assignee", "issuetype", "updated"],
        limit=limit,
    )
    result = search_result.to_simplified_dict()
    result = ResponseFormatter.compress_search_result(result, include_description=False)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Search Fields", "readOnlyHint": True},
)
async def search_fields(
    ctx: Context,
    keyword: Annotated[
        str,
        Field(
            description="Keyword for fuzzy search. If left empty, lists the first 'limit' available fields in their default order.",
            default="",
        ),
    ] = "",
    limit: Annotated[
        int, Field(description="Maximum number of results", default=10, ge=1)
    ] = 10,
    refresh: Annotated[
        bool,
        Field(description="Whether to force refresh the field list", default=False),
    ] = False,
) -> str:
    """Search Jira fields by keyword with fuzzy match.

    Args:
        ctx: The FastMCP context.
        keyword: Keyword for fuzzy search.
        limit: Maximum number of results.
        refresh: Whether to force refresh the field list.

    Returns:
        JSON string representing a list of matching field definitions.
    """
    jira = await get_jira_fetcher(ctx)
    result = jira.search_fields(keyword, limit=limit, refresh=refresh)
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Project Issues", "readOnlyHint": True},
)
async def get_project_issues(
    ctx: Context,
    project_key: Annotated[str, Field(description="The project key")],
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
    ] = 10,
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get all issues for a specific Jira project.

    Args:
        ctx: The FastMCP context.
        project_key: The project key.
        limit: Maximum number of results.
        start_at: Starting index for pagination.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing the search results including pagination info.
    """
    jira = await get_jira_fetcher(ctx)
    search_result = jira.get_project_issues(
        project_key=project_key, start=start_at, limit=limit
    )
    result = search_result.to_simplified_dict()

    if compact:
        result = ResponseFormatter.compress_search_result(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Transitions", "readOnlyHint": True},
)
async def get_transitions(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
) -> str:
    """Get available status transitions for a Jira issue.

    Usually unnecessary: jira_transition_issue and jira_batch_transition
    accept status_name (e.g. 'Ready for QA') and resolve the transition id
    server-side; their responses include next_transitions. Call this only
    to inspect a workflow without transitioning.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.

    Returns:
        JSON string representing a list of available transitions.
    """
    jira = await get_jira_fetcher(ctx)
    # Underlying method returns list[dict] in the desired format
    transitions = jira.get_available_transitions(issue_key)
    return json.dumps(transitions, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Worklog", "readOnlyHint": True},
)
async def get_worklog(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
) -> str:
    """Get worklog entries for a Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.

    Returns:
        JSON string representing the worklog entries.
    """
    jira = await get_jira_fetcher(ctx)
    worklogs = jira.get_worklogs(issue_key)
    result = {"worklogs": worklogs}
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Download Attachments", "readOnlyHint": True},
)
async def download_attachments(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    target_dir: Annotated[
        str, Field(description="Directory where attachments should be saved")
    ],
) -> str:
    """Download attachments from a Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        target_dir: Directory to save attachments.

    Returns:
        JSON string indicating the result of the download operation.
    """
    jira = await get_jira_fetcher(ctx)
    result = jira.download_issue_attachments(issue_key=issue_key, target_dir=target_dir)
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Agile Boards", "readOnlyHint": True},
)
async def get_agile_boards(
    ctx: Context,
    board_name: Annotated[
        str | None,
        Field(description="(Optional) The name of board, support fuzzy search"),
    ] = None,
    project_key: Annotated[
        str | None, Field(description="(Optional) Jira project key (e.g., 'PROJ-123')")
    ] = None,
    board_type: Annotated[
        str | None,
        Field(
            description="(Optional) The type of jira board (e.g., 'scrum', 'kanban')"
        ),
    ] = None,
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
    ] = 10,
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get jira agile boards by name, project key, or type.

    Args:
        ctx: The FastMCP context.
        board_name: Name of the board (fuzzy search).
        project_key: Project key.
        board_type: Board type ('scrum' or 'kanban').
        start_at: Starting index.
        limit: Maximum results.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing a list of board objects.
    """
    jira = await get_jira_fetcher(ctx)
    boards = jira.get_all_agile_boards_model(
        board_name=board_name,
        project_key=project_key,
        board_type=board_type,
        start=start_at,
        limit=limit,
    )
    result = [board.to_simplified_dict() for board in boards]

    if compact:
        result = ResponseFormatter.compress_boards(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Board Issues", "readOnlyHint": True},
)
async def get_board_issues(
    ctx: Context,
    board_id: Annotated[str, Field(description="The id of the board (e.g., '1001')")],
    jql: Annotated[
        str,
        Field(
            description=(
                "JQL query string (Jira Query Language). Examples:\n"
                '- Find Epics: "issuetype = Epic AND project = PROJ"\n'
                '- Find issues in Epic: "parent = PROJ-123"\n'
                "- Find by status: \"status = 'In Progress' AND project = PROJ\"\n"
                '- Find by assignee: "assignee = currentUser()"\n'
                '- Find recently updated: "updated >= -7d AND project = PROJ"\n'
                '- Find by label: "labels = frontend AND project = PROJ"\n'
                '- Find by priority: "priority = High AND project = PROJ"'
            )
        ),
    ],
    fields: Annotated[
        str,
        Field(
            description=(
                "Comma-separated fields to return in the results. "
                "Use '*all' for all fields, or specify individual "
                "fields like 'summary,status,assignee,priority'"
            ),
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
    ] = 10,
    expand: Annotated[
        str,
        Field(
            description="Optional fields to expand in the response (e.g., 'changelog').",
            default="version",
        ),
    ] = "version",
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get all issues linked to a specific board filtered by JQL.

    Args:
        ctx: The FastMCP context.
        board_id: The ID of the board.
        jql: JQL query string to filter issues.
        fields: Comma-separated fields to return.
        start_at: Starting index for pagination.
        limit: Maximum number of results.
        expand: Optional fields to expand.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing the search results including pagination info.
    """
    jira = await get_jira_fetcher(ctx)
    fields_list: str | list[str] | None = fields
    if fields and fields != "*all":
        fields_list = [f.strip() for f in fields.split(",")]

    search_result = jira.get_board_issues(
        board_id=board_id,
        jql=jql,
        fields=fields_list,
        start=start_at,
        limit=limit,
        expand=expand,
    )
    result = search_result.to_simplified_dict()

    if compact:
        result = ResponseFormatter.compress_search_result(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Sprints from Board", "readOnlyHint": True},
)
async def get_sprints_from_board(
    ctx: Context,
    board_id: Annotated[str, Field(description="The id of board (e.g., '1000')")],
    state: Annotated[
        str | None,
        Field(description="Sprint state (e.g., 'active', 'future', 'closed')"),
    ] = None,
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
    ] = 10,
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get jira sprints from board by state.

    Args:
        ctx: The FastMCP context.
        board_id: The ID of the board.
        state: Sprint state ('active', 'future', 'closed'). If None, returns all sprints.
        start_at: Starting index.
        limit: Maximum results.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing a list of sprint objects.
    """
    jira = await get_jira_fetcher(ctx)
    sprints = jira.get_all_sprints_from_board_model(
        board_id=board_id, state=state, start=start_at, limit=limit
    )
    result = [sprint.to_simplified_dict() for sprint in sprints]

    if compact:
        result = ResponseFormatter.compress_sprints(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Sprint Issues", "readOnlyHint": True},
)
async def get_sprint_issues(
    ctx: Context,
    sprint_id: Annotated[str, Field(description="The id of sprint (e.g., '10001')")],
    fields: Annotated[
        str,
        Field(
            description=(
                "Comma-separated fields to return in the results. "
                "Use '*all' for all fields, or specify individual "
                "fields like 'summary,status,assignee,priority'"
            ),
            default=",".join(DEFAULT_READ_JIRA_FIELDS),
        ),
    ] = ",".join(DEFAULT_READ_JIRA_FIELDS),
    start_at: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(description="Maximum number of results (1-50)", default=10, ge=1, le=50),
    ] = 10,
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get jira issues from sprint.

    Args:
        ctx: The FastMCP context.
        sprint_id: The ID of the sprint.
        fields: Comma-separated fields to return.
        start_at: Starting index.
        limit: Maximum results.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing the search results including pagination info.
    """
    jira = await get_jira_fetcher(ctx)
    fields_list: str | list[str] | None = fields
    if fields and fields != "*all":
        fields_list = [f.strip() for f in fields.split(",")]

    search_result = jira.get_sprint_issues(
        sprint_id=sprint_id, fields=fields_list, start=start_at, limit=limit
    )
    result = search_result.to_simplified_dict()

    if compact:
        result = ResponseFormatter.compress_search_result(result)

    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Link Types", "readOnlyHint": True},
)
async def get_link_types(ctx: Context) -> str:
    """Get all available issue link types.

    Args:
        ctx: The FastMCP context.

    Returns:
        JSON string representing a list of issue link type objects.
    """
    jira = await get_jira_fetcher(ctx)
    link_types = jira.get_issue_link_types()
    formatted_link_types = [link_type.to_simplified_dict() for link_type in link_types]
    return json.dumps(formatted_link_types, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Issue", "destructiveHint": True},
)
@check_write_access
async def create_issue(
    ctx: Context,
    project_key: Annotated[
        str,
        Field(
            description=(
                "The JIRA project key (e.g. 'PROJ', 'DEV', 'SUPPORT'). "
                "This is the prefix of issue keys in your project. "
                "Never assume what it might be, always ask the user."
            )
        ),
    ],
    summary: Annotated[str, Field(description="Summary/title of the issue")],
    issue_type: Annotated[
        str,
        Field(
            description=(
                "Issue type (e.g. 'Task', 'Bug', 'Story', 'Epic', 'Subtask'). "
                "The available types depend on your project configuration. "
                "For subtasks, use 'Subtask' (not 'Sub-task') and include parent in additional_fields."
            ),
        ),
    ],
    assignee: Annotated[
        str | None,
        Field(
            description="(Optional) Assignee's user identifier (string): Email, display name, or account ID (e.g., 'user@example.com', 'John Doe', 'accountid:...')",
            default=None,
        ),
    ] = None,
    description: Annotated[
        str | None, Field(description="Issue description", default=None)
    ] = None,
    components: Annotated[
        str | None,
        Field(
            description="(Optional) Comma-separated list of component names to assign (e.g., 'Frontend,API')",
            default=None,
        ),
    ] = None,
    additional_fields: Annotated[
        dict[str, Any] | str | None,
        Field(
            description=(
                "REQUIRED for fields not listed above (labels, priority, duedate, etc).\n"
                "Pass as a dictionary. Field names must match Jira API exactly:\n\n"
                "COMMON FIELDS:\n"
                "- Due date: {'duedate': '2025-02-15'}  (use 'duedate' NOT 'due_date')\n"
                "- Labels: {'labels': ['frontend', 'urgent']}\n"
                "- Priority: {'priority': {'name': 'High'}}\n"
                "- Parent: {'parent': {'key': 'PROJ-123'}}\n"
                "- Fix versions: {'fixVersions': [{'name': 'v1.0'}]}\n"
                "- Custom fields: {'customfield_10010': 'value'}\n\n"
                "IMPORTANT: Do NOT pass labels, duedate, priority as top-level parameters.\n"
                "They MUST be inside this additional_fields dict."
            ),
            default=None,
        ),
    ] = None,
    return_mode: Annotated[
        str,
        Field(
            description=(
                "Response size: 'summary' (default — key + url + a few shaped "
                "fields), 'minimal' (key + url + message only), or 'full' "
                "(legacy: complete issue payload). New tickets created via "
                "this tool are small by definition, but consistency with the "
                "other write tools keeps callers' code uniform."
            ),
            default="summary",
        ),
    ] = "summary",
    response_fields: Annotated[
        str | None,
        Field(
            description=(
                "Comma-separated fields to include when return_mode='summary'. "
                "Examples: key,summary,status,assignee,updated"
            ),
            default=None,
        ),
    ] = None,
    force: Annotated[
        bool,
        Field(
            description=(
                "Bypass the duplicate guard. By default, if an issue with the "
                "same summary was created in this project within the last 10 "
                "minutes, the existing key is returned instead of creating a "
                "duplicate. Pass true only when the duplicate is intentional."
            ),
            default=False,
        ),
    ] = False,
) -> str:
    """Create a new Jira issue.

    Duplicate guard: if an identical-summary issue was created in the same
    project within the last 10 minutes, this returns the existing issue's
    key (duplicate_guard=true in the response) instead of creating another.
    This protects against retries after ambiguous responses. Pass force=true
    to create anyway.

    PARAMETER GUIDE:
    - Top-level: project_key, summary, issue_type, assignee, description, components
    - Everything else (labels, duedate, priority, parent, custom fields) goes in additional_fields

    Args:
        ctx: The FastMCP context.
        project_key: The JIRA project key.
        summary: Summary/title of the issue.
        issue_type: Issue type (e.g., 'Task', 'Bug', 'Story', 'Epic', 'Subtask').
        assignee: Assignee's user identifier (string): Email, display name, or account ID (e.g., 'user@example.com', 'John Doe', 'accountid:...').
        description: Issue description.
        components: Comma-separated list of component names.
        additional_fields: Dictionary or JSON string of additional fields.

    Returns:
        JSON string representing the created issue object.

    Raises:
        ValueError: If in read-only mode or Jira client is unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    # Parse components from comma-separated string to list
    components_list = None
    if components and isinstance(components, str):
        components_list = [
            comp.strip() for comp in components.split(",") if comp.strip()
        ]

    # Use additional_fields directly as dict
    # Accept either dict or JSON string for additional fields
    if additional_fields is None:
        extra_fields: dict[str, Any] = {}
    elif isinstance(additional_fields, dict):
        extra_fields = additional_fields
    elif isinstance(additional_fields, str):
        try:
            extra_fields = json.loads(additional_fields)
            if not isinstance(extra_fields, dict):
                raise ValueError(
                    "Parsed additional_fields is not a JSON object (dict)."
                )
        except json.JSONDecodeError as e:
            raise ValueError(f"additional_fields is not valid JSON: {e}") from e
    else:
        raise ValueError("additional_fields must be a dictionary or JSON string.")

    if not force:
        duplicate_key = _find_recent_duplicate(jira, project_key, summary)
        if duplicate_key:
            return _json(
                {
                    "message": (
                        f"Duplicate guard: {duplicate_key} with the same "
                        "summary was created in this project within the last "
                        "10 minutes — NOT creating another. If the earlier "
                        "call appeared to fail, it actually succeeded; use "
                        f"{duplicate_key}. Pass force=true to create a "
                        "duplicate intentionally."
                    ),
                    "key": duplicate_key,
                    "url": _issue_url(jira, duplicate_key),
                    "duplicate_guard": True,
                }
            )

    issue = jira.create_issue(
        project_key=project_key,
        summary=summary,
        issue_type=issue_type,
        description=description,
        assignee=assignee,
        components=components_list,
        **extra_fields,
    )
    return _operation_response(
        jira,
        message="Issue created successfully",
        issue=issue,
        return_mode=return_mode,
        response_fields=response_fields,
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Batch Create Issues", "destructiveHint": True},
)
@check_write_access
async def batch_create_issues(
    ctx: Context,
    issues: Annotated[
        str,
        Field(
            description=(
                "JSON array of issue objects. Each object should contain:\n"
                "- project_key (required): The project key (e.g., 'PROJ')\n"
                "- summary (required): Issue summary/title\n"
                "- issue_type (required): Type of issue (e.g., 'Task', 'Bug')\n"
                "- description (optional): Issue description\n"
                "- assignee (optional): Assignee username or email\n"
                "- components (optional): Array of component names\n"
                "Example: [\n"
                '  {"project_key": "PROJ", "summary": "Issue 1", "issue_type": "Task"},\n'
                '  {"project_key": "PROJ", "summary": "Issue 2", "issue_type": "Bug", "components": ["Frontend"]}\n'
                "]"
            )
        ),
    ],
    validate_only: Annotated[
        bool,
        Field(
            description="If true, only validates the issues without creating them",
            default=False,
        ),
    ] = False,
) -> str:
    """Create multiple Jira issues in a batch.

    Args:
        ctx: The FastMCP context.
        issues: JSON array string of issue objects.
        validate_only: If true, only validates without creating.

    Returns:
        JSON string indicating success and listing created issues (or validation result).

    Raises:
        ValueError: If in read-only mode, Jira client unavailable, or invalid JSON.
    """
    jira = await get_jira_fetcher(ctx)
    # Parse issues from JSON string
    try:
        issues_list = json.loads(issues)
        if not isinstance(issues_list, list):
            raise ValueError("Input 'issues' must be a JSON array string.")
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON in issues")
    except Exception as e:
        raise ValueError(f"Invalid input for issues: {e}") from e

    # Create issues in batch
    created_issues = jira.batch_create_issues(issues_list, validate_only=validate_only)

    message = (
        "Issues validated successfully"
        if validate_only
        else "Issues created successfully"
    )
    result = {
        "message": message,
        "issues": [issue.to_simplified_dict() for issue in created_issues],
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Batch Get Changelogs", "readOnlyHint": True},
)
async def batch_get_changelogs(
    ctx: Context,
    issue_ids_or_keys: Annotated[
        list[str],
        Field(
            description="List of Jira issue IDs or keys, e.g. ['PROJ-123', 'PROJ-124']"
        ),
    ],
    fields: Annotated[
        list[str] | None,
        Field(
            description="(Optional) Filter the changelogs by fields, e.g. ['status', 'assignee']. Default to None for all fields.",
            default=None,
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description=(
                "Maximum number of changelogs to return in result for each issue. "
                "Default to -1 for all changelogs. "
                "Notice that it only limits the results in the response, "
                "the function will still fetch all the data."
            ),
            default=-1,
        ),
    ] = -1,
) -> str:
    """Get changelogs for multiple Jira issues (Cloud only).

    Args:
        ctx: The FastMCP context.
        issue_ids_or_keys: List of issue IDs or keys.
        fields: List of fields to filter changelogs by. None for all fields.
        limit: Maximum changelogs per issue (-1 for all).

    Returns:
        JSON string representing a list of issues with their changelogs.

    Raises:
        NotImplementedError: If run on Jira Server/Data Center.
        ValueError: If Jira client is unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    # Ensure this runs only on Cloud, as per original function docstring
    if not jira.config.is_cloud:
        raise NotImplementedError(
            "Batch get issue changelogs is only available on Jira Cloud."
        )

    # Call the underlying method
    issues_with_changelogs = jira.batch_get_changelogs(
        issue_ids_or_keys=issue_ids_or_keys, fields=fields
    )

    # Format the response
    results = []
    limit_val = None if limit == -1 else limit
    for issue in issues_with_changelogs:
        results.append(
            {
                "issue_id": issue.id,
                "changelogs": [
                    changelog.to_simplified_dict()
                    for changelog in issue.changelogs[:limit_val]
                ],
            }
        )
    return json.dumps(results, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Update Issue", "destructiveHint": True},
)
@check_write_access
async def update_issue(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    fields: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Dictionary of fields to update. For 'assignee', provide a string identifier (email, name, or accountId). "
                "Example: `{'assignee': 'user@example.com', 'summary': 'New Summary'}`"
            )
        ),
    ],
    additional_fields: Annotated[
        dict[str, Any] | None,
        Field(
            description="(Optional) Dictionary of additional fields to update. Use this for custom fields or more complex updates.",
            default=None,
        ),
    ] = None,
    attachments: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) JSON string array or comma-separated list of file paths to attach to the issue. "
                "Example: '/path/to/file1.txt,/path/to/file2.txt' or ['/path/to/file1.txt','/path/to/file2.txt']"
            ),
            default=None,
        ),
    ] = None,
    return_mode: Annotated[
        str,
        Field(
            description=(
                "Response size: 'summary' (default — key + url + a few shaped "
                "fields), 'minimal' (key + url + message only), or 'full' "
                "(legacy: complete issue payload). Big descriptions can blow "
                "past harness token limits on 'full'."
            ),
            default="summary",
        ),
    ] = "summary",
    response_fields: Annotated[
        str | None,
        Field(
            description=(
                "Comma-separated fields to include when return_mode='summary'. "
                "Examples: key,summary,status,assignee,updated"
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Update an existing Jira issue including changing status, adding Epic links, updating fields, etc.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        fields: Dictionary of fields to update.
        additional_fields: Optional dictionary of additional fields.
        attachments: Optional JSON array string or comma-separated list of file paths.
        return_mode: Response payload size — 'summary' (default), 'minimal',
            or 'full'.
        response_fields: Optional comma-separated field allowlist when
            return_mode='summary'.

    Returns:
        JSON string with the shaped operation result (key + url + message,
        plus the issue payload when return_mode != 'minimal'). Attachment
        results are always preserved on the result envelope when present.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable, or invalid input.
    """
    jira = await get_jira_fetcher(ctx)
    # Use fields directly as dict
    if not isinstance(fields, dict):
        raise ValueError("fields must be a dictionary.")
    update_fields = fields

    # Use additional_fields directly as dict
    extra_fields = additional_fields or {}
    if not isinstance(extra_fields, dict):
        raise ValueError("additional_fields must be a dictionary.")

    # Parse attachments
    attachment_paths = []
    if attachments:
        if isinstance(attachments, str):
            try:
                parsed = json.loads(attachments)
                if isinstance(parsed, list):
                    attachment_paths = [str(p) for p in parsed]
                else:
                    raise ValueError("attachments JSON string must be an array.")
            except json.JSONDecodeError:
                # Assume comma-separated if not valid JSON array
                attachment_paths = [
                    p.strip() for p in attachments.split(",") if p.strip()
                ]
        else:
            raise ValueError(
                "attachments must be a JSON array string or comma-separated string."
            )

    # Combine fields and additional_fields
    all_updates = {**update_fields, **extra_fields}
    if attachment_paths:
        all_updates["attachments"] = attachment_paths

    try:
        issue = jira.update_issue(issue_key=issue_key, **all_updates)
        extra: dict[str, Any] | None = None
        if (
            issue is not None
            and hasattr(issue, "custom_fields")
            and "attachment_results" in issue.custom_fields
        ):
            extra = {"attachment_results": issue.custom_fields["attachment_results"]}
        return _operation_response(
            jira,
            message="Issue updated successfully",
            issue=issue,
            issue_key=issue_key,
            return_mode=return_mode,
            response_fields=response_fields,
            extra=extra,
        )
    except Exception as e:
        logger.error(f"Error updating issue {issue_key}: {str(e)}", exc_info=True)
        raise ValueError(f"Failed to update issue {issue_key}: {str(e)}")


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={
        "title": "Assign Issue",
        "destructiveHint": False,
        "idempotentHint": True,
    },
)
@check_write_access
async def assign_issue(
    ctx: Context,
    issue_key: Annotated[
        str, Field(description="Jira issue key (e.g., 'PROJ-123')")
    ],
    assignee: Annotated[
        str,
        Field(
            description=(
                "Assignee identifier — email, displayName, or accountId. "
                "Pass an empty string to unassign. The tool resolves "
                "email/displayName to the correct accountId (Cloud) or "
                "username (Server/DC) before the write."
            )
        ),
    ],
) -> str:
    """Set the assignee on a Jira issue with a minimal response payload.

    Use this instead of ``jira_update_issue`` for assignee-only writes —
    the general update path can silently no-op on assignee in some
    configurations, and the Atlassian-hosted ``editJiraIssue`` echoes
    the entire issue JSON back (which exceeds harness token limits when
    the touched ticket carries a large description).

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        assignee: Email, displayName, or accountId. Empty string unassigns.

    Returns:
        JSON object with shape::

            {
              "success": true,
              "message": "Issue PROJ-123 assignee updated",
              "key": "PROJ-123",
              "url": "https://.../browse/PROJ-123",
              "prior_assignee": "Jack Felke",
              "new_assignee": "Suhrob Ulmasov (Stan)"
            }

    Raises:
        ValueError: If ``issue_key`` is missing, the assignee cannot be
            resolved, in read-only mode, or the Jira client is
            unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    if not issue_key:
        raise ValueError("issue_key is required.")
    # ``assignee`` is allowed to be the empty string (unassign).

    try:
        prior_display, new_display = jira.assign_issue(issue_key, assignee or None)
    except ValueError:
        raise
    except Exception as e:
        logger.error(
            f"Error assigning issue {issue_key} to '{assignee}': {str(e)}",
            exc_info=True,
        )
        raise ValueError(
            f"Failed to assign issue {issue_key}: {str(e)}"
        ) from e

    result = {
        "success": True,
        "message": f"Issue {issue_key} assignee updated",
        "key": issue_key,
        "url": _issue_url(jira, issue_key),
        "prior_assignee": prior_display,
        "new_assignee": new_display,
    }
    return _json(result)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Delete Issue", "destructiveHint": True},
)
@check_write_access
async def delete_issue(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g. PROJ-123)")],
) -> str:
    """Delete an existing Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.

    Returns:
        JSON string indicating success.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    deleted = jira.delete_issue(issue_key)
    result = {"message": f"Issue {issue_key} has been deleted successfully."}
    # The underlying method raises on failure, so if we reach here, it's success.
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Add Comment", "destructiveHint": True},
)
@check_write_access
async def add_comment(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    comment: Annotated[
        str,
        Field(
            description=(
                "Comment body. The Markdown preprocessor converts standard "
                "Markdown to Atlassian Wiki syntax at send time. When format='wiki', "
                "the body is sent as-is. When format='auto' (default), the tool "
                "emits a warning on the response envelope if obvious Markdown "
                "markers are detected — Atlassian Wiki remains the canonical "
                "comment syntax for Jira Cloud."
            )
        ),
    ],
    visibility: Annotated[
        dict[str, str] | None,
        Field(
            description="""(Optional) Comment visibility (e.g. {"type":"group","value":"jira-users"})"""
        ),
    ] = None,
    format: Annotated[
        str,
        Field(
            description=(
                "Comment markup format. 'auto' (default) emits a "
                "rendering-hint warning if Markdown markers are detected. "
                "'wiki' suppresses the check. 'markdown' explicitly opts "
                "into the existing Markdown→Wiki preprocessor."
            ),
            default="auto",
        ),
    ] = "auto",
) -> str:
    """Add a comment to a Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        comment: Comment text.
        visibility: (Optional) Comment visibility (e.g. {"type":"group","value":"jira-users"}).
        format: 'auto' (default) | 'wiki' | 'markdown'. See parameter description.

    Returns:
        JSON string representing the added comment object, plus an optional
        ``warnings`` list when ``format='auto'`` detects Markdown leakage.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    warnings: list[str] = []
    if format == "auto":
        markers: list[str] = []
        if re.search(r"\*\*[^*\n]+\*\*", comment or ""):
            markers.append("**bold** (Wiki uses *bold*)")
        if re.search(r"^```", comment or "", re.M):
            markers.append("``` fenced code (Wiki uses {code}...{code})")
        if re.search(r"^#{1,6} ", comment or "", re.M):
            markers.append("# heading (Wiki uses h1./h2./h3.)")
        if markers:
            warnings.append(
                "Markdown markers detected in comment; Atlassian Wiki is the "
                "canonical comment syntax. Detected: " + ", ".join(markers)
            )

    # add_comment returns dict: {id, body (cleaned), created, author}
    result = jira.add_comment(issue_key, comment, visibility)
    if not isinstance(result, dict):
        envelope: dict[str, Any] = {"comment": result}
        if warnings:
            envelope["warnings"] = warnings
        return json.dumps(envelope, indent=2, ensure_ascii=False)

    body = str(result.get("body") or "")
    comment_id = result.get("id")
    envelope = {
        "success": True,
        "comment_id": comment_id,
        "url": (
            f"{_issue_url(jira, issue_key)}"
            f"?focusedCommentId={comment_id}" if comment_id else _issue_url(jira, issue_key)
        ),
        # Stored-body preview, post Wiki conversion — enough to verify the
        # comment rendered correctly WITHOUT a follow-up jira_get_issue call.
        "body_preview": body[:300] + ("…" if len(body) > 300 else ""),
        "body_chars": len(body),
        "created": result.get("created"),
    }
    if warnings:
        envelope["warnings"] = warnings
    return json.dumps(envelope, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Edit Comment", "destructiveHint": True},
)
@check_write_access
async def edit_comment(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    comment_id: Annotated[str, Field(description="The ID of the comment to edit")],
    comment: Annotated[
        str, Field(description="Updated comment text in Markdown format")
    ],
    visibility: Annotated[
        dict[str, str] | None,
        Field(
            description="""(Optional) Comment visibility (e.g. {"type":"group","value":"jira-users"})"""
        ),
    ] = None,
) -> str:
    """Edit an existing comment on a Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        comment_id: The ID of the comment to edit.
        comment: Updated comment text in Markdown.
        visibility: (Optional) Comment visibility (e.g. {"type":"group","value":"jira-users"}).

    Returns:
        JSON string representing the updated comment object.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    # edit_comment returns dict
    result = jira.edit_comment(issue_key, comment_id, comment, visibility)
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Add Worklog", "destructiveHint": True},
)
@check_write_access
async def add_worklog(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    time_spent: Annotated[
        str,
        Field(
            description=(
                "Time spent in Jira format. Examples: "
                "'1h 30m' (1 hour and 30 minutes), '1d' (1 day), '30m' (30 minutes), '4h' (4 hours)"
            )
        ),
    ],
    comment: Annotated[
        str | None,
        Field(description="(Optional) Comment for the worklog in Markdown format"),
    ] = None,
    started: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Start time in ISO format. If not provided, the current time will be used. "
                "Example: '2023-08-01T12:00:00.000+0000'"
            )
        ),
    ] = None,
    # Add original_estimate and remaining_estimate as per original tool
    original_estimate: Annotated[
        str | None, Field(description="(Optional) New value for the original estimate")
    ] = None,
    remaining_estimate: Annotated[
        str | None, Field(description="(Optional) New value for the remaining estimate")
    ] = None,
) -> str:
    """Add a worklog entry to a Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        time_spent: Time spent in Jira format.
        comment: Optional comment in Markdown.
        started: Optional start time in ISO format.
        original_estimate: Optional new original estimate.
        remaining_estimate: Optional new remaining estimate.


    Returns:
        JSON string representing the added worklog object.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    # add_worklog returns dict
    worklog_result = jira.add_worklog(
        issue_key=issue_key,
        time_spent=time_spent,
        comment=comment,
        started=started,
        original_estimate=original_estimate,
        remaining_estimate=remaining_estimate,
    )
    result = {"message": "Worklog added successfully", "worklog": worklog_result}
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Link to Epic", "destructiveHint": True},
)
@check_write_access
async def link_to_epic(
    ctx: Context,
    issue_key: Annotated[
        str, Field(description="The key of the issue to link (e.g., 'PROJ-123')")
    ],
    epic_key: Annotated[
        str, Field(description="The key of the epic to link to (e.g., 'PROJ-456')")
    ],
    return_mode: Annotated[
        str,
        Field(
            description=(
                "Response size: 'summary' (default — key + url + a few shaped "
                "fields), 'minimal' (key + url + message only), or 'full' "
                "(legacy: complete issue payload)."
            ),
            default="summary",
        ),
    ] = "summary",
    response_fields: Annotated[
        str | None,
        Field(
            description=(
                "Comma-separated fields to include when return_mode='summary'. "
                "Examples: key,summary,status,assignee,updated"
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Link an existing issue to an epic.

    Args:
        ctx: The FastMCP context.
        issue_key: The key of the issue to link.
        epic_key: The key of the epic to link to.
        return_mode: Response payload size — 'summary' (default), 'minimal',
            or 'full'.
        response_fields: Optional comma-separated field allowlist when
            return_mode='summary'.

    Returns:
        JSON string with the shaped operation result.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    issue = jira.link_issue_to_epic(issue_key, epic_key)
    return _operation_response(
        jira,
        message=f"Issue {issue_key} has been linked to epic {epic_key}.",
        issue=issue,
        issue_key=issue_key,
        return_mode=return_mode,
        response_fields=response_fields,
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Issue Link", "destructiveHint": True},
)
@check_write_access
async def create_issue_link(
    ctx: Context,
    link_type: Annotated[
        str,
        Field(
            description="The type of link to create (e.g., 'Duplicate', 'Blocks', 'Relates to')"
        ),
    ],
    inward_issue_key: Annotated[
        str, Field(description="The key of the inward issue (e.g., 'PROJ-123')")
    ],
    outward_issue_key: Annotated[
        str, Field(description="The key of the outward issue (e.g., 'PROJ-456')")
    ],
    comment: Annotated[
        str | None, Field(description="(Optional) Comment to add to the link")
    ] = None,
    comment_visibility: Annotated[
        dict[str, str] | None,
        Field(
            description="(Optional) Visibility settings for the comment (e.g., {'type': 'group', 'value': 'jira-users'})",
            default=None,
        ),
    ] = None,
) -> str:
    """Create a link between two Jira issues.

    Args:
        ctx: The FastMCP context.
        link_type: The type of link (e.g., 'Blocks').
        inward_issue_key: The key of the source issue.
        outward_issue_key: The key of the target issue.
        comment: Optional comment text.
        comment_visibility: Optional dictionary for comment visibility.

    Returns:
        JSON string indicating success or failure.

    Raises:
        ValueError: If required fields are missing, invalid input, in read-only mode, or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    if not all([link_type, inward_issue_key, outward_issue_key]):
        raise ValueError(
            "link_type, inward_issue_key, and outward_issue_key are required."
        )

    link_data = {
        "type": {"name": link_type},
        "inwardIssue": {"key": inward_issue_key},
        "outwardIssue": {"key": outward_issue_key},
    }

    if comment:
        comment_obj = {"body": comment}
        if comment_visibility and isinstance(comment_visibility, dict):
            if "type" in comment_visibility and "value" in comment_visibility:
                comment_obj["visibility"] = comment_visibility
            else:
                logger.warning("Invalid comment_visibility dictionary structure.")
        link_data["comment"] = comment_obj

    result = jira.create_issue_link(link_data)
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Remote Issue Link", "destructiveHint": True},
)
@check_write_access
async def create_remote_issue_link(
    ctx: Context,
    issue_key: Annotated[
        str,
        Field(description="The key of the issue to add the link to (e.g., 'PROJ-123')"),
    ],
    url: Annotated[
        str,
        Field(
            description="The URL to link to (e.g., 'https://example.com/page' or Confluence page URL)"
        ),
    ],
    title: Annotated[
        str,
        Field(
            description="The title/name of the link (e.g., 'Documentation Page', 'Confluence Page')"
        ),
    ],
    summary: Annotated[
        str | None, Field(description="(Optional) Description of the link")
    ] = None,
    relationship: Annotated[
        str | None,
        Field(
            description="(Optional) Relationship description (e.g., 'causes', 'relates to', 'documentation')"
        ),
    ] = None,
    icon_url: Annotated[
        str | None, Field(description="(Optional) URL to a 16x16 icon for the link")
    ] = None,
) -> str:
    """Create a remote issue link (web link or Confluence link) for a Jira issue.

    This tool allows you to add web links and Confluence links to Jira issues.
    The links will appear in the issue's "Links" section and can be clicked to navigate to external resources.

    Args:
        ctx: The FastMCP context.
        issue_key: The key of the issue to add the link to.
        url: The URL to link to (can be any web page or Confluence page).
        title: The title/name that will be displayed for the link.
        summary: Optional description of what the link is for.
        relationship: Optional relationship description.
        icon_url: Optional URL to a 16x16 icon for the link.

    Returns:
        JSON string indicating success or failure.

    Raises:
        ValueError: If required fields are missing, invalid input, in read-only mode, or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    if not issue_key:
        raise ValueError("issue_key is required.")
    if not url:
        raise ValueError("url is required.")
    if not title:
        raise ValueError("title is required.")

    # Build the remote link data structure
    link_object = {
        "url": url,
        "title": title,
    }

    if summary:
        link_object["summary"] = summary

    if icon_url:
        link_object["icon"] = {"url16x16": icon_url, "title": title}

    link_data = {"object": link_object}

    if relationship:
        link_data["relationship"] = relationship

    result = jira.create_remote_issue_link(issue_key, link_data)
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Remove Issue Link", "destructiveHint": True},
)
@check_write_access
async def remove_issue_link(
    ctx: Context,
    link_id: Annotated[str, Field(description="The ID of the link to remove")],
) -> str:
    """Remove a link between two Jira issues.

    Args:
        ctx: The FastMCP context.
        link_id: The ID of the link to remove.

    Returns:
        JSON string indicating success.

    Raises:
        ValueError: If link_id is missing, in read-only mode, or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    if not link_id:
        raise ValueError("link_id is required")

    result = jira.remove_issue_link(link_id)  # Returns dict on success
    return json.dumps(result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Transition Issue", "destructiveHint": True},
)
@check_write_access
async def transition_issue(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    transition_id: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) ID of the transition to perform (e.g. '41'). "
                "Prefer status_name instead — it resolves the id server-side, "
                "so a prior jira_get_transitions call is NOT needed."
            ),
            default=None,
        ),
    ] = None,
    status_name: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Target status by name, e.g. 'Ready for QA' or "
                "'In Progress'. Case-insensitive; resolved server-side against "
                "the issue's available transitions. Provide this OR "
                "transition_id. On no match the error lists every valid name."
            ),
            default=None,
        ),
    ] = None,
    fields: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "(Optional) Dictionary of fields to update during the transition. "
                "Some transitions require specific fields to be set (e.g., resolution). "
                "Example: {'resolution': {'name': 'Fixed'}}"
            ),
            default=None,
        ),
    ] = None,
    comment: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Comment to add during the transition. "
                "This will be visible in the issue history."
            ),
        ),
    ] = None,
    return_mode: Annotated[
        str,
        Field(
            description=(
                "Response size: 'summary' (default — key + url + a few shaped "
                "fields), 'minimal' (key + url + message only), or 'full' "
                "(legacy: complete issue payload). Big descriptions can blow "
                "past harness token limits on 'full'."
            ),
            default="summary",
        ),
    ] = "summary",
    response_fields: Annotated[
        str | None,
        Field(
            description=(
                "Comma-separated fields to include when return_mode='summary'. "
                "Examples: key,summary,status,assignee,updated"
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Transition a Jira issue to a new status.

    Accepts either a target status name (preferred — resolved server-side,
    no jira_get_transitions round-trip needed) or a raw transition id.
    The response includes ``next_transitions`` (the moves valid from the
    new status), so a follow-up jira_get_transitions call is unnecessary.
    For many issues through the same status, use jira_batch_transition.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        transition_id: Optional ID of the transition.
        status_name: Optional target status name (case-insensitive).
        fields: Optional dictionary of fields to update during transition.
        comment: Optional comment for the transition.
        return_mode: Response payload size — 'summary' (default), 'minimal',
            or 'full'.
        response_fields: Optional comma-separated field allowlist when
            return_mode='summary'.

    Returns:
        JSON string with the shaped operation result (key + url + message +
        next_transitions, plus the issue payload when return_mode != 'minimal').

    Raises:
        ValueError: If required fields missing, invalid input, in read-only mode, or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    if not issue_key:
        raise ValueError("issue_key is required.")
    if not transition_id and not status_name:
        raise ValueError(
            "Provide status_name (e.g. 'Ready for QA') or transition_id."
        )
    if not transition_id:
        transition_id = _resolve_transition_id(jira, issue_key, status_name)

    # Use fields directly as dict
    update_fields = fields or {}
    if not isinstance(update_fields, dict):
        raise ValueError("fields must be a dictionary.")

    issue = jira.transition_issue(
        issue_key=issue_key,
        transition_id=transition_id,
        fields=update_fields,
        comment=comment,
    )

    return _operation_response(
        jira,
        message=f"Issue {issue_key} transitioned successfully",
        issue=issue,
        issue_key=issue_key,
        return_mode=return_mode,
        response_fields=response_fields,
        extra={"next_transitions": _next_transitions(jira, issue_key)},
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Batch Transition", "destructiveHint": True},
)
@check_write_access
async def batch_transition(
    ctx: Context,
    keys: Annotated[
        str,
        Field(description="Comma-separated Jira issue keys."),
    ],
    transition_id: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) ID of the transition to perform on every key. "
                "Prefer status_name — ids vary per workflow; the name is "
                "resolved per key server-side."
            ),
            default=None,
        ),
    ] = None,
    status_name: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Target status by name (e.g. 'Ready for QA'), "
                "resolved per key. Provide this OR transition_id."
            ),
            default=None,
        ),
    ] = None,
    comment: Annotated[
        str | None,
        Field(
            description="(Optional) Comment to add to every transitioned issue.",
            default=None,
        ),
    ] = None,
) -> str:
    """Transition many Jira issues to the same status in one call.

    Accepts a status name (preferred; resolved per key, so mixed workflows
    work) or a raw transition id applied verbatim to every key. Failures on
    one key do not abort the others — the caller sees the full batch outcome
    and can retry the individual failures.

    Args:
        ctx: The FastMCP context.
        keys: Comma-separated Jira issue keys.
        transition_id: Optional transition id to apply to every key.
        status_name: Optional target status name, resolved per key.
        comment: Optional comment text emitted on each transition.

    Returns:
        JSON object: ``{target, summary: {ok, fail, total}, results: [...]}``.
    """
    jira = await get_jira_fetcher(ctx)
    key_list = _parse_csv(keys) or []
    if not key_list:
        raise ValueError("keys is required (comma-separated Jira issue keys).")
    if not transition_id and not status_name:
        raise ValueError(
            "Provide status_name (e.g. 'Ready for QA') or transition_id."
        )

    results: list[dict[str, Any]] = []
    ok = 0
    fail = 0
    for key in key_list:
        try:
            resolved_id = transition_id or _resolve_transition_id(
                jira, key, status_name
            )
            jira.transition_issue(
                issue_key=key,
                transition_id=resolved_id,
                fields={},
                comment=comment,
            )
            results.append({"key": key, "success": True})
            ok += 1
        except Exception as e:
            results.append({"key": key, "success": False, "error": str(e)})
            fail += 1
            logger.warning(f"batch_transition: {key} failed: {e}")

    return _json(
        {
            "target": status_name or transition_id,
            "summary": {"ok": ok, "fail": fail, "total": len(key_list)},
            "results": results,
        }
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={
        "title": "PR Handoff",
        "destructiveHint": True,
        "idempotentHint": True,
    },
)
@check_write_access
async def pr_handoff(
    ctx: Context,
    issue_key: Annotated[
        str, Field(description="Jira issue key (e.g., 'DS-12704').")
    ],
    pr_url: Annotated[
        str,
        Field(
            description="The GitHub PR URL to attach as a remote link on the issue."
        ),
    ],
    pr_title: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) PR title to use for the remote-link label. "
                "Defaults to the URL itself if omitted."
            ),
            default=None,
        ),
    ] = None,
    transition_id: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Transition ID to apply. If omitted, the status "
                "is left unchanged — useful when the ticket is already in "
                "the target state."
            ),
            default=None,
        ),
    ] = None,
    assignee: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Assignee identifier (email, displayName, or "
                "accountId). If omitted, assignee is left unchanged."
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Atomic post-PR-approval handoff: transition + assign + remote link.

    Wraps the three-call pattern (transition_issue → assign_issue →
    create_remote_issue_link) into a single tool call with a minimal
    response. Idempotent on each leg — re-running on an already-handed-off
    ticket re-applies the same transitions (where allowed), re-asserts the
    assignment, and treats a duplicate-link error as a non-failure.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key.
        pr_url: GitHub PR URL to link.
        pr_title: Optional label for the remote link.
        transition_id: Optional transition to apply.
        assignee: Optional assignee identifier.

    Returns:
        JSON envelope with per-leg outcomes::

            {
              "success": true,
              "key": "DS-12704",
              "url": "...",
              "transition": {"applied": true, "transition_id": "41"} | null,
              "assignee": {"prior": "...", "new": "..."} | null,
              "link": {"added": true, "title": "PR #28 — ..."} | {"added": false, "reason": "duplicate"}
            }
    """
    jira = await get_jira_fetcher(ctx)
    if not issue_key:
        raise ValueError("issue_key is required.")
    if not pr_url:
        raise ValueError("pr_url is required.")

    out: dict[str, Any] = {
        "success": True,
        "key": issue_key,
        "url": _issue_url(jira, issue_key),
        "transition": None,
        "assignee": None,
        "link": None,
    }

    # 1. Transition (if requested)
    if transition_id:
        try:
            jira.transition_issue(
                issue_key=issue_key,
                transition_id=transition_id,
                fields={},
                comment=None,
            )
            out["transition"] = {
                "applied": True,
                "transition_id": transition_id,
            }
        except Exception as e:
            out["transition"] = {
                "applied": False,
                "transition_id": transition_id,
                "error": str(e),
            }
            out["success"] = False
            logger.warning(
                f"pr_handoff {issue_key}: transition failed: {e}"
            )

    # 2. Assignee (if requested)
    if assignee is not None:
        try:
            prior, new = jira.assign_issue(issue_key, assignee or None)
            out["assignee"] = {"prior": prior, "new": new}
        except Exception as e:
            out["assignee"] = {"error": str(e)}
            out["success"] = False
            logger.warning(f"pr_handoff {issue_key}: assign failed: {e}")

    # 3. Remote link
    label = pr_title or pr_url
    try:
        jira.create_remote_issue_link(
            issue_key,
            {"object": {"url": pr_url, "title": label}},
        )
        out["link"] = {"added": True, "title": label}
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "duplicate" in msg or "exists" in msg:
            out["link"] = {
                "added": False,
                "reason": "duplicate",
                "title": label,
            }
        else:
            out["link"] = {"added": False, "error": str(e)}
            out["success"] = False
            logger.warning(f"pr_handoff {issue_key}: link failed: {e}")

    return _json(out)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Sprint", "destructiveHint": True},
)
@check_write_access
async def create_sprint(
    ctx: Context,
    board_id: Annotated[str, Field(description="The id of board (e.g., '1000')")],
    sprint_name: Annotated[
        str, Field(description="Name of the sprint (e.g., 'Sprint 1')")
    ],
    start_date: Annotated[
        str, Field(description="Start time for sprint (ISO 8601 format)")
    ],
    end_date: Annotated[
        str, Field(description="End time for sprint (ISO 8601 format)")
    ],
    goal: Annotated[
        str | None, Field(description="(Optional) Goal of the sprint")
    ] = None,
) -> str:
    """Create Jira sprint for a board.

    Args:
        ctx: The FastMCP context.
        board_id: Board ID.
        sprint_name: Sprint name.
        start_date: Start date (ISO format).
        end_date: End date (ISO format).
        goal: Optional sprint goal.

    Returns:
        JSON string representing the created sprint object.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    sprint = jira.create_sprint(
        board_id=board_id,
        sprint_name=sprint_name,
        start_date=start_date,
        end_date=end_date,
        goal=goal,
    )
    return json.dumps(sprint.to_simplified_dict(), indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Update Sprint", "destructiveHint": True},
)
@check_write_access
async def update_sprint(
    ctx: Context,
    sprint_id: Annotated[str, Field(description="The id of sprint (e.g., '10001')")],
    sprint_name: Annotated[
        str | None, Field(description="(Optional) New name for the sprint")
    ] = None,
    state: Annotated[
        str | None,
        Field(description="(Optional) New state for the sprint (future|active|closed)"),
    ] = None,
    start_date: Annotated[
        str | None, Field(description="(Optional) New start date for the sprint")
    ] = None,
    end_date: Annotated[
        str | None, Field(description="(Optional) New end date for the sprint")
    ] = None,
    goal: Annotated[
        str | None, Field(description="(Optional) New goal for the sprint")
    ] = None,
) -> str:
    """Update jira sprint.

    Args:
        ctx: The FastMCP context.
        sprint_id: The ID of the sprint.
        sprint_name: Optional new name.
        state: Optional new state (future|active|closed).
        start_date: Optional new start date.
        end_date: Optional new end date.
        goal: Optional new goal.

    Returns:
        JSON string representing the updated sprint object or an error message.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    sprint = jira.update_sprint(
        sprint_id=sprint_id,
        sprint_name=sprint_name,
        state=state,
        start_date=start_date,
        end_date=end_date,
        goal=goal,
    )

    if sprint is None:
        error_payload = {
            "error": f"Failed to update sprint {sprint_id}. Check logs for details."
        }
        return json.dumps(error_payload, indent=2, ensure_ascii=False)
    else:
        return json.dumps(sprint.to_simplified_dict(), indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get Project Versions", "readOnlyHint": True},
)
async def get_project_versions(
    ctx: Context,
    project_key: Annotated[str, Field(description="Jira project key (e.g., 'PROJ')")],
) -> str:
    """Get all fix versions for a specific Jira project."""
    jira = await get_jira_fetcher(ctx)
    versions = jira.get_project_versions(project_key)
    return json.dumps(versions, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Get All Projects", "readOnlyHint": True},
)
async def get_all_projects(
    ctx: Context,
    include_archived: Annotated[
        bool,
        Field(
            description="Whether to include archived projects in the results",
            default=False,
        ),
    ] = False,
    compact: Annotated[
        bool,
        Field(
            description="If true (default), returns compressed response with only key, name, type.",
            default=True,
        ),
    ] = True,
) -> str:
    """Get all Jira projects accessible to the current user.

    Args:
        ctx: The FastMCP context.
        include_archived: Whether to include archived projects.
        compact: If true, compress response for reduced context usage.

    Returns:
        JSON string representing a list of project objects accessible to the user.
        Project keys are always returned in uppercase.
        If JIRA_PROJECTS_FILTER is configured, only returns projects matching those keys.

    Raises:
        ValueError: If the Jira client is not configured or available.
    """
    try:
        jira = await get_jira_fetcher(ctx)
        projects = jira.get_all_projects(include_archived=include_archived)
    except (MCPAtlassianAuthenticationError, HTTPError, OSError, ValueError) as e:
        error_message = ""
        log_level = logging.ERROR
        if isinstance(e, MCPAtlassianAuthenticationError):
            error_message = f"Authentication/Permission Error: {str(e)}"
        elif isinstance(e, OSError | HTTPError):
            error_message = f"Network or API Error: {str(e)}"
        elif isinstance(e, ValueError):
            error_message = f"Configuration Error: {str(e)}"

        error_result = {
            "success": False,
            "error": error_message,
        }
        logger.log(log_level, f"get_all_projects failed: {error_message}")
        return json.dumps(error_result, indent=2, ensure_ascii=False)

    # Ensure all project keys are uppercase
    for project in projects:
        if "key" in project:
            project["key"] = project["key"].upper()

    # Apply project filter if configured
    if jira.config.projects_filter:
        # Split projects filter by commas and handle possible whitespace
        allowed_project_keys = {
            p.strip().upper() for p in jira.config.projects_filter.split(",")
        }
        projects = [
            project
            for project in projects
            if project.get("key") in allowed_project_keys
        ]

    if compact:
        projects = ResponseFormatter.compress_projects(projects)

    return json.dumps(projects, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Version", "destructiveHint": True},
)
@check_write_access
async def create_version(
    ctx: Context,
    project_key: Annotated[str, Field(description="Jira project key (e.g., 'PROJ')")],
    name: Annotated[str, Field(description="Name of the version")],
    start_date: Annotated[
        str | None, Field(description="Start date (YYYY-MM-DD)", default=None)
    ] = None,
    release_date: Annotated[
        str | None, Field(description="Release date (YYYY-MM-DD)", default=None)
    ] = None,
    description: Annotated[
        str | None, Field(description="Description of the version", default=None)
    ] = None,
) -> str:
    """Create a new fix version in a Jira project.

    Args:
        ctx: The FastMCP context.
        project_key: The project key.
        name: Name of the version.
        start_date: Start date (optional).
        release_date: Release date (optional).
        description: Description (optional).

    Returns:
        JSON string of the created version object.
    """
    jira = await get_jira_fetcher(ctx)
    try:
        version = jira.create_project_version(
            project_key=project_key,
            name=name,
            start_date=start_date,
            release_date=release_date,
            description=description,
        )
        return json.dumps(version, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(
            f"Error creating version in project {project_key}: {str(e)}", exc_info=True
        )
        return json.dumps(
            {"success": False, "error": str(e)}, indent=2, ensure_ascii=False
        )


@jira_mcp.tool(
    name="batch_create_versions",
    tags={"jira", "write"},
    annotations={"title": "Batch Create Versions", "destructiveHint": True},
)
@check_write_access
async def batch_create_versions(
    ctx: Context,
    project_key: Annotated[str, Field(description="Jira project key (e.g., 'PROJ')")],
    versions: Annotated[
        str,
        Field(
            description=(
                "JSON array of version objects. Each object should contain:\n"
                "- name (required): Name of the version\n"
                "- startDate (optional): Start date (YYYY-MM-DD)\n"
                "- releaseDate (optional): Release date (YYYY-MM-DD)\n"
                "- description (optional): Description of the version\n"
                "Example: [\n"
                '  {"name": "v1.0", "startDate": "2025-01-01", "releaseDate": "2025-02-01", "description": "First release"},\n'
                '  {"name": "v2.0"}\n'
                "]"
            )
        ),
    ],
) -> str:
    """Batch create multiple versions in a Jira project.

    Args:
        ctx: The FastMCP context.
        project_key: The project key.
        versions: JSON array string of version objects.

    Returns:
        JSON array of results, each with success flag, version or error.
    """
    jira = await get_jira_fetcher(ctx)
    try:
        version_list = json.loads(versions)
        if not isinstance(version_list, list):
            raise ValueError("Input 'versions' must be a JSON array string.")
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON in versions")
    except Exception as e:
        raise ValueError(f"Invalid input for versions: {e}") from e

    results = []
    if not version_list:
        return json.dumps(results, indent=2, ensure_ascii=False)

    for idx, v in enumerate(version_list):
        # Defensive: ensure v is a dict and has a name
        if not isinstance(v, dict) or not v.get("name"):
            results.append(
                {
                    "success": False,
                    "error": f"Item {idx}: Each version must be an object with at least a 'name' field.",
                }
            )
            continue
        try:
            version = jira.create_project_version(
                project_key=project_key,
                name=v["name"],
                start_date=v.get("startDate"),
                release_date=v.get("releaseDate"),
                description=v.get("description"),
            )
            results.append({"success": True, "version": version})
        except Exception as e:
            logger.error(
                f"Error creating version in batch for project {project_key}: {str(e)}",
                exc_info=True,
            )
            results.append({"success": False, "error": str(e), "input": v})
    return json.dumps(results, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read", "metrics"},
    annotations={"title": "Get Issue Dates", "readOnlyHint": True},
)
async def jira_get_issue_dates(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    include_status_changes: Annotated[
        bool,
        Field(
            description="Include status change history with timestamps and durations"
        ),
    ] = True,
    include_status_summary: Annotated[
        bool,
        Field(description="Include aggregated time spent in each status"),
    ] = True,
) -> str:
    """
    Get date information and status transition history for a Jira issue.

    Returns dates (created, updated, due date, resolution date) and optionally
    status change history with time tracking for workflow analysis.

    Args:
        ctx: The FastMCP context.
        issue_key: The Jira issue key.
        include_status_changes: Whether to include status change history.
        include_status_summary: Whether to include aggregated time per status.

    Returns:
        JSON string with issue dates and optional status tracking data.
    """
    jira = await get_jira_fetcher(ctx)
    try:
        result = jira.get_issue_dates(
            issue_key=issue_key,
            include_created=True,
            include_updated=True,
            include_due_date=True,
            include_resolution_date=True,
            include_status_changes=include_status_changes,
            include_status_summary=include_status_summary,
        )
        return json.dumps(result.to_simplified_dict(), indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error getting issue dates for {issue_key}: {str(e)}")
        error_result = {"success": False, "error": str(e), "issue_key": issue_key}
        return json.dumps(error_result, indent=2, ensure_ascii=False)


@jira_mcp.tool(
    tags={"jira", "read", "metrics", "sla"},
    annotations={"title": "Get Issue SLA", "readOnlyHint": True},
)
async def jira_get_issue_sla(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    metrics: Annotated[
        str | None,
        Field(
            description=(
                "Comma-separated list of SLA metrics to calculate. "
                "Available: cycle_time, lead_time, time_in_status, due_date_compliance, "
                "resolution_time, first_response_time. "
                "Defaults to configured metrics or 'cycle_time,time_in_status'."
            )
        ),
    ] = None,
    working_hours_only: Annotated[
        bool | None,
        Field(
            description=(
                "Calculate using working hours only (excludes weekends/non-business hours). "
                "Defaults to value from JIRA_SLA_WORKING_HOURS_ONLY environment variable."
            )
        ),
    ] = None,
    include_raw_dates: Annotated[
        bool,
        Field(description="Include raw date values in the response"),
    ] = False,
) -> str:
    """
    Calculate SLA metrics for a Jira issue.

    Computes various time-based metrics including cycle time, lead time,
    time spent in each status, due date compliance, and more.

    Working hours can be configured via environment variables:
    - JIRA_SLA_WORKING_HOURS_ONLY: Enable working hours filtering (true/false)
    - JIRA_SLA_WORKING_HOURS_START: Start time (e.g., "09:00")
    - JIRA_SLA_WORKING_HOURS_END: End time (e.g., "17:00")
    - JIRA_SLA_WORKING_DAYS: Working days (e.g., "1,2,3,4,5" for Mon-Fri)
    - JIRA_SLA_TIMEZONE: Timezone for calculations (e.g., "America/New_York")

    Args:
        ctx: The FastMCP context.
        issue_key: The Jira issue key.
        metrics: Comma-separated list of metrics to calculate.
        working_hours_only: Use working hours only for calculations.
        include_raw_dates: Include raw date values in response.

    Returns:
        JSON string with calculated SLA metrics.
    """
    jira = await get_jira_fetcher(ctx)
    try:
        # Parse metrics from comma-separated string
        metrics_list = None
        if metrics:
            metrics_list = [m.strip() for m in metrics.split(",") if m.strip()]

        result = jira.get_issue_sla(
            issue_key=issue_key,
            metrics=metrics_list,
            working_hours_only=working_hours_only,
            include_raw_dates=include_raw_dates,
        )
        return json.dumps(result.to_simplified_dict(), indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error calculating SLA for {issue_key}: {str(e)}")
        error_result = {"success": False, "error": str(e), "issue_key": issue_key}
        return json.dumps(error_result, indent=2, ensure_ascii=False)


# Import vector tools to register them on jira_mcp
# This must be at the end to avoid circular imports
try:
    from mcp_atlassian.servers import vector_tools  # noqa: F401

    logger.debug("Vector search tools registered successfully")
except ImportError as e:
    logger.debug(f"Vector search tools not available: {e}")
