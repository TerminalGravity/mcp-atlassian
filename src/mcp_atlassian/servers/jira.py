"""Jira FastMCP server instance and tool definitions."""

import json
import logging
import re
from typing import Annotated, Any, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from mcp_atlassian.jira.constants import DEFAULT_READ_JIRA_FIELDS
from mcp_atlassian.jira.response_formatter import ResponseFormatter
from mcp_atlassian.servers.dependencies import get_jira_fetcher
from mcp_atlassian.utils.decorators import check_write_access, require_write_access

logger = logging.getLogger(__name__)

jira_mcp = FastMCP(
    name="Jira MCP Service",
    instructions="Provides tools for interacting with Atlassian Jira.",
)


SUMMARY_FIELDS = ["summary", "status", "priority", "assignee", "issuetype", "updated"]


def _json(data: Any) -> Any:
    # Tools return STRUCTURED content (dicts), not pre-stringified JSON.
    # FastMCP serializes a dict return into structuredContent natively, so the
    # Claude Code TUI renders it as a nested, readable object. Returning a JSON
    # *string* instead makes FastMCP wrap it as {"result": "<escaped JSON>"},
    # which renders as an unreadable wall of \n and \" escapes. This helper is
    # now an identity passthrough kept at every return site to preserve the
    # single, intentional "this is the tool result" boundary.
    return data


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _norm_key_param(primary: str | None, *aliases: str | None) -> str | None:
    """Return the first non-empty value — lets a tool accept any of several
    parameter spellings for the same concept (kills keys/issue_key friction)."""
    for v in (primary, *aliases):
        if v:
            return v
    return None


# Verbosity has two historical spellings across the surface: jira_get speaks
# 'response_format' (summary|full); the write tools speak 'return_mode'
# (summary|minimal|full). Each tool keeps its own canonical spelling but ALSO
# accepts the other as an alias so an agent never has to remember which is
# which. 'minimal' has no analogue on the summary|full axis, so it folds to
# 'summary' when mapped onto a response_format target.
_VERBOSITY_RETURN_MODE = {"summary", "minimal", "full"}
_VERBOSITY_RESPONSE_FORMAT = {"summary", "full"}


def _norm_return_mode(return_mode: str | None, response_format: str | None) -> str:
    """Canonical verbosity for write tools (return_mode axis: summary|minimal|full).

    Accepts a 'response_format' alias and validates the result so a bogus value
    fails loudly rather than silently degrading.
    """
    value = _norm_key_param(return_mode, response_format) or "summary"
    if value not in _VERBOSITY_RETURN_MODE:
        raise ValueError(
            f"Invalid return_mode '{value}'. "
            f"Valid: {sorted(_VERBOSITY_RETURN_MODE)} "
            "(response_format is accepted as an alias)."
        )
    return value


def _norm_response_format(response_format: str | None, return_mode: str | None) -> str:
    """Canonical verbosity for jira_get (response_format axis: summary|full).

    Accepts a 'return_mode' alias; 'minimal' folds to 'summary' since the
    read path only distinguishes summary vs full.
    """
    value = _norm_key_param(response_format, return_mode) or "summary"
    if value == "minimal":
        value = "summary"
    if value not in _VERBOSITY_RESPONSE_FORMAT:
        raise ValueError(
            f"Invalid response_format '{value}'. "
            f"Valid: {sorted(_VERBOSITY_RESPONSE_FORMAT)} "
            "(return_mode is accepted as an alias; 'minimal' maps to 'summary')."
        )
    return value


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
) -> dict[str, Any]:
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
                # Only adopt the shaped key when it's a usable string —
                # mocks/garbage from shaping must never displace the
                # caller-supplied issue_key (B2: the fallback envelope
                # below must always be serializable).
                shaped_key = shaped.get("key")
                key = shaped_key if isinstance(shaped_key, str) and shaped_key else key
                result["issue"] = shaped
    except Exception as e:
        logger.warning(f"_operation_response: shaping failed, degrading: {e}")
        result["response_shaping_error"] = str(e)
        if issue is not None and key is None:
            issue_attr_key = getattr(issue, "key", None)
            key = issue_attr_key if isinstance(issue_attr_key, str) else None
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
        return {
            "message": message,
            "key": key
            if isinstance(key, str)
            else (str(key) if key is not None else None),
            "serialization_error": str(e),
        }


def _find_transition(
    transitions: list[dict[str, Any]], target_status: str
) -> dict[str, Any] | None:
    target = target_status.casefold()
    for transition in transitions:
        if str(transition.get("to_status", "")).casefold() == target:
            return transition
        to_data = transition.get("to")
        if (
            isinstance(to_data, dict)
            and str(to_data.get("name", "")).casefold() == target
        ):
            return transition
    for transition in transitions:
        if str(transition.get("name", "")).casefold() == target:
            return transition
    return None


def _resolve_transition_id(jira: Any, issue_key: str, status_name: str) -> str:
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
            "Retry with one of those names as the target status name, or "
            "pass the id as transition_id."
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


def _find_recent_duplicate(jira: Any, project_key: str, summary: str) -> str | None:
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
                raw.get("summary") or (raw.get("fields") or {}).get("summary") or ""
            )
            if candidate.strip().casefold() == target:
                return raw.get("key")
    except Exception as e:
        logger.warning(f"create_issue duplicate guard skipped: {e}")
    return None


def _project_issue_type_names(jira: Any, project_key: str) -> list[str]:
    """Best-effort list of creatable issue-type names for a project. Returns
    [] if it can't be determined (never raises). Only called when a create
    actually fails, so the happy path pays no extra round-trip."""
    try:
        issue_types = jira.get_project_issue_types(project_key)
        return [
            str(it.get("name"))
            for it in (issue_types or [])
            if isinstance(it, dict) and it.get("name")
        ]
    except Exception as e:
        logger.warning(f"create_issue issue-type lookup skipped: {e}")
        return []


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
                "created": ResponseFormatter.relative_timestamp(c.get("created")),
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
        str | None,
        Field(
            description=(
                "Canonical verbosity param. 'summary' (default, ~1 KB/issue: "
                "triage fields + truncated description + latest 2 comments "
                "truncated) or 'full' (complete description and all fetched "
                "comments). summary answers status/assignee/triage questions — "
                "request full only when you need complete text. (Alias: "
                "return_mode is also accepted; 'minimal' maps to 'summary'.)"
            ),
            default=None,
        ),
    ] = None,
    return_mode: Annotated[
        str | None,
        Field(
            description="(Alias for response_format; 'minimal' maps to 'summary'.)",
            default=None,
        ),
    ] = None,
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
        Field(
            description="Max comments fetched per issue (0 = none)",
            default=10,
            ge=0,
            le=100,
        ),
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
) -> dict:
    """Get one or many Jira issues in a token-budgeted form.

    Replaces get_issue / get_issue_summary / quick_status / batch_get_changelogs /
    get_issue_dates / get_issue_sla. For finding issues by query, use jira_find.
    Re-fetching with summary format is cheap — don't hoard full payloads.

    Verbosity is ``response_format`` (summary|full, canonical); ``return_mode`` is
    accepted as an alias ('minimal' maps to 'summary').

    Returns:
        JSON object mapping each requested key to its issue card (or
        {"error": ...} for keys that failed — one bad key never fails the batch).
    """
    jira = await get_jira_fetcher(ctx)
    response_format = _norm_response_format(response_format, return_mode)
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
                extras_from_raw=(("changelogs",) if "changelog" in includes else ()),
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


_JQL_MARKERS = re.compile(r"[=~<>]|\bORDER\s+BY\b|\bin\s*\(", re.IGNORECASE)
# JQL boolean operators are conventionally uppercase; lowercase 'and'/'or' is
# natural language. Case-sensitive on purpose.
_JQL_BOOL_OPS = re.compile(r"\b(AND|OR)\b")


def _looks_like_jql(query: str) -> bool:
    """Heuristic: JQL contains operators/keywords natural language doesn't."""
    q = query or ""
    return bool(_JQL_MARKERS.search(q) or _JQL_BOOL_OPS.search(q))


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
        Literal["auto", "jql", "semantic"],
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
        int,
        Field(
            description="Pagination offset (0-based), ignored for similar_to",
            default=0,
            ge=0,
        ),
    ] = 0,
    projects_filter: Annotated[
        str | None,
        Field(
            description="(Optional) Comma-separated project keys to restrict results.",
            default=None,
        ),
    ] = None,
) -> dict:
    """Find Jira issues — the ONLY search tool. JQL, semantic, or similar-to.

    Replaces search / list_issues / get_project_issues / semantic_search /
    find_similar / detect_duplicates. Results include the triage fields
    (status, assignee, priority, type, updated) so per-key follow-up
    jira_get calls are usually unnecessary. Narrow the query rather than
    paginating deeply.
    """
    # Deliberately function-level: vector_tools imports jira_mcp from this
    # module, so a top-level import would be circular.
    from mcp_atlassian.servers.vector_tools import semantic_search_impl

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

    result = await semantic_search_impl(
        query, projects=projects, limit=limit, offset=start_at
    )
    result["mode"] = "semantic"
    result["query"] = query
    return _json(result)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Transition Issues", "destructiveHint": True},
)
@check_write_access
async def transition(
    ctx: Context,
    keys: Annotated[
        str,
        Field(
            description="One issue key or comma-separated keys to move to the same status."
        ),
    ],
    to_status: Annotated[
        str | None,
        Field(
            description=(
                "Target status NAME, e.g. 'Ready for QA' or 'In Progress'. "
                "Case-insensitive; resolved server-side per key — never look up "
                "transition ids yourself. On no match the error lists every "
                "valid name. Provide this OR transition_id."
            ),
            default=None,
        ),
    ] = None,
    transition_id: Annotated[
        str | None,
        Field(
            description="(Optional) Raw transition id; prefer to_status.", default=None
        ),
    ] = None,
    fields: Annotated[
        dict[str, Any] | None,
        Field(
            description="(Optional) Fields to set during the transition, e.g. {'resolution': {'name': 'Fixed'}}.",
            default=None,
        ),
    ] = None,
    comment: Annotated[
        str | None,
        Field(
            description="(Optional) Comment added to each transitioned issue.",
            default=None,
        ),
    ] = None,
    return_mode: Annotated[
        str | None,
        Field(
            description=(
                "Canonical verbosity param. 'summary' (default), 'minimal', or "
                "'full'. Single-key only. (Alias: response_format is also "
                "accepted.)"
            ),
            default=None,
        ),
    ] = None,
    response_format: Annotated[
        str | None,
        Field(description="(Alias for return_mode.)", default=None),
    ] = None,
) -> dict:
    """Move one or many Jira issues to a new status by NAME.

    Handles single and batch transitions and resolves status names to
    transition ids internally. The
    response includes next_transitions (single-key), so no lookup call is
    ever needed. Batch failures are per-key — one bad key never aborts the rest.
    Single key → issue envelope + next_transitions; multiple keys →
    {target, summary: {ok, fail, total}, results: [...]}.
    """
    jira = await get_jira_fetcher(ctx)
    return_mode = _norm_return_mode(return_mode, response_format)
    key_list = _parse_csv(keys) or []
    if not key_list:
        raise ValueError("keys is required.")
    if not transition_id and not to_status:
        raise ValueError("Provide to_status (e.g. 'Ready for QA') or transition_id.")

    update_fields = fields or {}
    if not isinstance(update_fields, dict):
        raise ValueError("fields must be a dictionary.")

    if len(key_list) == 1:
        key = key_list[0]
        resolved = transition_id or _resolve_transition_id(jira, key, to_status)
        issue = jira.transition_issue(
            issue_key=key,
            transition_id=resolved,
            fields=update_fields,
            comment=comment,
        )
        return _operation_response(
            jira,
            message=f"Issue {key} transitioned successfully",
            issue=issue,
            issue_key=key,
            return_mode=return_mode,
            extra={"next_transitions": _next_transitions(jira, key)},
        )

    results: list[dict[str, Any]] = []
    ok = fail = 0
    for key in key_list:
        try:
            resolved = transition_id or _resolve_transition_id(jira, key, to_status)
            jira.transition_issue(
                issue_key=key,
                transition_id=resolved,
                fields=update_fields,
                comment=comment,
            )
            results.append({"key": key, "success": True})
            ok += 1
        except Exception as e:
            results.append({"key": key, "success": False, "error": str(e)})
            fail += 1
            logger.warning(f"transition: {key} failed: {e}")
    return _json(
        {
            "target": to_status or transition_id,
            "summary": {"ok": ok, "fail": fail, "total": len(key_list)},
            "results": results,
        }
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Comment on Issue", "destructiveHint": True},
)
@check_write_access
async def comment(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g., 'PROJ-123'). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    body: Annotated[
        str | None,
        Field(
            description=(
                "Comment body. Atlassian Wiki is the canonical syntax "
                "(*bold*, {code}...{code}, h2. heading). Input is always run "
                "through the Markdown→Wiki preprocessor; format only gates the "
                "Markdown-leakage warning."
            ),
            default=None,
        ),
    ] = None,
    comment_id: Annotated[
        str | None,
        Field(
            description="(Optional) Existing comment id — edits that comment instead of adding a new one.",
            default=None,
        ),
    ] = None,
    visibility: Annotated[
        dict[str, str] | None,
        Field(
            description="""(Optional) Visibility, e.g. {"type":"group","value":"jira-users"}""",
            default=None,
        ),
    ] = None,
    format: Annotated[
        Literal["auto", "wiki", "markdown"],
        Field(
            description=(
                "Controls the Markdown-leakage warning only (input is always "
                "run through the Markdown→Wiki preprocessor): 'auto' (default) "
                "warns if Markdown markers are detected; 'wiki' and 'markdown' "
                "both suppress the warning."
            ),
            default="auto",
        ),
    ] = "auto",
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Add or edit a comment on a Jira issue.

    Replaces add_comment / edit_comment. The body is always run through the
    Markdown→Wiki preprocessor regardless of format; format only gates the
    Markdown-leakage warning. The response's body_preview is the STORED body
    post-conversion — verify rendering from it; do NOT follow up with a
    jira_get call to check the comment.

    The issue identifier is ``issue_key`` (canonical); ``key`` and ``keys`` are
    accepted as aliases so callers needn't remember which spelling this tool wants.
    """
    jira = await get_jira_fetcher(ctx)
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    if not body:
        raise ValueError("body is required.")
    warnings: list[str] = []
    if format == "auto":
        markers: list[str] = []
        if re.search(r"\*\*[^*\n]+\*\*", body or ""):
            markers.append("**bold** (Wiki uses *bold*)")
        if re.search(r"^```", body or "", re.M):
            markers.append("``` fenced code (Wiki uses {code}...{code})")
        if re.search(r"^#{1,6} ", body or "", re.M):
            markers.append("# heading (Wiki uses h1./h2./h3.)")
        if markers:
            warnings.append(
                "Markdown markers detected in comment; Atlassian Wiki is the "
                "canonical comment syntax. Detected: " + ", ".join(markers)
            )

    if comment_id:
        result = jira.edit_comment(issue_key, comment_id, body, visibility)
        action = "edited"
    else:
        result = jira.add_comment(issue_key, body, visibility)
        action = "added"

    if not isinstance(result, dict):
        envelope: dict[str, Any] = {"action": action, "comment": result}
        if warnings:
            envelope["warnings"] = warnings
        return _json(envelope)

    stored = str(result.get("body") or "")
    cid = result.get("id") or comment_id
    envelope = {
        "success": True,
        "action": action,
        "comment_id": cid,
        "url": (
            f"{_issue_url(jira, issue_key)}?focusedCommentId={cid}"
            if cid
            else _issue_url(jira, issue_key)
        ),
        "body_preview": stored[:300] + ("…" if len(stored) > 300 else ""),
        "body_chars": len(stored),
    }
    ts = result.get("created") or result.get("updated")
    if ts:
        envelope["created" if action == "added" else "updated"] = ts
    if warnings:
        envelope["warnings"] = warnings
    return _json(envelope)


def _link_type_dicts(jira: Any) -> list[dict[str, Any]]:
    """Issue link types as plain dicts regardless of model/dict return."""
    out = []
    for t in jira.get_issue_link_types():
        if hasattr(t, "to_simplified_dict"):
            out.append(t.to_simplified_dict())
        elif isinstance(t, dict):
            out.append(t)
    return out


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Link Issue", "destructiveHint": True},
)
@check_write_access
async def link(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "The issue being linked FROM (e.g. 'DS-123'). Canonical param; "
                "'key' and 'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    to: Annotated[
        str | None,
        Field(
            description=(
                "Link target: an issue key ('DS-456'), an epic key when "
                "link_type='epic', or a URL when link_type='web'."
            ),
            default=None,
        ),
    ] = None,
    link_type: Annotated[
        str | None,
        Field(
            description=(
                "Semantic link kind: 'epic' (parent epic), 'web' (external URL, "
                "e.g. a PR), or an issue-link type name like 'Blocks' / "
                "'Relates' / 'Duplicate'. Unknown names error with the valid list."
            ),
            default=None,
        ),
    ] = None,
    title: Annotated[
        str | None,
        Field(
            description="(Optional, web links) Display title; defaults to the URL.",
            default=None,
        ),
    ] = None,
    remove: Annotated[
        bool,
        Field(
            description="Remove a link instead of creating one (requires link_id).",
            default=False,
        ),
    ] = False,
    link_id: Annotated[
        str | None,
        Field(description="(remove=true) The issue-link id to delete.", default=None),
    ] = None,
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Create or remove any kind of Jira link.

    Replaces link_to_epic / create_issue_link / create_remote_issue_link /
    remove_issue_link / get_link_types. 'epic' and 'web' are special kinds;
    everything else is matched against the instance's issue-link types —
    exact type NAME first (case-insensitive), then relationship phrase
    (inward/outward) as a fallback (an ambiguous phrase match errors).

    Every create returns a consistent envelope: ``success``, ``key`` (the
    FROM issue), and a human-readable ``message``. Web links carry only
    url + title — the legacy tool's relationship/icon/summary fields are
    intentionally dropped.

    The FROM issue is ``issue_key`` (canonical); ``key`` and ``keys`` are
    accepted as aliases.
    """
    jira = await get_jira_fetcher(ctx)
    issue_key = _norm_key_param(issue_key, key, keys)

    if remove:
        if not link_id:
            raise ValueError("remove=true requires link_id.")
        result = jira.remove_issue_link(link_id)
        return _json(result if isinstance(result, dict) else {"success": True})

    if not issue_key:
        raise ValueError("issue_key (or key) is required when creating a link.")
    if not to or not link_type:
        raise ValueError("to and link_type are required when creating a link.")

    kind = link_type.strip().casefold()
    if kind == "epic":
        issue = jira.link_issue_to_epic(issue_key, to)
        return _operation_response(
            jira,
            message=f"Issue {issue_key} linked to epic {to}.",
            issue=issue,
            issue_key=issue_key,
            return_mode="minimal",
            extra={"success": True},
        )

    if kind == "web":
        result = jira.create_remote_issue_link(
            issue_key, {"object": {"url": to, "title": title or to}}
        )
        out = result if isinstance(result, dict) else {}
        out.setdefault("success", True)
        out["key"] = issue_key
        out["message"] = f"Linked {issue_key} to {to}"
        return _json(out)

    # Match exact type NAME first across all types; only on no name match
    # fall back to relationship phrases (inward/outward). A phrase that
    # matches more than one type is ambiguous — error rather than guess.
    types = _link_type_dicts(jira)
    canonical = next(
        (
            t["name"]
            for t in types
            if t.get("name") and str(t["name"]).casefold() == kind
        ),
        None,
    )
    if canonical is None:
        phrase_matches = [
            t["name"]
            for t in types
            if t.get("name")
            and kind
            in (
                str(t.get("inward", "")).casefold(),
                str(t.get("outward", "")).casefold(),
            )
        ]
        if len(phrase_matches) == 1:
            canonical = phrase_matches[0]
        elif len(phrase_matches) > 1:
            raise ValueError(
                f"Ambiguous link_type '{link_type}' matches multiple types by "
                f"relationship phrase: {sorted(set(phrase_matches))}. Use the "
                "exact type name instead."
            )
    if canonical is None:
        names = ", ".join(sorted({str(t.get("name")) for t in types if t.get("name")}))
        raise ValueError(
            f"Unknown link_type '{link_type}'. Valid issue-link types: {names}. "
            "Or use 'epic' / 'web'."
        )

    result = jira.create_issue_link(
        {
            "type": {"name": canonical},
            "inwardIssue": {"key": issue_key},
            "outwardIssue": {"key": to},
        }
    )
    out = result if isinstance(result, dict) else {}
    out.setdefault("success", True)
    out["key"] = issue_key
    out["message"] = f"Linked {issue_key} {canonical} {to}"
    return _json(out)


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Worklog", "destructiveHint": True},
)
@check_write_access
async def worklog(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g., 'PROJ-123'). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    time_spent: Annotated[
        str | None,
        Field(
            description=(
                "Time to log, Jira format ('1h 30m', '1d', '30m'). "
                "Omit to READ the issue's worklogs instead of adding one."
            ),
            default=None,
        ),
    ] = None,
    comment: Annotated[
        str | None, Field(description="(Optional, add) Worklog comment.", default=None)
    ] = None,
    started: Annotated[
        str | None,
        Field(
            description="(Optional, add) ISO start time; defaults to now.", default=None
        ),
    ] = None,
    original_estimate: Annotated[
        str | None,
        Field(description="(Optional, add) New original estimate.", default=None),
    ] = None,
    remaining_estimate: Annotated[
        str | None,
        Field(description="(Optional, add) New remaining estimate.", default=None),
    ] = None,
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Read worklogs (no time_spent) or add one (time_spent given).

    Replaces get_worklog / add_worklog. The issue identifier is ``issue_key``
    (canonical); ``key`` and ``keys`` are accepted as aliases.
    """
    jira = await get_jira_fetcher(ctx)
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    if time_spent is None:
        worklogs = jira.get_worklogs(issue_key)
        return _json({"key": issue_key, "worklogs": worklogs})
    result = jira.add_worklog(
        issue_key=issue_key,
        time_spent=time_spent,
        comment=comment,
        started=started,
        original_estimate=original_estimate,
        remaining_estimate=remaining_estimate,
    )
    return _json(
        {"message": "Worklog added successfully", "key": issue_key, "worklog": result}
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Attach File", "destructiveHint": True},
)
@check_write_access
async def attach(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g. 'PROJ-123'). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    file_path: Annotated[
        str | None,
        Field(
            description=(
                "Absolute path of the file to attach. Comma-separated for "
                "multiple files in one call."
            ),
            default=None,
        ),
    ] = None,
    key: Annotated[
        str | None, Field(description="(Alias for issue_key.)", default=None)
    ] = None,
    keys: Annotated[
        str | None, Field(description="(Alias for issue_key.)", default=None)
    ] = None,
) -> dict:
    """Upload one or more file attachments to a Jira issue.

    file_path takes a single absolute path, or comma-separated paths for
    multiple files. Per-file results carry success/filename/size/id; a missing
    file returns {success: false, error: ...} for that file rather than raising,
    so one bad path never aborts the rest.
    """
    jira = await get_jira_fetcher(ctx)
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    if not file_path:
        raise ValueError("file_path is required (one path or comma-separated paths).")

    paths = _parse_csv(file_path) or []
    if len(paths) == 1:
        return _json(jira.upload_attachment(issue_key=issue_key, file_path=paths[0]))

    results = [
        jira.upload_attachment(issue_key=issue_key, file_path=p) for p in paths
    ]
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    return _json(
        {
            "key": issue_key,
            "summary": {"ok": ok, "fail": len(results) - ok, "total": len(results)},
            "results": results,
        }
    )


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Agile (Boards & Sprints)"},
)
async def agile(
    ctx: Context,
    action: Annotated[
        Literal["boards", "sprints", "sprint_issues", "create_sprint", "update_sprint"],
        Field(
            description=(
                "'boards' (list boards), 'sprints' (list a board's sprints — "
                "needs board_id), 'sprint_issues' (needs sprint_id), "
                "'create_sprint' (needs board_id + sprint_name + start_date + "
                "end_date), 'update_sprint' (needs sprint_id)."
            )
        ),
    ],
    board_id: Annotated[
        str | None,
        Field(description="Board id (sprints / create_sprint).", default=None),
    ] = None,
    sprint_id: Annotated[
        str | None,
        Field(description="Sprint id (sprint_issues / update_sprint).", default=None),
    ] = None,
    project_key: Annotated[
        str | None, Field(description="(boards) Filter by project.", default=None)
    ] = None,
    board_name: Annotated[
        str | None, Field(description="(boards) Fuzzy name filter.", default=None)
    ] = None,
    board_type: Annotated[
        str | None, Field(description="(boards) 'scrum' or 'kanban'.", default=None)
    ] = None,
    state: Annotated[
        str | None,
        Field(
            description="(sprints) 'active'|'future'|'closed'; (update_sprint) new state.",
            default=None,
        ),
    ] = None,
    sprint_name: Annotated[
        str | None,
        Field(description="(create/update_sprint) Sprint name.", default=None),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(description="(create/update_sprint) ISO 8601 start.", default=None),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(description="(create/update_sprint) ISO 8601 end.", default=None),
    ] = None,
    goal: Annotated[
        str | None,
        Field(description="(create/update_sprint) Sprint goal.", default=None),
    ] = None,
    limit: Annotated[
        int, Field(description="Max results (1-50)", default=10, ge=1, le=50)
    ] = 10,
    start_at: Annotated[
        int, Field(description="Pagination offset", default=0, ge=0)
    ] = 0,
) -> dict:
    """Boards and sprints, one tool. Replaces get_agile_boards /
    get_sprints_from_board / get_sprint_issues / create_sprint / update_sprint /
    get_board_issues (use jira_find with JQL for board-issue queries).
    """
    jira = await get_jira_fetcher(ctx)

    if action == "boards":
        boards = jira.get_all_agile_boards_model(
            board_name=board_name,
            project_key=project_key,
            board_type=board_type,
            start=start_at,
            limit=limit,
        )
        return _json(
            {
                "boards": ResponseFormatter.compress_boards(
                    [b.to_simplified_dict() for b in boards]
                )
            }
        )

    if action == "sprints":
        if not board_id:
            raise ValueError("action='sprints' requires board_id.")
        sprints = jira.get_all_sprints_from_board_model(
            board_id=board_id, state=state, start=start_at, limit=limit
        )
        return _json(
            {
                "sprints": ResponseFormatter.compress_sprints(
                    [s.to_simplified_dict() for s in sprints]
                )
            }
        )

    if action == "sprint_issues":
        if not sprint_id:
            raise ValueError("action='sprint_issues' requires sprint_id.")
        search_result = jira.get_sprint_issues(
            sprint_id=sprint_id, fields=SUMMARY_FIELDS, start=start_at, limit=limit
        )
        return _json(
            ResponseFormatter.compress_search_result(search_result.to_simplified_dict())
        )

    if action == "create_sprint":
        require_write_access(ctx, "create sprint")
        if not (board_id and sprint_name and start_date and end_date):
            raise ValueError(
                "action='create_sprint' requires board_id, sprint_name, "
                "start_date, end_date."
            )
        sprint = jira.create_sprint(
            board_id=board_id,
            sprint_name=sprint_name,
            start_date=start_date,
            end_date=end_date,
            goal=goal,
        )
        return _json(
            {"message": "Sprint created", "sprint": sprint.to_simplified_dict()}
        )

    # update_sprint
    require_write_access(ctx, "update sprint")
    if not sprint_id:
        raise ValueError("action='update_sprint' requires sprint_id.")
    sprint = jira.update_sprint(
        sprint_id=sprint_id,
        sprint_name=sprint_name,
        state=state,
        start_date=start_date,
        end_date=end_date,
        goal=goal,
    )
    if sprint is None:
        return _json({"error": f"Failed to update sprint {sprint_id}."})
    return _json({"message": "Sprint updated", "sprint": sprint.to_simplified_dict()})


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Project Versions"},
)
async def versions(
    ctx: Context,
    project_key: Annotated[str, Field(description="Jira project key (e.g., 'PROJ')")],
    name: Annotated[
        str | None,
        Field(
            description="(Optional) Provide to CREATE a version with this name; omit to list.",
            default=None,
        ),
    ] = None,
    start_date: Annotated[
        str | None, Field(description="(create) Start date YYYY-MM-DD.", default=None)
    ] = None,
    release_date: Annotated[
        str | None, Field(description="(create) Release date YYYY-MM-DD.", default=None)
    ] = None,
    description: Annotated[
        str | None, Field(description="(create) Version description.", default=None)
    ] = None,
) -> dict:
    """List a project's fix versions, or create one (name given).

    Replaces get_project_versions / create_version / batch_create_versions.
    """
    jira = await get_jira_fetcher(ctx)
    if name is None:
        return _json(
            {"project": project_key, "versions": jira.get_project_versions(project_key)}
        )
    require_write_access(ctx, "create version")
    version = jira.create_project_version(
        project_key=project_key,
        name=name,
        start_date=start_date,
        release_date=release_date,
        description=description,
    )
    return _json({"message": "Version created", "version": version})


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Projects, Fields & Users", "readOnlyHint": True},
)
async def projects(
    ctx: Context,
    field_keyword: Annotated[
        str | None,
        Field(
            description="(Optional) Fuzzy-search Jira field definitions instead of listing projects.",
            default=None,
        ),
    ] = None,
    issue_types: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) A project key (e.g. 'AI'). Returns the issue types "
                "that can actually be CREATED in that project — call this before "
                "jira_create when the valid types are unknown, instead of guessing "
                "'Epic'/'Story'/'Task' and hitting 'Specify a valid issue type'."
            ),
            default=None,
        ),
    ] = None,
    user: Annotated[
        str | None,
        Field(
            description="(Optional) Look up a user (email / name / accountId) instead of listing projects.",
            default=None,
        ),
    ] = None,
    include_archived: Annotated[
        bool, Field(description="Include archived projects.", default=False)
    ] = False,
    limit: Annotated[
        int, Field(description="Max results", default=20, ge=1, le=100)
    ] = 20,
) -> dict:
    """Workspace discovery: project list (default), creatable issue types for a
    project (issue_types), field schema search (field_keyword), or user lookup
    (user).

    Replaces get_all_projects / search_fields / get_user_profile. Use the
    issue_types mode to discover valid jira_create issue types up front.
    """
    jira = await get_jira_fetcher(ctx)
    if user is not None:
        try:
            found = jira.get_user_profile_by_identifier(user)
            return _json({"success": True, "user": found.to_simplified_dict()})
        except Exception as e:
            return _json({"success": False, "error": str(e), "user_identifier": user})
    if issue_types is not None:
        raw_types = jira.get_project_issue_types(issue_types)
        compact = [
            {
                "id": it.get("id"),
                "name": it.get("name"),
                "subtask": it.get("subtask", False),
                "description": (it.get("description") or "")[:120],
            }
            for it in raw_types
        ]
        return _json({"project": issue_types, "issue_types": compact})
    if field_keyword is not None:
        return _json({"fields": jira.search_fields(field_keyword, limit=limit)})
    all_projects = jira.get_all_projects(include_archived=include_archived)
    compressed = ResponseFormatter.compress_projects(all_projects)
    out: dict[str, Any] = {"projects": compressed[:limit]}
    if len(compressed) > limit:
        out["truncated"] = True
        out["total"] = len(compressed)
        out["note"] = (
            f"Showing {limit} of {len(compressed)} projects. "
            "Raise 'limit' or filter with 'field_keyword'/'user' to narrow."
        )
    return _json(out)


def _handoff_line(raw: dict[str, Any]) -> dict[str, Any]:
    c = ResponseFormatter.compress_issue(raw, include_description=False)
    return {
        "key": c.get("key"),
        "status": c.get("status"),
        "priority": c.get("priority"),
        "summary": (c.get("summary") or "")[:80],
        "updated": c.get("updated"),
    }


@jira_mcp.tool(
    tags={"jira", "read"},
    annotations={"title": "Handoff Snapshot", "readOnlyHint": True},
)
async def handoff(
    ctx: Context,
    projects: Annotated[
        str | None,
        Field(
            description="(Optional) Comma-separated project keys to scope the snapshot.",
            default=None,
        ),
    ] = None,
    days: Annotated[
        int,
        Field(
            description="Recency window for 'recently updated' (days).",
            default=3,
            ge=1,
            le=30,
        ),
    ] = 3,
    limit: Annotated[
        int,
        Field(description="Max issues per section.", default=10, ge=1, le=30),
    ] = 10,
) -> dict:
    """Compact resumable state snapshot (~500 tokens) for context resets.

    Emits my open issues and my recently-updated issues as one-line cards.
    A fresh agent ingests this and resumes work without re-deriving state —
    call it at the start of a session or after a context reset instead of
    re-fetching individual issues.
    """
    jira = await get_jira_fetcher(ctx)
    scope = ""
    project_list = _parse_csv(projects)
    if project_list:
        for p in project_list:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,9}", p):
                raise ValueError(f"Invalid project key: {p!r}")
        quoted = ", ".join(f'"{p}"' for p in project_list)
        scope = f" AND project in ({quoted})"
    fields = ["summary", "status", "priority", "updated"]

    open_result = jira.search_issues(
        jql=f"assignee = currentUser() AND resolution = Unresolved{scope} "
        "ORDER BY updated DESC",
        fields=fields,
        limit=limit,
    )
    recent_result = jira.search_issues(
        jql=f"assignee = currentUser() AND updated >= -{days}d{scope} "
        "ORDER BY updated DESC",
        fields=fields,
        limit=limit,
    )
    open_issues = [_handoff_line(i.to_simplified_dict()) for i in open_result.issues]
    recently_updated = [
        _handoff_line(i.to_simplified_dict()) for i in recent_result.issues
    ]
    if not open_issues and not recently_updated:
        note = "No open or recently-updated issues assigned to you — clean slate."
    else:
        note = (
            "State snapshot for context reset — ingest and resume. "
            "Use jira_get for any issue needing detail."
        )
    return _json(
        {
            "note": note,
            "open_issues": open_issues,
            "recently_updated": recently_updated,
        }
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Create Issue", "destructiveHint": True},
)
@check_write_access
async def create(
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
                "- Parent: {'parent': 'PROJ-123'}  (the issue KEY as a string, not a {'key': ...} object)\n"
                "- Fix versions: {'fixVersions': [{'name': 'v1.0'}]}\n"
                "- Custom fields: {'customfield_10010': 'value'}\n\n"
                "IMPORTANT: Do NOT pass labels, duedate, priority as top-level parameters.\n"
                "They MUST be inside this additional_fields dict."
            ),
            default=None,
        ),
    ] = None,
    return_mode: Annotated[
        str | None,
        Field(
            description=(
                "Canonical verbosity param. Response size: 'summary' (default — "
                "key + url + a few shaped fields), 'minimal' (key + url + "
                "message only), or 'full' (legacy: complete issue payload). New "
                "tickets created via this tool are small by definition, but "
                "consistency with the other write tools keeps callers' code "
                "uniform. (Alias: response_format is also accepted.)"
            ),
            default=None,
        ),
    ] = None,
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
    response_format: Annotated[
        str | None,
        Field(description="(Alias for return_mode.)", default=None),
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
) -> dict:
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
    return_mode = _norm_return_mode(return_mode, response_format)
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

    try:
        issue = jira.create_issue(
            project_key=project_key,
            summary=summary,
            issue_type=issue_type,
            description=description,
            assignee=assignee,
            components=components_list,
            **extra_fields,
        )
    except Exception as e:
        # Enrich on failure only (no happy-path round-trip): if the issue_type
        # was rejected, tell the agent which types the project actually accepts
        # so it can self-correct in one shot instead of running discovery calls.
        valid = _project_issue_type_names(jira, project_key)
        hint = (
            f" Valid issue types for {project_key}: {', '.join(valid)}."
            if valid
            else ""
        )
        raise ValueError(
            f"Could not create issue with issue_type '{issue_type}' in "
            f"{project_key}: {e}.{hint}"
        ) from e
    return _operation_response(
        jira,
        message="Issue created successfully",
        issue=issue,
        return_mode=return_mode,
        response_fields=response_fields,
    )


@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Update Issue", "destructiveHint": True},
)
@check_write_access
async def update(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g., 'PROJ-123'). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    fields: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Dictionary of fields to update. For 'assignee', provide a string identifier (email, name, or accountId). "
                "Example: `{'assignee': 'user@example.com', 'summary': 'New Summary'}`"
            ),
            default=None,
        ),
    ] = None,
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
        str | None,
        Field(
            description=(
                "Canonical verbosity param. Response size: 'summary' (default — "
                "key + url + a few shaped fields), 'minimal' (key + url + "
                "message only), or 'full' (legacy: complete issue payload). Big "
                "descriptions can blow past harness token limits on 'full'. "
                "(Alias: response_format is also accepted.)"
            ),
            default=None,
        ),
    ] = None,
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
    response_format: Annotated[
        str | None,
        Field(description="(Alias for return_mode.)", default=None),
    ] = None,
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Update an existing Jira issue including changing status, adding Epic links, updating fields, etc.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key (canonical; 'key'/'keys' accepted as aliases).
        fields: Dictionary of fields to update.
        additional_fields: Optional dictionary of additional fields.
        attachments: Optional JSON array string or comma-separated list of file paths.
        return_mode: Response payload size — 'summary' (default), 'minimal',
            or 'full' (canonical; 'response_format' accepted as an alias).
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
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    return_mode = _norm_return_mode(return_mode, response_format)
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
async def assign(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g., 'PROJ-123'). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    assignee: Annotated[
        str | None,
        Field(
            description=(
                "Assignee identifier — email, displayName, or accountId. "
                "Pass an empty string to unassign. The tool resolves "
                "email/displayName to the correct accountId (Cloud) or "
                "username (Server/DC) before the write."
            ),
            default=None,
        ),
    ] = None,
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Set the assignee on a Jira issue with a minimal response payload.

    Use this instead of ``jira_update`` for assignee-only writes —
    the general update path can silently no-op on assignee in some
    configurations, and the Atlassian-hosted ``editJiraIssue`` echoes
    the entire issue JSON back (which exceeds harness token limits when
    the touched ticket carries a large description).

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key (canonical; 'key'/'keys' accepted as aliases).
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
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    if assignee is None:
        raise ValueError("assignee is required (pass an empty string to unassign).")
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
        raise ValueError(f"Failed to assign issue {issue_key}: {str(e)}") from e

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
async def delete(
    ctx: Context,
    issue_key: Annotated[
        str | None,
        Field(
            description=(
                "Jira issue key (e.g. PROJ-123). Canonical param; 'key' and "
                "'keys' are accepted as aliases."
            ),
            default=None,
        ),
    ] = None,
    key: Annotated[
        str | None,
        Field(description="(Alias for issue_key.)", default=None),
    ] = None,
    keys: Annotated[
        str | None,
        Field(description="(Alias for issue_key — single key.)", default=None),
    ] = None,
) -> dict:
    """Delete an existing Jira issue.

    Args:
        ctx: The FastMCP context.
        issue_key: Jira issue key (canonical; 'key'/'keys' accepted as aliases).

    Returns:
        JSON string indicating success.

    Raises:
        ValueError: If in read-only mode or Jira client unavailable.
    """
    jira = await get_jira_fetcher(ctx)
    issue_key = _norm_key_param(issue_key, key, keys)
    if not issue_key:
        raise ValueError("issue_key (or key) is required.")
    success = jira.delete_issue(issue_key)
    result = {
        "success": success,
        "message": f"Issue {issue_key} has been deleted successfully.",
    }
    # The underlying method raises on failure, so if we reach here, it's success.
    return _json(result)


# Import vector tools to register them on jira_mcp
# This must be at the end to avoid circular imports
try:
    from mcp_atlassian.servers import vector_tools  # noqa: F401

    logger.debug("Vector search tools registered successfully")
except ImportError as e:
    logger.debug(f"Vector search tools not available: {e}")
