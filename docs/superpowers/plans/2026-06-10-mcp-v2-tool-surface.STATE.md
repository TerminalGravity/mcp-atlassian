# MCP v2 Tool Surface — Canonical Execution State

> **Purpose:** single source of truth for resuming this project in ANY session.
> Update this file (and commit it) every time a task changes state.
> Spec: `docs/superpowers/specs/2026-06-10-mcp-v2-tool-surface-design.md`
> Plan: `docs/superpowers/plans/2026-06-10-mcp-v2-tool-surface.md` (13 tasks, full code per task)

**Last updated:** 2026-06-11 (after Task 3 close)

## Where the work lives

- **Worktree:** `/Users/jack/Developer/mcp-atlassian/.claude/worktrees/mcp-v2-surface`
- **Branch:** `worktree-mcp-v2-surface` (based on local `main` @ 4e57742 — includes the v1-bridge commit 4154e5d the plan depends on; `origin/main` is BEHIND local main, do not rebase onto origin)
- **Test command:** `uv run pytest tests/unit/servers/ -q` — current baseline: **136 passed, 0 failed**
- **Process:** superpowers:subagent-driven-development — fresh implementer subagent per task (sonnet), then spec-compliance review, then code-quality review (superpowers:code-reviewer), fix loops until approved. Full task text is pasted into each subagent prompt from the plan file (never make the subagent read the plan).

## Task board

| # | Task | Status | Commits |
|---|------|--------|---------|
| 1 | `jira_get` — multi-key reader, summary truncation | ✅ DONE (re-review approved) | 8a7d4f8, 9af60a9, 243f691 |
| 2 | `jira_find` — JQL/semantic/similar-to | ✅ DONE (re-review approved) | 3f1e389, 4d138fa |
| 3 | `jira_transition` — single/batch by name + B2 envelope hardening | ✅ DONE (spec ✅, quality ✅, follow-ups committed) | 4be18c7, 3fcea13, 8b51a2f |
| 4 | `jira_comment` — add/edit + body_preview | ⬜ NEXT | — |
| 5 | `jira_link` — epic/web/issue + removal | ⬜ pending | — |
| 6 | `jira_worklog` — read/add | ⬜ pending | — |
| 7 | `jira_agile` / `jira_versions` / `jira_projects` | ⬜ pending | — |
| 8 | vector_tools rewrite — `jira_knowledge` + `jira_vector_sync_status`, delete 19 | ⬜ pending | — |
| 9 | `jira_handoff` — context-reset snapshot | ⬜ pending | — |
| 10 | Clean break — delete 31 legacy Jira tools, rename create/update/assign/delete | ⬜ pending | — |
| 11 | Confluence 12 → 4 | ⬜ pending | — |
| 12 | Docs/skills sweep + budget evals | ⬜ pending | — |
| 13 | Live dogfood pass (needs user to reconnect MCP) | ⬜ pending | — |

Pre-task baseline commit: bcd78c0 (fixed pre-existing `test_create_issue` failure — `return_mode="full"`).

## Carry-overs discovered by review loops (do not lose)

**Into Task 8 (vector rewrite):**
- Decide error-surfacing policy in `semantic_search_impl`: empty-index returns soft `{"error","hint"}` JSON but embedder/store exceptions propagate as hard errors. Recommend: catch embed/store failures → actionable hint payloads. Test it.
- Fix `has_more` off-by-one when `exclude_key` trims results (vector_tools.py pagination block).

**Into Task 12 (sweep/evals):**
- Promote `ResponseFormatter._relative_timestamp` → public `relative_timestamp`; update the external use in jira.py (`_issue_card` latest_comments).
- If budget evals flag `include="changelog"` payloads: cap to last-N + total count (mirror latest_comments/comments_total).
- Truncation limits shipped as 400 (description) / 200 (comment body), not the plan's 500/300 — done to hold the <1500-byte card budget; document in spec if touched.
- E402 mid-file imports in test_jira_server.py (plan-verbatim) — fold into the lint pass.
- `uv run ruff format` the touched ranges of jira.py (minor format drift noted by Task 3 review).

## Defects the review loop caught (context for future reviewers)

1. **Plan bug (Task 1):** `include="changelog"` was fetched then silently dropped in summary mode → fixed via `_issue_card(extras_from_raw=...)`.
2. **Plan bug (Task 2):** `\bAND\b|\bOR\b` under IGNORECASE misrouted natural language ("payment and refund failures") to JQL → fixed with case-sensitive `_JQL_BOOL_OPS`; plan file amended in 4d138fa.
3. **Latent bug (Task 3):** `_operation_response`'s last-resort fallback could itself raise on a non-serializable key, violating the B2 "successful write never errors" guarantee → hardened with 3 guards + 2 unit tests.

Pattern: implementer (sonnet) + two-stage review catches ~1 real defect per task. Do not skip reviews.

## Conventions locked in (apply to all remaining tasks)

- **Readability rule (binding, in plan header):** flat fields over nested objects, display names over accountIds, relative timestamps ("2h ago"), no null/empty keys, no responses > ~2 KB unless `full` requested.
- Enum-ish string params use `typing.Literal` (already imported in jira.py), e.g. `mode`, `return_mode`. Add a bogus-value rejection test each time.
- Lazy function-level import for anything from `vector_tools` inside `jira.py` tools (circular import: vector_tools imports `jira_mcp` from jira.py). Test patches target the NON-`src.`-prefixed module path (`mcp_atlassian.servers.vector_tools...`).
- Steering truncation tag: `TRUNC_HINT` in jira.py.
- New tools register on `jira_mcp`; exposed names get the `jira_` mount prefix (function `get` → tool `jira_get`). Test fixture `test_jira_mcp` needs the import + `add_tool(...)` for every new tool.
- Each task: TDD (failing tests first), full `tests/unit/servers/` green before commit, conventional-commit messages `feat(v2):` / `fix(v2):`.

## Session-resume checklist

1. `cd /Users/jack/Developer/mcp-atlassian/.claude/worktrees/mcp-v2-surface` (or `EnterWorktree path=...`)
2. `git log --oneline -5` + `git status` — confirm clean and matching the task board above
3. `uv run pytest tests/unit/servers/ -q` — confirm the baseline count
4. Open the plan file, find the NEXT task, dispatch per the process above
5. Update this file + commit when a task changes state

## Visual progress dashboard

`/tmp/mcp-v2-progress.html` (regenerate freely — it's throwaway; `open` it in the browser; auto-refreshes). Real before/after sample: jira_get on a multi-KB ticket went 20,577 → 1,551 bytes (13.3×).

## Live dogfood (Task 13) prerequisites

User must reconnect the `adr-jira` MCP server after Task 12 lands so the v2 surface loads. Scratch writes go to a sandbox/test issue the user designates.
