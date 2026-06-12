# MCP v2 Tool Surface — Canonical Execution State

> **Purpose:** single source of truth for resuming this project in ANY session.
> Update this file (and commit it) every time a task changes state.
> Spec: `docs/superpowers/specs/2026-06-10-mcp-v2-tool-surface-design.md`
> Plan: `docs/superpowers/plans/2026-06-10-mcp-v2-tool-surface.md` (13 tasks, full code per task)

**Last updated:** 2026-06-11 (Tasks 1–12 DONE; Task 13 dogfood blocked on user MCP reconnect)

## Where the work lives

- **Worktree:** `/Users/jack/Developer/mcp-atlassian/.claude/worktrees/mcp-v2-surface`
- **Branch:** `worktree-mcp-v2-surface` (based on local `main` @ 4e57742 — includes the v1-bridge commit 4154e5d the plan depends on; `origin/main` is BEHIND local main, do not rebase onto origin)
- **Test command:** `uv run pytest tests/unit/servers/ -q` — current baseline: **168 passed, 0 failed** (full `tests/unit/` ~1265 passed)
- **Process:** superpowers:subagent-driven-development — fresh implementer subagent per task (sonnet), then spec-compliance review, then code-quality review (superpowers:code-reviewer), fix loops until approved. Full task text is pasted into each subagent prompt from the plan file (never make the subagent read the plan).

## Task board

| # | Task | Status | Commits |
|---|------|--------|---------|
| 1 | `jira_get` — multi-key reader, summary truncation | ✅ DONE (re-review approved) | 8a7d4f8, 9af60a9, 243f691 |
| 2 | `jira_find` — JQL/semantic/similar-to | ✅ DONE (re-review approved) | 3f1e389, 4d138fa |
| 3 | `jira_transition` — single/batch by name + B2 envelope hardening | ✅ DONE (spec ✅, quality ✅, follow-ups committed) | 4be18c7, 3fcea13, 8b51a2f |
| 4 | `jira_comment` — add/edit + body_preview | ✅ DONE (re-review approved) | 9e77e91, 2a32831 |
| 5 | `jira_link` — epic/web/issue + removal | ✅ DONE (re-review approved, branch coverage added) | a49af7e, 5330722, dc6f843 |
| 6 | `jira_worklog` — read/add | ✅ DONE (spec-verified inline; trivial) | 9428d28 |
| 7 | `jira_agile` / `jira_versions` / `jira_projects` + read-only write-guard | ✅ DONE (spec ✅, quality ✅, read-only regression fixed + mutation-tested) | 19c93a3, af5c888 |
| 8 | vector_tools rewrite — `jira_knowledge` + `jira_vector_sync_status`, delete 19 | ✅ DONE (spec ✅, quality ✅, 3021→334 lines) | 8a40423, 6e5136d |
| 9 | `jira_handoff` — context-reset snapshot | ✅ DONE (spec ✅, quality ✅, real budget test) | 53b543c, 1662b49 |
| 10 | Clean break — delete 37 legacy, rename create/update/assign/delete → 14 tools | ✅ DONE (spec ✅ all 9 checks, quality ✅, lint 319→21) | a2ad28e |
| 11 | Confluence 12 → 4 (find/get/write/comment) | ✅ DONE (spec ✅, quality ✅, fallback log + truncation marker) | a7d96ee, d1cc759 |
| 12 | Docs/skills sweep + budget evals + coverage carry-overs | ✅ DONE (12a code + 12b docs, parallel; suite 1251 green) | 4e66226, 27caefd |
| 13 | Live dogfood pass | ⏸ BLOCKED ON USER — needs MCP reconnect to load v2 surface | — |

Pre-task baseline commit: bcd78c0 (fixed pre-existing `test_create_issue` failure — `return_mode="full"`).

## Carry-overs discovered by review loops (do not lose)

**Into Task 8 (vector rewrite):**
- Decide error-surfacing policy in `semantic_search_impl`: empty-index returns soft `{"error","hint"}` JSON but embedder/store exceptions propagate as hard errors. Recommend: catch embed/store failures → actionable hint payloads. Test it.
- Fix `has_more` off-by-one when `exclude_key` trims results (vector_tools.py pagination block).

**Into Task 10 (clean break):**
- Task 7 added inline read-only guards (`require_write_access`) on jira_agile/jira_versions write sub-actions. When deleting legacy create_sprint/update_sprint/create_version/batch_create_versions, confirm the deletions do NOT strip the new guarded paths in the v2 `agile`/`versions` tools. The new helper lives in `utils/decorators.py` (`require_write_access`, `_resolve_read_only`) — keep it.
- Also confirm Task 7's plan amendment (read-only note in the plan's Task 7 section) is honored.

**Into Task 12 (sweep/evals):**
- Add server-layer tests for `jira_update` / `jira_assign` / `jira_delete` — they have NO MCP-tool-boundary tests (pre-existing gap, not caused by Task 10; bodies are covered indirectly at the mixin layer in tests/unit/jira/). Cover arg parsing, return_mode shaping, @check_write_access.
- Restore `jira_projects` filter/error-path coverage: Task 10 collapsed ~10 get_all_projects tests into 1 happy-path `test_jira_projects_list`. Untested now: include_archived=True branch, projects-filter narrowing, auth/config error paths through the tool.
- Trivial: F841 unused `deleted` var in the `delete` tool (jira.py ~1712) — clean up when keeper bodies are next touched.
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

## ⚠️ Main-branch divergence (merge consideration for Task 10 / finishing)

A PARALLEL session has advanced `main` past this worktree's base (4e57742) with at least:
- `8a93e36` "feat(jira): account_id in user-profile payload + upload_attachment tool" (adds `account_id` to JiraUser.to_simplified_dict + a `jira_upload_attachment` tool)

The worktree is isolated and unaffected, but at merge/finish time:
- The v2 clean break DELETES `get_user_profile` (folded into `jira_projects`) and does NOT include `upload_attachment` — reconcile: either fold `account_id` into `jira_projects`' user lookup, and decide whether `upload_attachment` joins the v2 surface (it's a legit tool the corpus didn't cover) or is dropped.
- Expect a non-trivial merge on `jira.py` / `test_jira_server.py`. Diff `main` against the worktree branch before merging; do NOT fast-forward.

NOTE for reviewers: this worktree lives at `.claude/worktrees/mcp-v2-surface`. ALWAYS run git/pytest from there. Running them in the main repo root (`/Users/jack/Developer/mcp-atlassian/`) shows `main`, which legitimately lacks the v2 work — that is NOT a revert (one reviewer tripped on this).

## Final holistic review (post Task 12) — SHIP ✅

Branch reviewed end-to-end for cross-cutting/integration concerns: 20 tools surface through the REAL mount path (main.py mounts jira_mcp+confluence_mcp); read/write tag partition clean (10/10, no unguarded write exposed in read-only mode — the critical check); jira_agile/jira_versions inline write-guards intact end-to-end; no dead/duplicate registration; imports clean; suite green (1255 passed). Verdict: **code ready to merge** (Task 13 live-dogfood still pending on user). `tests/unit/servers/test_v2_surface_smoke.py` now pins the assembled 20-tool surface (uses the non-src-prefixed import path = real assembly).

**Post-merge polish (non-blocking, fold into the upload_attachment/account_id merge pass):**
- `response_format` (jira_get: summary|full) vs `return_mode` (writes: summary|minimal|full) — divergent names + enum sets, both plain `str` not `Literal`. Either unify, or make both `Literal` + cross-reference in docstrings.
- `success` key non-uniform across write envelopes: assign/delete/link have it; create_sprint/versions-create/worklog-add return `{"message":...}` without it. Add `success: True` for a uniform contract.

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
