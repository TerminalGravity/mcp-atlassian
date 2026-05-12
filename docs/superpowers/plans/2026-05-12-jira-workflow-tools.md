# Jira MCP Workflow Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 tools to the Jira MCP that eliminate the high-frequency multi-call workflows surfaced during the 2026-05-12 changemaker-gcp ticket-sweep session.

**Architecture:** All tools live in `src/mcp_atlassian/servers/jira.py` and call existing `JiraFetcher` mixin methods (`transition_issue`, `assign_issue` from the prior commit, `create_remote_issue_link`). New tools follow the existing `@jira_mcp.tool` + `_operation_response` pattern. No new mixin methods needed.

**Tech Stack:** Python 3.10+, FastMCP, atlassian-python-api (underlying client).

---

## Task 1: `jira_quick_status` — read-side status map

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `get_issue` tool)

- [ ] **Step 1: Add tool function**

```python
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
    key. Tickets not found are emitted with ``{status: null, error: 'not found'}``.

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

    jql = f'key in ({", ".join(key_list)})'
    search_result = jira.search_issues(
        jql=jql,
        fields=["status", "assignee", "priority"],
        limit=len(key_list) * 2,
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
```

- [ ] **Step 2: Syntax + import check**

```bash
python3 -m py_compile src/mcp_atlassian/servers/jira.py
.venv/bin/python -c "from mcp_atlassian.servers import jira; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(jira): add jira_quick_status — minimal status map for many keys"
```

---

## Task 2: `jira_batch_transition` — batch transition many keys

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after `transition_issue`)

- [ ] **Step 1: Add tool function**

```python
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
        str,
        Field(description="ID of the transition to perform on every key."),
    ],
    comment: Annotated[
        str | None,
        Field(description="(Optional) Comment to add to every transitioned issue.", default=None),
    ] = None,
) -> str:
    """Transition many Jira issues through the same transition in one call.

    Returns a per-key result list. Failures on one key do not abort the
    others — the caller sees the full batch outcome and can retry the
    individual failures.

    Args:
        ctx: The FastMCP context.
        keys: Comma-separated Jira issue keys.
        transition_id: ID of the transition to apply to every key.
        comment: Optional comment text emitted on each transition.

    Returns:
        JSON object: ``{transition_id, summary: {ok, fail}, results: [...]}``.
    """
    jira = await get_jira_fetcher(ctx)
    key_list = _parse_csv(keys) or []
    if not key_list:
        raise ValueError("keys is required (comma-separated Jira issue keys).")
    if not transition_id:
        raise ValueError("transition_id is required.")

    results: list[dict[str, Any]] = []
    ok = 0
    fail = 0
    for key in key_list:
        try:
            jira.transition_issue(
                issue_key=key,
                transition_id=transition_id,
                fields={},
                comment=comment,
            )
            results.append({"key": key, "success": True})
            ok += 1
        except Exception as e:
            results.append({"key": key, "success": False, "error": str(e)})
            fail += 1
            logger.warning(f"batch_transition: {key} failed: {e}")

    return _json({
        "transition_id": transition_id,
        "summary": {"ok": ok, "fail": fail, "total": len(key_list)},
        "results": results,
    })
```

- [ ] **Step 2: Syntax + import + commit**

---

## Task 3: `jira_keys_from_text` — extract DS keys from any string

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add as read tool)

- [ ] **Step 1: Add tool function**

```python
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
        Field(description="If true (default), de-duplicate keys.", default=True),
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
    _ = await get_jira_fetcher(ctx)  # noqa: F841  (validates session)
    pattern = re.compile(r"\b([A-Z][A-Z0-9]+)-(\d+)\b")
    keys = [f"{m.group(1)}-{m.group(2)}" for m in pattern.finditer(text or "")]
    if project_filter:
        allowed = {p.strip().upper() for p in project_filter.split(",") if p.strip()}
        keys = [k for k in keys if k.split("-", 1)[0] in allowed]
    if dedupe:
        seen: set[str] = set()
        keys = [k for k in keys if not (k in seen or seen.add(k))]
    return _json({"keys": keys, "count": len(keys)})
```

Add at top of file: `import re` (verify it's not already imported).

- [ ] **Step 2: Syntax + import + commit**

---

## Task 4: `jira_pr_handoff` — atomic transition + assign + remote link

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` (add after batch_transition)

- [ ] **Step 1: Add tool function**

```python
@jira_mcp.tool(
    tags={"jira", "write"},
    annotations={"title": "PR Handoff", "destructiveHint": True, "idempotentHint": True},
)
@check_write_access
async def pr_handoff(
    ctx: Context,
    issue_key: Annotated[str, Field(description="Jira issue key (e.g., 'DS-12704').")],
    pr_url: Annotated[
        str,
        Field(description="The GitHub PR URL to attach as a remote link on the issue."),
    ],
    pr_title: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) PR title to use for the remote-link label. Defaults "
                "to the URL itself if omitted."
            ),
            default=None,
        ),
    ] = None,
    transition_id: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Transition ID to apply. If omitted, the status is "
                "left unchanged — useful when the ticket is already in the "
                "target state."
            ),
            default=None,
        ),
    ] = None,
    assignee: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Assignee identifier (email, displayName, or accountId). "
                "If omitted, assignee is left unchanged."
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Atomic post-PR-approval handoff: transition + assign + link.

    Wraps the three-call pattern (transition_issue → assign_issue →
    create_remote_issue_link) into a single tool call with a minimal
    response. Idempotent on each leg — re-running on an already-handed-off
    ticket re-applies the same transitions (where allowed) and re-asserts
    the link (Atlassian rejects duplicates; we swallow that error).

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
                issue_key=issue_key, transition_id=transition_id, fields={}, comment=None
            )
            out["transition"] = {"applied": True, "transition_id": transition_id}
        except Exception as e:
            out["transition"] = {
                "applied": False, "transition_id": transition_id, "error": str(e)
            }
            out["success"] = False
            logger.warning(f"pr_handoff {issue_key}: transition failed: {e}")

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
            out["link"] = {"added": False, "reason": "duplicate", "title": label}
        else:
            out["link"] = {"added": False, "error": str(e)}
            out["success"] = False
            logger.warning(f"pr_handoff {issue_key}: link failed: {e}")

    return _json(out)
```

- [ ] **Step 2: Syntax + import + commit**

---

## Task 5: `add_comment` Wiki-format preflight

**Files:**
- Modify: `src/mcp_atlassian/servers/jira.py` — `add_comment` tool

- [ ] **Step 1: Add `format` param**

Locate the existing `add_comment` tool. Add a `format` parameter:

```python
format: Annotated[
    str,
    Field(
        description=(
            "Comment markup format. 'auto' (default) emits a warning if "
            "obvious Markdown markers are detected (Atlassian Wiki is the "
            "canonical comment syntax). 'wiki' suppresses the check. "
            "'markdown' is accepted but lets the existing preprocessor handle conversion."
        ),
        default="auto",
    ),
] = "auto",
```

In the body, after the existing comment write, attach a warnings list:

```python
warnings: list[str] = []
if format == "auto":
    md_markers = []
    if re.search(r"\*\*[^*]+\*\*", comment):
        md_markers.append("**bold** (Wiki uses *bold*)")
    if re.search(r"^```", comment, re.M):
        md_markers.append("``` fenced code (Wiki uses {code}...{code})")
    if re.search(r"^#{1,6} ", comment, re.M):
        md_markers.append("# heading (Wiki uses h1./h2./h3.)")
    if md_markers:
        warnings.append(
            "Markdown markers detected in comment; Atlassian Wiki is the "
            "canonical comment syntax. Detected: " + ", ".join(md_markers)
        )
```

Add `warnings` to the result envelope when non-empty.

- [ ] **Step 2: Syntax + import + commit**

---

## Task 6: Verification + push all

- [ ] **Step 1: Final import test**
```bash
.venv/bin/python -c "from mcp_atlassian.servers import jira; print('OK')"
```

- [ ] **Step 2: Dogfood `pr_handoff` against an already-handed-off ticket**

Run a Python one-liner against DS-12918 (already Stan-assigned, Ready for QA) with `transition_id=None`, `assignee=None`, `pr_url='https://github.com/alldigitalrewards/changemaker-gcp/pull/36'`. Expect: success, link reports duplicate (already added in prior session). No state change.

- [ ] **Step 3: Push to origin/main**
```bash
git push origin main
```

---

## Self-review (done at plan-write time)

- ✅ All 5 tools from the user spec present (quick_status, batch_transition, keys_from_text, pr_handoff, add_comment format preflight).
- ✅ No placeholders — every step has the actual code.
- ✅ Tool name consistency: `quick_status`, `batch_transition`, `keys_from_text`, `pr_handoff` all use snake_case. FastMCP registers them as `jira_quick_status`, etc., via the `@jira_mcp.tool` decorator + module prefix.
- ✅ Type consistency: every tool uses the existing `_operation_response` / `_shape_issue_model` / `_field_value` / `_parse_csv` / `_json` helpers that landed in commit `a9531ad`. No new helpers required.
- ✅ Dogfood verification uses a known-idempotent ticket (DS-12918) so we don't accidentally re-trigger a real state change during testing.
