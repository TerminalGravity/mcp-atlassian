# MCP Atlassian v2 Tool Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the MCP server's ~73 tools into 20 workflow-shaped, token-efficient tools per the approved spec (`docs/superpowers/specs/2026-06-10-mcp-v2-tool-surface-design.md`), deleting all superseded tools.

**Architecture:** Additive-then-subtractive within the existing module layout: Tasks 1–9 add the new consolidated tools alongside the old ones (every task leaves the suite green), Task 10 deletes/renames the superseded Jira tools, Task 11 rewrites Confluence, Task 12 sweeps docs and adds token-budget eval tests. New tools register on the existing `jira_mcp` / `confluence_mcp` FastMCP instances; the `main_mcp.mount(..., "jira")` prefix turns function `get` into exposed tool `jira_get`.

**Tech Stack:** Python 3.10+, FastMCP, Pydantic, pytest (`uv run pytest`), existing fetcher layer (`JiraFetcher` via `get_jira_fetcher`, `ConfluenceFetcher` via `get_confluence_fetcher`), LanceDB vector store (`mcp_atlassian/vector/`).

**Output readability rule (applies to every tool):** responses render inline in Claude Code sessions and must read as human-scannable cards, not JSON walls — flat fields over nested objects (`"status": "In Progress"`, never `{"name": ...}`), display names over accountIds, relative timestamps (`"2h ago"`), one-line summaries, no null/empty keys. `ResponseFormatter` flattening + `_issue_card` enforce this; any new response shape must follow it. Task 13 verifies it live.

**Run tests with:** `uv run pytest tests/unit/servers/ -x -q` (fast loop) and `uv run pytest -x -q` (full) before each commit.

**Worktree:** Execute in a dedicated worktree (superpowers:using-git-worktrees) branched from `main`.

---

## Deviations from spec (approved-by-plan-review)

1. **`force` not `allow_duplicate`** on `jira_create` — the duplicate-guard bypass already shipped as `force`; renaming a working, adopted parameter buys nothing.
2. **`batch_create_issues` is deleted without absorbing a list-create into `jira_create`** — a `dict | list[dict]` union parameter is exactly the schema ambiguity the tool-design article warns against. Corpus shows 78 single creates and near-zero batch; N creates = N calls is acceptable. YAGNI.
3. **`download_attachments` is deleted** (writes files to disk; not in the approved 20-tool surface; the REST API or web UI covers the rare need).
4. **`jira_get` supports `include="sla"`** in addition to the spec's `include="dates"` — the SLA calculator exists and folds in for free.

## Existing code reused (do NOT rebuild)

| Helper / body | Location | Used by |
|---|---|---|
| `_json`, `_parse_csv`, `_issue_url`, `_field_value` | `src/mcp_atlassian/servers/jira.py:30-49` | everything |
| `_shape_issue_dict`, `_shape_issue_model` | `jira.py:52-106` | write envelopes |
| `_operation_response` (write-success envelope, B2 fix) | `jira.py:109-155` | all writes |
| `_find_transition`, `_resolve_transition_id`, `_next_transitions` | `jira.py:158-202` | `jira_transition` |
| `_find_recent_duplicate` (B1 fix) | `jira.py:205-231` | `jira_create` |
| `add_comment` envelope w/ `body_preview` (C2 fix) | `jira.py:1837-1878` | `jira_comment` |
| `ResponseFormatter` (compress_issue/search/boards/sprints/projects, `_truncate`) | `src/mcp_atlassian/jira/response_formatter.py` | reads |
| Vector singletons `_get_config/_get_store/_get_embedder/_get_parser` | `src/mcp_atlassian/servers/vector_tools.py:29-84` | `jira_find`, `jira_knowledge` |
| `jira_knowledge_query` body (self-query parser path) | `vector_tools.py:643-770` | `jira_knowledge` |
| `jira_vector_sync_status` body | `vector_tools.py:578-642` | `jira_vector_sync_status` |

## File map

| File | Change |
|---|---|
| `src/mcp_atlassian/servers/jira.py` | +10 new tools (Tasks 1–7, 9), then −31 old tools & 4 renames (Task 10). Ends ≈1,700 lines. |
| `src/mcp_atlassian/servers/vector_tools.py` | Rewritten (Task 8): 2,900 → ≈350 lines. Keeps singletons; adds `semantic_search_impl`/`similar_impl`; tools `knowledge`, `vector_sync_status`; deletes 19 tools. |
| `src/mcp_atlassian/servers/confluence.py` | Rewritten (Task 11): 12 → 4 tools. |
| `tests/unit/servers/test_jira_server.py` | New-tool tests added per task; fixture import/add_tool lists rewritten in Task 10. |
| `tests/unit/servers/test_vector_tools.py` | New (Task 8). |
| `tests/unit/servers/test_confluence_server.py` | Rewritten (Task 11). |
| `CLAUDE.md`, `.claude/**`, `AGENTS.md` | Tool-name sweep (Task 12). |

## Final exposed surface (20)

`jira_get, jira_find, jira_create, jira_update, jira_assign, jira_transition, jira_comment, jira_worklog, jira_link, jira_delete, jira_agile, jira_versions, jira_projects, jira_handoff, jira_knowledge, jira_vector_sync_status, confluence_find, confluence_get, confluence_write, confluence_comment`

---

### Task 1: `jira_get` — unified reader with summary-by-default truncation

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `_find_recent_duplicate`, line ~231)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/servers/test_jira_server.py` (top-level, after existing tests). Note the fixture changes in Step 3 are required for the client test to resolve `jira_get`.

```python
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
                {"author": {"display_name": f"U{i}"}, "created": "c", "body": "blah " * 200}
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "truncate_tagged or issue_card or jira_get" -q`
Expected: FAIL / ERROR with `ImportError: cannot import name '_issue_card'`

- [ ] **Step 3: Implement `jira_get`**

In `src/mcp_atlassian/servers/jira.py`, insert after `_find_recent_duplicate` (ends line ~231):

```python
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
    jira: Any, issue: Any, *, response_format: str = "summary"
) -> dict[str, Any]:
    """Token-budgeted issue view. summary ≈ 1 KB regardless of issue size."""
    raw = issue.to_simplified_dict()
    if raw.get("key") and not raw.get("url"):
        raw["url"] = _issue_url(jira, raw["key"])
    if response_format == "full":
        return raw

    card = ResponseFormatter.compress_issue(raw, include_description=False)
    card["url"] = raw.get("url")
    if raw.get("description"):
        card["description"] = _truncate_tagged(raw["description"], 500)
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
                "created": c.get("created"),
                "body": _truncate_tagged(str(c.get("body") or ""), 300),
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
            card = _issue_card(jira, issue, response_format=response_format)
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
            out[key] = {"error": str(e)}
    return _json(out)
```

In `tests/unit/servers/test_jira_server.py`, add `get` to the fixture: in the `from src.mcp_atlassian.servers.jira import (...)` block inside `test_jira_mcp`, add `get,` (alphabetical position), and add `jira_sub_mcp.add_tool(get)` next to the existing `add_tool(get_issue)` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "truncate_tagged or issue_card or jira_get" -q`
Expected: PASS (6 tests). Then `uv run pytest tests/unit/servers/ -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_get — multi-key reader with summary-by-default truncation"
```

---

### Task 2: `jira_find` — one search tool (JQL + semantic + similar-to)

**Files:**
- Modify: `src/mcp_atlassian/servers/vector_tools.py` (add impl helpers after `_get_parser`, line ~84)
- Modify: `src/mcp_atlassian/servers/jira.py` (add tool after `get`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
async def test_jira_find_requires_query_or_similar_to(jira_client):
    with pytest.raises(Exception, match="query"):
        await jira_client.call_tool("jira_find", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "looks_like_jql or jira_find" -q`
Expected: FAIL with `ImportError: cannot import name '_looks_like_jql'`

- [ ] **Step 3: Add impl helpers to vector_tools.py**

In `src/mcp_atlassian/servers/vector_tools.py`, after `_get_parser()` (line ~84), add plain async helpers (NOT tools). These are extracted from the existing `jira_semantic_search` body (lines 170–232) — same store/embedder calls, same compact result shape:

```python
async def semantic_search_impl(
    query: str,
    *,
    projects: list[str] | None = None,
    limit: int = 10,
    offset: int = 0,
    min_score: float = 0.3,
    exclude_key: str | None = None,
) -> dict[str, Any]:
    """Hybrid vector+FTS search. Plain coroutine shared by jira_find and tools here."""
    store = _get_store()
    embedder = _get_embedder()
    config = _get_config()

    stats = store.get_stats()
    if stats["total_issues"] == 0:
        return {
            "error": "Vector index is empty. Run sync first.",
            "hint": "uv run python -m mcp_atlassian.vector.cli sync --full",
        }

    query_vector = await embedder.embed(query)
    filters: dict[str, Any] = {}
    if projects:
        filters["project_key"] = {"$in": projects}

    results, total_count = store.hybrid_search(
        query_vector=query_vector,
        query_text=query,
        limit=limit + (1 if exclude_key else 0),
        offset=offset,
        filters=filters or None,
        fts_weight=config.fts_weight,
        min_score=min_score,
    )
    if exclude_key:
        results = [r for r in results if r["issue_id"] != exclude_key][:limit]

    response: dict[str, Any] = {
        "total_matches": total_count,
        "returned": len(results),
        "results": [
            {
                "key": r["issue_id"],
                "summary": r["summary"][:120],
                "type": r["issue_type"],
                "status": r["status"],
                "project": r["project_key"],
                "score": round(r.get("score", 0), 3),
            }
            for r in results
        ],
        "hint": "Use jira_get with the keys for details",
    }
    if total_count > offset + len(results):
        response["pagination"] = {
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit,
            "has_more": True,
        }
    return response
```

- [ ] **Step 4: Add the `find` tool to jira.py**

After the `get` tool in `src/mcp_atlassian/servers/jira.py`:

```python
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
```

In the test fixture: add `find,` to the import block and `jira_sub_mcp.add_tool(find)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "looks_like_jql or jira_find" -q`
Expected: PASS. Then `uv run pytest tests/unit/servers/ -q` — all green.

- [ ] **Step 6: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py src/mcp_atlassian/servers/vector_tools.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_find — unified JQL/semantic/similar-to search"
```

---

### Task 3: `jira_transition` — single or batch, by status name

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `find`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# --- v2 surface: jira_transition -------------------------------------------


@pytest.mark.anyio
async def test_jira_transition_single_by_name(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Ready for QA", "to_status": "Ready for QA"},
    ]
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_transition" -q`
Expected: FAIL with tool-not-found for `jira_transition`

- [ ] **Step 3: Implement `transition`**

Add after `find` in jira.py. Single-key path = existing `transition_issue` body; multi-key path = existing `batch_transition` body. Both reuse `_resolve_transition_id` / `_operation_response` / `_next_transitions` unchanged.

```python
@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Transition Issues", "destructiveHint": True},
)
@check_write_access
async def transition(
    ctx: Context,
    keys: Annotated[
        str,
        Field(description="One issue key or comma-separated keys to move to the same status."),
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
        Field(description="(Optional) Raw transition id; prefer to_status.", default=None),
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
        Field(description="(Optional) Comment added to each transitioned issue.", default=None),
    ] = None,
    return_mode: Annotated[
        str,
        Field(description="'summary' (default), 'minimal', or 'full'. Single-key only.", default="summary"),
    ] = "summary",
) -> str:
    """Move one or many Jira issues to a new status by NAME.

    Replaces transition_issue / batch_transition / get_transitions. The
    response includes next_transitions (single-key), so no lookup call is
    ever needed. Batch failures are per-key — one bad key never aborts the rest.
    """
    jira = await get_jira_fetcher(ctx)
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
```

Fixture: add `transition,` to import and `jira_sub_mcp.add_tool(transition)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_transition" -q`
Expected: PASS (3). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_transition — single/batch by status name"
```

---

### Task 4: `jira_comment` — add or edit, with rendered preview

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `transition`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
        "created": "2026-06-10T10:00:00.000+0000",
    }
    response = await jira_client.call_tool(
        "jira_comment",
        {"issue_key": "TEST-123", "body": "edited body", "comment_id": "10001"},
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "edited"
    assert content["body_preview"] == "edited body"
    mock_jira_fetcher.edit_comment.assert_called_once_with(
        "TEST-123", "10001", "edited body", None
    )


@pytest.mark.anyio
async def test_jira_comment_warns_on_markdown(jira_client, mock_jira_fetcher):
    mock_jira_fetcher.add_comment.return_value = {"id": "1", "body": "x", "created": "c"}
    response = await jira_client.call_tool(
        "jira_comment", {"issue_key": "TEST-123", "body": "**bold** text"}
    )
    content = json.loads(response.content[0].text)
    assert any("Markdown" in w for w in content.get("warnings", []))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_comment" -q`
Expected: FAIL — tool `jira_comment` not found

- [ ] **Step 3: Implement `comment`**

The body is the existing `add_comment` (jira.py:1837–1878) with: parameter renamed `comment`→`body`, an edit branch when `comment_id` is given, and `action` added to the envelope.

```python
@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Comment on Issue", "destructiveHint": True},
)
@check_write_access
async def comment(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
    body: Annotated[
        str,
        Field(
            description=(
                "Comment body. Atlassian Wiki is the canonical syntax "
                "(*bold*, {code}...{code}, h2. heading). With format='auto' "
                "(default) Markdown markers trigger a warning on the envelope."
            )
        ),
    ],
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
        str,
        Field(
            description="'auto' (default — warn on Markdown markers), 'wiki' (suppress check), 'markdown' (opt into Markdown→Wiki preprocessor).",
            default="auto",
        ),
    ] = "auto",
) -> str:
    """Add or edit a comment on a Jira issue.

    Replaces add_comment / edit_comment. The response's body_preview is the
    STORED body post-conversion — verify rendering from it; do NOT follow up
    with a jira_get call to check the comment.
    """
    jira = await get_jira_fetcher(ctx)
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
        "created": result.get("created"),
    }
    if warnings:
        envelope["warnings"] = warnings
    return _json(envelope)
```

Fixture: add `comment,` to import and `jira_sub_mcp.add_tool(comment)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_comment" -q`
Expected: PASS (3). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_comment — add/edit with stored-body preview"
```

---

### Task 5: `jira_link` — all link kinds in one tool

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `comment`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_link" -q`
Expected: FAIL — tool `jira_link` not found

- [ ] **Step 3: Implement `link`**

```python
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
        str, Field(description="The issue being linked FROM (e.g. 'DS-123').")
    ],
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
        Field(description="(Optional, web links) Display title; defaults to the URL.", default=None),
    ] = None,
    remove: Annotated[
        bool,
        Field(description="Remove a link instead of creating one (requires link_id).", default=False),
    ] = False,
    link_id: Annotated[
        str | None,
        Field(description="(remove=true) The issue-link id to delete.", default=None),
    ] = None,
) -> str:
    """Create or remove any kind of Jira link.

    Replaces link_to_epic / create_issue_link / create_remote_issue_link /
    remove_issue_link / get_link_types. 'epic' and 'web' are special kinds;
    everything else is matched (case-insensitive) against the instance's
    issue-link type names.
    """
    jira = await get_jira_fetcher(ctx)

    if remove:
        if not link_id:
            raise ValueError("remove=true requires link_id.")
        result = jira.remove_issue_link(link_id)
        return _json(result if isinstance(result, dict) else {"success": True})

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
        )

    if kind == "web":
        result = jira.create_remote_issue_link(
            issue_key, {"object": {"url": to, "title": title or to}}
        )
        out = result if isinstance(result, dict) else {}
        out.setdefault("success", True)
        out["key"] = issue_key
        return _json(out)

    types = _link_type_dicts(jira)
    canonical = None
    for t in types:
        for candidate in (t.get("name"), t.get("inward"), t.get("outward")):
            if candidate and str(candidate).casefold() == kind:
                canonical = t.get("name")
                break
        if canonical:
            break
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
    return _json(out)
```

Fixture: add `link,` to import and `jira_sub_mcp.add_tool(link)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_link" -q`
Expected: PASS (4). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_link — epic/web/issue links + removal in one tool"
```

---

### Task 6: `jira_worklog` — read or add

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `link`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_worklog" -q`
Expected: FAIL — tool `jira_worklog` not found

- [ ] **Step 3: Implement `worklog`**

```python
@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "Worklog", "destructiveHint": True},
)
@check_write_access
async def worklog(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'PROJ-123')")],
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
        Field(description="(Optional, add) ISO start time; defaults to now.", default=None),
    ] = None,
    original_estimate: Annotated[
        str | None, Field(description="(Optional, add) New original estimate.", default=None)
    ] = None,
    remaining_estimate: Annotated[
        str | None, Field(description="(Optional, add) New remaining estimate.", default=None)
    ] = None,
) -> str:
    """Read worklogs (no time_spent) or add one (time_spent given).

    Replaces get_worklog / add_worklog.
    """
    jira = await get_jira_fetcher(ctx)
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
    return _json({"message": "Worklog added successfully", "key": issue_key, "worklog": result})
```

Fixture: add `worklog,` to import and `jira_sub_mcp.add_tool(worklog)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_worklog" -q`
Expected: PASS (2). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_worklog — read/add in one tool"
```

---

### Task 7: `jira_agile`, `jira_versions`, `jira_projects` — admin collapse

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `worklog`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_agile or jira_versions or jira_projects" -q`
Expected: FAIL — tools not found

- [ ] **Step 3: Implement the three tools**

> **Read-only boundary note:** `agile` and `versions` stay tagged `read` (so the boards/sprints/list read sub-actions remain available in `--read-only` mode — tagging the whole tool `write` would wrongly hide the reads). Their write sub-actions (`create_sprint`, `update_sprint`, version create) are guarded INLINE via `require_write_access(ctx, "<action>")` (imported from `mcp_atlassian.utils.decorators`), which raises `ValueError(f"Cannot <action> in read-only mode.")`. Do NOT reintroduce these as `read`-only-tagged unguarded writes in Task 10. The `action` param is typed `Literal[...]` so pydantic rejects unknown actions at the boundary — no runtime `_AGILE_ACTIONS` membership check is needed.

```python
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
    board_id: Annotated[str | None, Field(description="Board id (sprints / create_sprint).", default=None)] = None,
    sprint_id: Annotated[str | None, Field(description="Sprint id (sprint_issues / update_sprint).", default=None)] = None,
    project_key: Annotated[str | None, Field(description="(boards) Filter by project.", default=None)] = None,
    board_name: Annotated[str | None, Field(description="(boards) Fuzzy name filter.", default=None)] = None,
    board_type: Annotated[str | None, Field(description="(boards) 'scrum' or 'kanban'.", default=None)] = None,
    state: Annotated[str | None, Field(description="(sprints) 'active'|'future'|'closed'; (update_sprint) new state.", default=None)] = None,
    sprint_name: Annotated[str | None, Field(description="(create/update_sprint) Sprint name.", default=None)] = None,
    start_date: Annotated[str | None, Field(description="(create/update_sprint) ISO 8601 start.", default=None)] = None,
    end_date: Annotated[str | None, Field(description="(create/update_sprint) ISO 8601 end.", default=None)] = None,
    goal: Annotated[str | None, Field(description="(create/update_sprint) Sprint goal.", default=None)] = None,
    limit: Annotated[int, Field(description="Max results (1-50)", default=10, ge=1, le=50)] = 10,
    start_at: Annotated[int, Field(description="Pagination offset", default=0, ge=0)] = 0,
) -> str:
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
            {"boards": ResponseFormatter.compress_boards(
                [b.to_simplified_dict() for b in boards]
            )}
        )

    if action == "sprints":
        if not board_id:
            raise ValueError("action='sprints' requires board_id.")
        sprints = jira.get_all_sprints_from_board_model(
            board_id=board_id, state=state, start=start_at, limit=limit
        )
        return _json(
            {"sprints": ResponseFormatter.compress_sprints(
                [s.to_simplified_dict() for s in sprints]
            )}
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
        require_write_access(ctx, "create sprint")  # write sub-action guard
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
        return _json({"message": "Sprint created", "sprint": sprint.to_simplified_dict()})

    # update_sprint
    require_write_access(ctx, "update sprint")  # write sub-action guard
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
        Field(description="(Optional) Provide to CREATE a version with this name; omit to list.", default=None),
    ] = None,
    start_date: Annotated[str | None, Field(description="(create) Start date YYYY-MM-DD.", default=None)] = None,
    release_date: Annotated[str | None, Field(description="(create) Release date YYYY-MM-DD.", default=None)] = None,
    description: Annotated[str | None, Field(description="(create) Version description.", default=None)] = None,
) -> str:
    """List a project's fix versions, or create one (name given).

    Replaces get_project_versions / create_version / batch_create_versions.
    """
    jira = await get_jira_fetcher(ctx)
    if name is None:
        return _json({"project": project_key, "versions": jira.get_project_versions(project_key)})
    require_write_access(ctx, "create version")  # write sub-action guard
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
        Field(description="(Optional) Fuzzy-search Jira field definitions instead of listing projects.", default=None),
    ] = None,
    user: Annotated[
        str | None,
        Field(description="(Optional) Look up a user (email / name / accountId) instead of listing projects.", default=None),
    ] = None,
    include_archived: Annotated[bool, Field(description="Include archived projects.", default=False)] = False,
    limit: Annotated[int, Field(description="Max results", default=20, ge=1, le=100)] = 20,
) -> str:
    """Workspace discovery: project list (default), field schema search
    (field_keyword), or user lookup (user).

    Replaces get_all_projects / search_fields / get_user_profile.
    """
    jira = await get_jira_fetcher(ctx)
    if user is not None:
        try:
            found = jira.get_user_profile_by_identifier(user)
            return _json({"success": True, "user": found.to_simplified_dict()})
        except Exception as e:
            return _json({"success": False, "error": str(e), "user_identifier": user})
    if field_keyword is not None:
        return _json({"fields": jira.search_fields(field_keyword, limit=limit)})
    all_projects = jira.get_all_projects(include_archived=include_archived)
    return _json({"projects": ResponseFormatter.compress_projects(all_projects)[:limit]})
```

Fixture: add `agile, projects, versions,` to import (alphabetical) and three `add_tool` lines. The test file needs `MagicMock` — already imported at top of the test module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_agile or jira_versions or jira_projects" -q`
Expected: PASS (7). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_agile / jira_versions / jira_projects admin collapse"
```

---

### Task 8: Rewrite vector_tools.py — `jira_knowledge` + `jira_vector_sync_status`, delete 19 tools

**Files:**
- Rewrite: `src/mcp_atlassian/servers/vector_tools.py`
- Create: `tests/unit/servers/test_vector_tools.py`
- Check: `tests/unit/vector/` (keep — tests the vector layer, not the tools; only delete files that import deleted tool functions)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/servers/test_vector_tools.py`:

```python
"""Tests for the v2 vector tool surface (knowledge / vector_sync_status)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_atlassian.servers import vector_tools


def test_v2_vector_surface_is_exactly_two_tools_plus_impls():
    """Old analytics tools must be gone; impls are plain helpers, not tools."""
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
async def test_semantic_search_impl_happy_path():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    store.hybrid_search.return_value = (
        [{"issue_id": "DS-1", "summary": "auth bug", "issue_type": "Bug",
          "status": "Open", "project_key": "DS", "score": 0.91}],
        1,
    )
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 8)
    config = MagicMock()
    config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl("auth bug", limit=5)
    assert result["returned"] == 1
    assert result["results"][0]["key"] == "DS-1"


@pytest.mark.anyio
async def test_semantic_search_impl_excludes_key():
    store = MagicMock()
    store.get_stats.return_value = {"total_issues": 100}
    store.hybrid_search.return_value = (
        [
            {"issue_id": "DS-1", "summary": "s", "issue_type": "Bug",
             "status": "Open", "project_key": "DS", "score": 0.99},
            {"issue_id": "DS-2", "summary": "s", "issue_type": "Bug",
             "status": "Open", "project_key": "DS", "score": 0.88},
        ],
        2,
    )
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 8)
    config = MagicMock()
    config.fts_weight = 0.3
    with (
        patch.object(vector_tools, "_get_store", return_value=store),
        patch.object(vector_tools, "_get_embedder", return_value=embedder),
        patch.object(vector_tools, "_get_config", return_value=config),
    ):
        result = await vector_tools.semantic_search_impl(
            "s", limit=1, exclude_key="DS-1"
        )
    assert [r["key"] for r in result["results"]] == ["DS-2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_vector_tools.py -q`
Expected: FAIL — `jira_semantic_search` still present / `knowledge` missing

- [ ] **Step 3: Rewrite vector_tools.py**

Replace the file's tool section. KEEP verbatim: the module docstring, imports (lines 1–27), `_reset_singletons` through `_get_parser` (lines 29–84), and the `semantic_search_impl` added in Task 2. Then:

1. **`knowledge`**: copy the body of `jira_knowledge_query` (lines 643–770) into a new tool function named `knowledge`, decorated `@jira_mcp.tool(tags={"jira", "vector", "read"}, annotations={"title": "Knowledge Query", "readOnlyHint": True})`. Change only: (a) the final hint string to `"Use jira_get with issue keys for full details"`, (b) the docstring to:

```python
    """Ask the synced Jira knowledge base a natural-language question.

    The ONLY knowledge/analytics tool. Parses the question into semantic
    terms + structured filters (project, type, status, assignee, dates)
    automatically — 'auth bugs from last month in DS' just works. For plain
    issue search use jira_find; for issue content use jira_get.
    """
```

2. **`vector_sync_status`**: copy the body of `jira_vector_sync_status` (lines 578–642) verbatim into a function named `vector_sync_status`, same decorator tags/annotations as the original. (The rename fixes the doubled `jira_jira_` prefix.)

3. **Delete** every other tool function and their private helpers that nothing else references: `jira_semantic_search`, `jira_find_similar`, `jira_detect_duplicates`, `jira_vector_reload`, `jira_knowledge_query`, `jira_search_comments`, `jira_project_insights`, `_get_insights_engine`, `jira_issue_clusters`, `jira_issue_trends`, `jira_bug_patterns`, `jira_project_velocity`, `_get_openai_client`, `jira_ai_summary`, `_build_issue_context`, `_generate_summary`, `jira_ai_query`, `_generate_answer`, `jira_resolution_patterns`, `jira_cross_project_patterns`, `jira_project_feature_matrix`, `jira_vendor_capabilities`, `jira_integration_knowledge`, `jira_generate_faq`, `jira_top_questions`. Remove imports that become unused (`SelfQueryParser` stays — `knowledge` uses `_get_parser`).

4. Check for orphaned references: `grep -rn "jira_semantic_search\|knowledge_query\|jira_ai_\|insights\|find_similar" src/ tests/ --include="*.py" | grep -v __pycache__` — fix any hit (delete dependent tests; `src/mcp_atlassian/vector/insights.py` itself stays, it's library code).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_vector_tools.py tests/unit/vector -q`
Expected: PASS (delete any old test files under `tests/unit/` that imported removed tool functions; the vector-layer tests stay green).

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/vector_tools.py tests/unit/servers/test_vector_tools.py
git commit -m "feat(v2)!: vector surface = jira_knowledge + jira_vector_sync_status (delete 19 tools)"
```

---

### Task 9: `jira_handoff` — context-reset state snapshot

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `projects`)
- Test: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_handoff" -q`
Expected: FAIL — tool not found

- [ ] **Step 3: Implement `handoff`**

```python
def _handoff_line(raw: dict[str, Any]) -> dict[str, Any]:
    c = ResponseFormatter.compress_issue(raw, include_description=False)
    return {
        "key": c.get("key"),
        "status": c.get("status"),
        "priority": c.get("priority"),
        "summary": (c.get("summary") or "")[:100],
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
        Field(description="(Optional) Comma-separated project keys to scope the snapshot.", default=None),
    ] = None,
    days: Annotated[
        int,
        Field(description="Recency window for 'recently updated' (days).", default=3, ge=1, le=30),
    ] = 3,
    limit: Annotated[
        int,
        Field(description="Max issues per section.", default=15, ge=1, le=30),
    ] = 15,
) -> str:
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
    return _json(
        {
            "note": (
                "State snapshot for context reset — ingest and resume. "
                "Use jira_get for any issue needing detail."
            ),
            "open_issues": [
                _handoff_line(i.to_simplified_dict()) for i in open_result.issues
            ],
            "recently_updated": [
                _handoff_line(i.to_simplified_dict()) for i in recent_result.issues
            ],
        }
    )
```

Fixture: add `handoff,` to import and `jira_sub_mcp.add_tool(handoff)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k "jira_handoff" -q`
Expected: PASS (2). Full server suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/unit/servers/test_jira_server.py
git commit -m "feat(v2): jira_handoff — compact state snapshot for context resets"
```

---

### Task 10: Clean break — rename keepers, delete 31 superseded Jira tools

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py`
- Modify: `tests/unit/servers/test_jira_server.py`

- [ ] **Step 1: Rename the four keepers (function defs only — bodies unchanged)**

In `src/mcp_atlassian/servers/jira.py`:
- `async def create_issue(` → `async def create(`
- `async def update_issue(` → `async def update(`
- `async def assign_issue(` → `async def assign(`
- `async def delete_issue(` → `async def delete(`

Update each tool's docstring cross-references while there (e.g. `create`'s docstring: "After creating, link to an epic with jira_link(link_type='epic')"). Also update intra-docstring mentions of old tool names anywhere in the kept tools (`grep -n "jira_get_issue\|jira_quick_status\|jira_search\b\|get_transitions\|batch_transition" src/mcp_atlassian/servers/jira.py` and fix each hit to reference the v2 names).

- [ ] **Step 2: Delete the superseded tools**

Delete these tool functions (decorator through body) from `jira.py`:

`get_user_profile, get_issue, get_issue_summary, quick_status, keys_from_text, search, list_issues, search_fields, get_project_issues, get_transitions, get_worklog, download_attachments, get_agile_boards, get_board_issues, get_sprints_from_board, get_sprint_issues, get_link_types, batch_create_issues, batch_get_changelogs, add_comment, edit_comment, add_worklog, link_to_epic, create_issue_link, create_remote_issue_link, remove_issue_link, transition_issue, batch_transition, pr_handoff, create_sprint, update_sprint, get_project_versions, get_all_projects, create_version, batch_create_versions, jira_get_issue_dates, jira_get_issue_sla`

Keep: all helpers (lines 30–231 region), `TRUNC_HINT`/`_truncate_tagged`/`_issue_card`/`_GET_INCLUDES`/`_JQL_MARKERS`/`_looks_like_jql`/`_link_type_dicts`/`_AGILE_ACTIONS`/`_handoff_line`, the 14 v2 tools, the `JiraUser` import (still used by `projects`), and the trailing `from mcp_atlassian.servers import vector_tools` registration import. Remove imports that become unused (run `uv run ruff check src/mcp_atlassian/servers/jira.py` and fix).

- [ ] **Step 3: Rewrite the test fixture and prune dead tests**

In `tests/unit/servers/test_jira_server.py`:

1. Replace the import block + `add_tool` list in `test_jira_mcp` with exactly the v2 surface:

```python
    from src.mcp_atlassian.servers.jira import (
        agile,
        assign,
        comment,
        create,
        delete,
        find,
        get,
        handoff,
        link,
        projects,
        transition,
        update,
        versions,
        worklog,
    )

    jira_sub_mcp = FastMCP(name="TestJiraSubMCP")
    for tool_fn in (
        agile, assign, comment, create, delete, find, get, handoff,
        link, projects, transition, update, versions, worklog,
    ):
        jira_sub_mcp.add_tool(tool_fn)
    test_mcp.mount(jira_sub_mcp, prefix="jira")
```

2. In `no_fetcher_test_jira_mcp`: `from src.mcp_atlassian.servers.jira import get` and `jira_sub_mcp.add_tool(get)`.
3. Delete tests that exercised deleted tools: `test_get_issue, test_search, test_create_issue*` (rename to call `jira_create` — keep these four tests, they cover the duplicate guard and additional_fields parsing; only the tool name string and import change), `test_batch_create_issues*` (delete), `test_get_user_profile_tool_*` (delete — covered by `test_jira_projects_user_lookup`), `test_no_fetcher_get_issue` (rewrite to call `jira_get` with `{"keys": "TEST-123"}` expecting the same fetcher error), `test_get_issue_with_user_specific_fetcher_in_state` (rewrite for `jira_get`), `test_get_project_versions_tool` / `test_get_all_projects_tool*` (delete — covered by Task 7 tests).
4. `grep -n "jira_get_issue\|jira_search\|jira_create_issue\|jira_update_issue\|jira_assign_issue\|jira_delete_issue\|jira_add_comment\|jira_transition_issue" tests/ -r` — every remaining hit gets the v2 name (`jira_get` + `keys`, `jira_find` + `query`, `jira_create`, `jira_update`, `jira_assign`, `jira_delete`, `jira_comment` + `body`, `jira_transition` + `keys`/`to_status`).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -x -q`
Expected: PASS. Also verify the surface count:

```bash
grep -c "^async def " src/mcp_atlassian/servers/jira.py   # expect 14
grep -c "^async def " src/mcp_atlassian/servers/vector_tools.py  # expect 3 (knowledge, vector_sync_status, semantic_search_impl)
```

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/jira.py tests/
git commit -m "feat(v2)!: clean break — delete 31 superseded Jira tools, rename keepers

jira.py surface is now: get, find, create, update, assign, transition,
comment, worklog, link, delete, agile, versions, projects, handoff."
```

---

### Task 11: Confluence — 12 tools → 4

**Files:**
- Rewrite: `src/mcp_atlassian/servers/confluence.py`
- Rewrite: `tests/unit/servers/test_confluence_server.py`

- [ ] **Step 1: Write the failing tests**

Replace `tests/unit/servers/test_confluence_server.py` content with a self-contained module (pattern mirrors the jira fixture; reuse its existing `MainAppContext`/config fixtures if present in the current file — keep whatever conftest-level fixtures the old file used for `mock_confluence_fetcher` and adapt):

```python
"""Tests for the v2 Confluence tool surface (find / get / write / comment)."""

import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client import FastMCPTransport

from src.mcp_atlassian.servers.context import MainAppContext
from src.mcp_atlassian.servers.main import AtlassianMCP


@pytest.fixture
def mock_confluence_fetcher():
    fetcher = MagicMock()
    page = MagicMock()
    page.to_simplified_dict.return_value = {
        "id": "123", "title": "Test Page", "space": {"key": "DEV"},
        "url": "https://test.example.com/wiki/spaces/DEV/pages/123",
    }
    page.content = "# content"
    fetcher.search.return_value = [page]
    fetcher.get_page_content.return_value = page
    fetcher.get_page_by_title.return_value = page
    fetcher.get_page_children.return_value = [page]
    comment = MagicMock()
    comment.to_simplified_dict.return_value = {"id": "c1", "body": "a comment"}
    fetcher.get_page_comments.return_value = [comment]
    fetcher.add_comment.return_value = comment
    label = MagicMock()
    label.to_simplified_dict.return_value = {"name": "docs"}
    fetcher.get_page_labels.return_value = [label]
    fetcher.add_page_label.return_value = [label]
    fetcher.create_page.return_value = page
    fetcher.update_page.return_value = page
    fetcher.delete_page.return_value = True
    return fetcher


@pytest.fixture
def conf_mcp(mock_confluence_fetcher):
    @asynccontextmanager
    async def lifespan(app: FastMCP) -> AsyncGenerator[MainAppContext, None]:
        yield MainAppContext(read_only=False)

    test_mcp = AtlassianMCP("TestConfluence", lifespan=lifespan)
    from src.mcp_atlassian.servers.confluence import comment, find, get, write

    sub = FastMCP(name="TestConfluenceSub")
    for fn in (comment, find, get, write):
        sub.add_tool(fn)
    test_mcp.mount(sub, prefix="confluence")
    return test_mcp


@pytest.fixture
async def conf_client(conf_mcp, mock_confluence_fetcher):
    with patch(
        "src.mcp_atlassian.servers.confluence.get_confluence_fetcher",
        AsyncMock(return_value=mock_confluence_fetcher),
    ):
        async with Client(transport=FastMCPTransport(conf_mcp)) as c:
            yield c


@pytest.mark.anyio
async def test_confluence_find_pages(conf_client, mock_confluence_fetcher):
    response = await conf_client.call_tool("confluence_find", {"query": "test docs"})
    content = json.loads(response.content[0].text)
    assert content["results"][0]["title"] == "Test Page"
    mock_confluence_fetcher.search.assert_called_once()


@pytest.mark.anyio
async def test_confluence_get_with_includes(conf_client, mock_confluence_fetcher):
    response = await conf_client.call_tool(
        "confluence_get", {"page_id": "123", "include": "children,comments,labels"}
    )
    content = json.loads(response.content[0].text)
    assert content["metadata"]["title"] == "Test Page"
    assert content["children"][0]["title"] == "Test Page"
    assert content["comments"][0]["body"] == "a comment"
    assert content["labels"][0]["name"] == "docs"


@pytest.mark.anyio
async def test_confluence_write_create(conf_client, mock_confluence_fetcher):
    response = await conf_client.call_tool(
        "confluence_write",
        {"space_key": "DEV", "title": "New", "content": "# hi"},
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "created"
    mock_confluence_fetcher.create_page.assert_called_once()


@pytest.mark.anyio
async def test_confluence_write_update(conf_client, mock_confluence_fetcher):
    response = await conf_client.call_tool(
        "confluence_write",
        {"page_id": "123", "title": "Updated", "content": "# hi2"},
    )
    content = json.loads(response.content[0].text)
    assert content["action"] == "updated"
    mock_confluence_fetcher.update_page.assert_called_once()


@pytest.mark.anyio
async def test_confluence_write_delete_requires_confirm(conf_client):
    with pytest.raises(Exception, match="confirm"):
        await conf_client.call_tool(
            "confluence_write", {"page_id": "123", "delete": True}
        )


@pytest.mark.anyio
async def test_confluence_comment(conf_client, mock_confluence_fetcher):
    response = await conf_client.call_tool(
        "confluence_comment", {"page_id": "123", "body": "nice page"}
    )
    content = json.loads(response.content[0].text)
    assert content["success"] is True
    mock_confluence_fetcher.add_comment.assert_called_once_with(
        page_id="123", content="nice page"
    )
```

NOTE: if `MainAppContext(read_only=False)` requires more constructor args in this codebase, copy the construction pattern from the old `test_confluence_server.py` fixtures before deleting them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/servers/test_confluence_server.py -q`
Expected: FAIL — `cannot import name 'find' from ...confluence`

- [ ] **Step 3: Rewrite confluence.py**

Keep: module docstring, imports, `confluence_mcp = FastMCP(...)` instance. Replace all 12 tools with 4. Bodies reuse the existing fetcher calls verbatim (search lines 87–113, get_page 184–233, children 305–333, comments 362–365, labels 394–397, create 497–530, update 601–636, delete 660–681, add_comment 711–734, search_user 775–807):

```python
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
                "Simple text ('project documentation') or CQL "
                "('type=page AND space=DEV', 'title~\"Meeting Notes\"', "
                "'label=documentation'). Simple text is wrapped in siteSearch "
                "automatically. With search_users=true, finds people instead "
                "('user.fullname ~ \"First Last\"' or a plain name)."
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
    limit: Annotated[int, Field(description="Max results (1-50)", default=10, ge=1, le=50)] = 10,
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
        original_query = query
        try:
            query = f'siteSearch ~ "{original_query}"'
            pages = confluence_fetcher.search(query, limit=limit, spaces_filter=spaces)
        except Exception:
            query = f'text ~ "{original_query}"'
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
        Field(description="Page ID (from the URL). Provide this OR title+space_key.", default=None),
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
        Field(description="Markdown (default) or raw HTML (token-heavy).", default=True),
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
            page_id=resolved_id, start=0, limit=25, expand="version",
            convert_to_markdown=convert_to_markdown, include_folders=True,
        )
        result["children"] = [c.to_simplified_dict() for c in children]
    if "comments" in includes:
        comments = confluence_fetcher.get_page_comments(resolved_id)
        result["comments"] = [c.to_simplified_dict() for c in comments]
    if "labels" in includes:
        labels = confluence_fetcher.get_page_labels(resolved_id)
        result["labels"] = [label.to_simplified_dict() for label in labels]
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
        Field(description="Existing page ID → update (or delete). Omit → create.", default=None),
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
        Field(description="'markdown' (default), 'wiki', or 'storage'.", default="markdown"),
    ] = "markdown",
    labels: Annotated[
        str | None,
        Field(description="(Optional) Comma-separated labels to add after writing.", default=None),
    ] = None,
    version_comment: Annotated[
        str | None,
        Field(description="(update) Version comment.", default=None),
    ] = None,
    delete: Annotated[
        bool,
        Field(description="Delete the page (requires page_id and confirm=true).", default=False),
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
            version_comment=version_comment,
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
        label_names = [label.strip() for label in labels.split(",") if label.strip()]
        applied = []
        for name in label_names:
            try:
                confluence_fetcher.add_page_label(
                    str(page_id or result["page"].get("id")), name
                )
                applied.append(name)
            except Exception as e:  # labels are best-effort decoration
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
```

Delete `confluence_get_page_views` along with the rest. `get_page_views` analytics drop entirely (zero corpus usage).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/servers/test_confluence_server.py -q`
Expected: PASS (7). Then `uv run pytest -x -q` — full suite green (fix any `tests/unit/confluence/` test importing deleted server tools; the fetcher-layer tests are untouched).

- [ ] **Step 5: Commit**

```bash
git add src/mcp_atlassian/servers/confluence.py tests/unit/servers/test_confluence_server.py
git commit -m "feat(v2)!: confluence surface = find/get/write/comment (12 → 4 tools)"
```

---

### Task 12: Docs/skills sweep, budget evals, final verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: any `.claude/` skill/config files referencing old tool names
- Test: `tests/unit/servers/test_jira_server.py` (budget evals)

- [ ] **Step 1: Add token-budget eval tests (from the miner's friction patterns)**

```python
# --- v2 budget evals (miner patterns) ----------------------------------------


def test_budget_summary_card_for_huge_issue_under_1500_bytes():
    """D3: a v7-TS-sized ticket must cost ~1 KB in summary form."""
    issue = _StubIssue(
        {
            "key": "DS-12400",
            "summary": "Huge spec ticket " + "x" * 100,
            "description": "spec line\n" * 1000,           # ~10 KB
            "status": {"name": "In Progress"},
            "priority": {"name": "P1"},
            "assignee": {"display_name": "Jack Felke"},
            "updated": "2026-06-09T10:00:00.000+0000",
            "comments": [
                {"author": {"display_name": "U"}, "created": "c", "body": "comment " * 300}
                for _ in range(10)
            ],                                              # ~24 KB of comments
        }
    )
    card = _issue_card(_StubJira(), issue, response_format="summary")
    assert len(json.dumps(card)) < 1500


@pytest.mark.anyio
async def test_budget_triage_sweep_is_one_call(jira_client, mock_jira_fetcher):
    """C1/C4: 8 issues in one jira_get call, not 8 calls."""
    response = await jira_client.call_tool(
        "jira_get", {"keys": ",".join(f"TEST-{i}" for i in range(1, 9))}
    )
    content = json.loads(response.content[0].text)
    assert len(content) == 8
    assert mock_jira_fetcher.get_issue.call_count == 8  # server-side, one MCP call


@pytest.mark.anyio
async def test_budget_transition_five_keys_zero_lookups(jira_client, mock_jira_fetcher):
    """C3: no get_transitions tool exists; names resolve server-side."""
    mock_jira_fetcher.get_available_transitions.return_value = [
        {"id": "41", "name": "Done", "to_status": "Done"}
    ]
    await jira_client.call_tool(
        "jira_transition",
        {"keys": "TEST-1,TEST-2,TEST-3,TEST-4,TEST-5", "to_status": "Done"},
    )
    assert mock_jira_fetcher.transition_issue.call_count == 5
```

Run: `uv run pytest tests/unit/servers/test_jira_server.py -k budget -q` — expected PASS (these pass immediately; they pin the budgets against regression).

- [ ] **Step 2: Sweep docs and skills for old tool names**

```bash
grep -rn "jira_get_issue\|jira_search\b\|jira_list_issues\|jira_quick_status\|jira_add_comment\|jira_transition_issue\|jira_batch_transition\|jira_get_transitions\|jira_semantic_search\|jira_knowledge_query\|jira_create_issue\|jira_update_issue\|jira_assign_issue\|confluence_get_page\|confluence_create_page" \
  CLAUDE.md AGENTS.md .claude/ docs/ README.md 2>/dev/null | grep -v docs/superpowers
```

For every hit, replace with the v2 name. In `CLAUDE.md` specifically, replace the "MCP Tools Available" section with:

```markdown
## MCP Tools Available

### Read
- `jira_get` - One or many issues (`keys` csv). `response_format='summary'` (default, ~1 KB/issue) or `'full'`. `include='changelog,dates,sla'` for extras.
- `jira_find` - The ONLY search tool: JQL or natural language (auto-detected), `similar_to='DS-123'` for duplicate detection.
- `jira_projects` - Project list, field schema search (`field_keyword`), user lookup (`user`).
- `jira_agile` - Boards & sprints (`action='boards'|'sprints'|'sprint_issues'|'create_sprint'|'update_sprint'`).
- `jira_handoff` - Compact state snapshot (my open issues + recent activity) for context resets.

### Write (use carefully)
- `jira_create` - New issue; duplicate guard returns the existing key on retry.
- `jira_update` / `jira_assign` / `jira_delete`
- `jira_transition` - One or many keys, by status NAME ('Ready for QA') — never look up transition ids.
- `jira_comment` - Add or edit (`comment_id`); response includes `body_preview` of the stored body — no verification fetch needed.
- `jira_worklog` - Read (no `time_spent`) or add.
- `jira_link` - Epic / web (PR) / issue links + removal.
- `jira_versions` - List or create fix versions.

### Knowledge
- `jira_knowledge` - Natural-language Q&A over the synced index (auto filter extraction).
- `jira_vector_sync_status` - Index freshness.

### Confluence
- `confluence_find` / `confluence_get` / `confluence_write` / `confluence_comment`
```

Also in `CLAUDE.md`: if any rule mandates verifying comment rendering with a follow-up fetch, delete it (superseded by `body_preview`). Update the JQL Quick Reference intro line to mention these run through `jira_find`.

- [ ] **Step 3: Lint and full verification**

```bash
uv run ruff check src/ tests/ --fix
uv run pytest -q
```

Expected: clean lint, full suite PASS.

- [ ] **Step 4: Smoke-test the live surface**

```bash
uv run python -c "
from mcp_atlassian.servers.jira import jira_mcp
import asyncio
tools = asyncio.run(jira_mcp.get_tools())
names = sorted(tools)
print(len(names), names)
"
```

Expected: 16 Jira-side tools — `agile, assign, comment, create, delete, find, get, handoff, knowledge, link, projects, transition, update, versions, vector_sync_status, worklog` (mounted as `jira_*`). Same check for `confluence_mcp` → 4.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude docs tests
git commit -m "feat(v2): docs/skills sweep + token-budget eval tests — v2 surface complete"
```

---

### Task 13: Dogfood pass — live human-readability verification

**Files:** none expected (fix-forward in `jira.py`/`vector_tools.py`/`confluence.py` if a check fails)

This task runs against the REAL Jira instance (alldigitalrewards.atlassian.net) through the reloaded MCP server in a Claude Code session. The user must restart/reconnect the `adr-jira` MCP server first — ask them to before starting.

- [ ] **Step 1: Reconnect the MCP server**

Ask the user to restart the MCP connection (e.g. `/mcp` reconnect or restart the Claude Code session) so the v2 surface loads. Verify: the available tools are exactly the 20 v2 names.

- [ ] **Step 2: Exercise each read tool and grade the inline rendering**

Make these live calls and inspect each response *as rendered in the session*:

1. `jira_get` with `keys` = one known-large ticket (e.g. a v7-TS spec ticket) — summary card fits on one screen, description ends with the truncation hint, comments show author + relative time.
2. `jira_get` with 5+ keys — output is a scannable per-key map, no repetition of giant fields.
3. `jira_find` with JQL (`assignee = currentUser() AND resolution = Unresolved`) — each result is one flat card: key, summary, status, assignee, priority, updated.
4. `jira_find` with natural language ("recent authentication work") — semantic results show key/summary/score, nothing nested.
5. `jira_handoff` — whole snapshot ≲ one screen, every line human-readable.
6. `jira_knowledge` with a real question — interpretation + results readable.
7. `confluence_find` + `confluence_get` on a known page.

**Acceptance bar per response:** no nested `{"name": ...}` objects, no accountIds where a display name exists, no absolute ISO timestamps where a relative one fits, no field that is null/empty noise, no response over ~2 KB unless `full` was requested.

- [ ] **Step 3: Exercise the write path on a scratch ticket**

On a designated test issue (ask the user which, or create one in a sandbox project with `jira_create` — the duplicate guard message itself is part of the readability check):

1. `jira_comment` — confirm `body_preview` is enough to verify rendering without any follow-up call.
2. `jira_transition` with a wrong status name — the error must read as instructions (lists valid names), not a stack trace.
3. `jira_transition` back to the original status by name.

- [ ] **Step 4: Fix-forward and re-verify**

Any check that fails gets fixed in the tool's shaping code (not by post-processing in the client), a unit test pinning the fix, and a re-run of the failed live call.

- [ ] **Step 5: Commit (if fixes were made)**

```bash
git add -A src/ tests/
git commit -m "fix(v2): dogfood pass — inline readability fixes"
```

---

## Completion checklist

- [ ] 20 exposed tools exactly (16 jira_* + 4 confluence_*)
- [ ] `uv run pytest -q` green
- [ ] No references to deleted tool names outside `docs/superpowers/` and git history
- [ ] Budget evals pin: summary card <1.5 KB, multi-key get, zero-lookup transitions
- [ ] Dogfood pass (Task 13) done against live Jira — every response human-readable inline
- [ ] User restarts their MCP client to pick up the new surface
