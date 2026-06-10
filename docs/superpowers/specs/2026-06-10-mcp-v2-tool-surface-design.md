# MCP Atlassian v2 Tool Surface — Design

**Date**: 2026-06-10
**Status**: Approved
**Scope**: Full MCP surface (jira.py, vector_tools.py, confluence.py) — clean break, old tools removed outright.

## Motivation

The server exposes ~70 tools across three sub-servers. A corpus analysis of 1,624 Claude Code transcripts (~1,673 adr-jira calls) quantified the friction:

- **Overlap drowns the good tools**: workflow tools built 2026-05-12 (`quick_status`, `batch_transition`, `pr_handoff`, `keys_from_text`, `get_issue_summary`) would erase most round-trip waste but got 0–3 calls each, because ~70 competing primitives make Claude default to familiar ones.
- **Round-trip waste (~350–450 eliminable calls)**: transition-ID lookups (103 `get_transitions` calls exist only to map names→IDs), post-comment verification re-fetches (up to 230), search→get_issue fan-out (5–10 follow-ups per search), same-issue re-fetching (DS-12400 fetched 8× in one session).
- **Context bloat**: `get_issue` defaults to full description + 10 full comment bodies; one 29 MB session spent ~17% of its context on Jira tool results.
- **Open defects**: B1 — duplicate issue creation on ambiguous response (DS-12909 created twice); B2 — successful writes masked by response-serialization errors, causing re-runs.

Design rubric (Anthropic engineering: *Writing tools for agents*, *Effective context engineering*, *Harness design for long-running agents*): smallest set of non-overlapping workflow-shaped tools; token-efficient responses with verbosity controls; truncation that steers; semantic names over opaque IDs; actionable errors; idempotent writes; compact references and structured handoffs for long-horizon work.

## Principle: clean break

Old tools are **deleted, not aliased**. The corpus shows adoption follows availability: as long as `get_transitions` exists, Claude will call it. Skills, CLAUDE.md, and agent configs are updated in the same change.

## New surface — 17 tools

### Read (replaces 12 tools)

#### `jira_get(keys, response_format="summary")`
Replaces: `get_issue`, `get_issue_summary`, `quick_status`, `batch_get_changelogs`, `jira_get_issue_dates`, `jira_get_issue_sla`.

- `keys`: one issue key or a list (kills per-issue fan-out loops).
- `response_format="summary"` (default): key, summary, status, assignee, type, priority, updated; description truncated to ~500 chars; comment **count** plus the latest 2 comments truncated to ~300 chars each. Every truncation is tagged: `…[truncated — use response_format="full"]`.
- `response_format="full"`: complete description, all comments (paginated, `comment_limit`/`comment_offset`), changelog on request via `include=["changelog"]`.
- Dates/SLA fields fold into `include=["dates"]`.
- Target: a summary fetch of a multi-KB v7-TS ticket ≤ ~1 KB. Re-fetching becomes cheap rather than prevented.

#### `jira_find(query, fields=None, limit=20, similar_to=None)`
Replaces: `search`, `list_issues`, `get_project_issues`, `get_board_issues`, `jira_semantic_search`, `jira_find_similar`, `jira_detect_duplicates`, `jira_search_comments`.

- `query`: JQL or natural language. Detection: parses as valid JQL → JQL path; otherwise semantic search over the vector store. Optional `mode="jql"|"semantic"` override.
- Default fields = the triage set (key, summary, status, assignee, type, priority, updated) so search results answer triage questions without follow-up `jira_get` calls.
- `similar_to="DS-1234"` finds semantically similar issues (covers find_similar and duplicate detection).
- Results paginated; truncation message suggests narrowing the query (steering).

### Write (replaces 13 tools)

All write tools share the **write-success envelope** (fixes B2): the write outcome (key, success, resulting state) is captured before any response shaping. If shaping or serialization fails, the tool returns a guaranteed-tiny `{"success": true, "key": …, "warning": "response shaping failed: …"}` instead of an error. A formatting failure can never masquerade as a failed write.

#### `jira_create(issues, allow_duplicate=False)`
Replaces: `create_issue`, `batch_create_issues`.
- `issues`: one issue spec or a list.
- **Idempotency guard (fixes B1)**: before creating, search for an issue with identical summary in the same project created within the last ~10 minutes. If found, return that key with `duplicate_suspected: true` and do not create. Override with `allow_duplicate=True`.

#### `jira_transition(keys, to_status, comment=None)`
Replaces: `transition_issue`, `batch_transition`, `get_transitions`.
- `to_status`: the human status **name** ("Ready for QA"). ID resolution is server-side with case-insensitive/fuzzy matching.
- Invalid name → error listing the valid transition names for that issue (actionable error; no separate lookup tool).
- `keys` accepts a list for batch transitions.
- Eliminates all 103 `get_transitions` calls in the corpus.

#### `jira_comment(issue_key, body, comment_id=None)`
Replaces: `add_comment`, `edit_comment`.
- `comment_id` present → edit; absent → add.
- Keeps the Markdown-leakage preflight (`format="auto"`).
- Response includes `rendered_preview`: the first ~300 chars of what Jira actually stored after conversion — closes the render-verification loop in-band (kills the per-comment `get_issue` re-fetch, pattern C2).

#### `jira_update(issue_key, fields, ...)` — kept, shape unchanged (return_mode already fixed).
#### `jira_assign(issue_key, assignee)` — kept as-is (67 successful adoptions post-fix).
#### `jira_worklog(issue_key, ...)` — merges `add_worklog` + `get_worklog` (add when `time_spent` given, read otherwise).
#### `jira_link(source_key, target_key_or_url, link_type)`
Replaces: `create_issue_link`, `remove_issue_link`, `link_to_epic`, `create_remote_issue_link`, `get_link_types`.
- `link_type`: semantic names — "blocks", "relates to", "epic", "web" (remote URL), etc. Invalid type → error listing valid types.
- `remove=True` deletes a link.

#### `jira_delete(issue_key, confirm)` — kept (destructive; requires explicit confirm).

### Agile / admin (replaces 11 tools)

Corpus shows ~10 total calls across this group; it does not merit more surface.

#### `jira_agile(action, ...)`
Replaces: `get_agile_boards`, `get_sprints_from_board`, `get_sprint_issues`, `create_sprint`, `update_sprint`, `get_board_issues` (board listing portion).
- `action`: `"boards" | "sprints" | "sprint_issues" | "create_sprint" | "update_sprint"`.
- Accepted trade-off: this is the one dispatch-param tool in the design, justified by negligible call volume.

#### `jira_versions(project_key, create=None)` — replaces `get_project_versions`, `create_version`, `batch_create_versions`.

#### `jira_projects(project_key=None, include=None)`
Replaces: `get_all_projects`, `search_fields`, `get_user_profile`.
- No args → project list. With key → project detail. `include=["fields"]` → field discovery; `include=["users"], user_query=…` → user lookup.

### Knowledge & long-horizon (replaces 14 tools)

#### `jira_knowledge(question, scope=None)`
Replaces: `jira_knowledge_query`, `jira_ai_query`, `jira_ai_summary`, `jira_project_insights`, `jira_issue_clusters`, `jira_issue_trends`, `jira_bug_patterns`, `jira_project_velocity`, `jira_resolution_patterns`, `jira_cross_project_patterns`, `jira_project_feature_matrix`, `jira_vendor_capabilities`, `jira_generate_faq`, `jira_top_questions`.
- One semantic-Q&A entry point over the vector store. Just-in-time retrieval replaces 14 speculative pre-shaped analytics views (all unadopted in the corpus).
- `scope`: optional project keys / date range to bound retrieval.

#### `jira_handoff(scope=None)`
Evolved from `pr_handoff` (0 corpus calls — rebuilt around the harness-article context-reset pattern).
- Emits a compact (~500-token) structured state snapshot: my open issues (keys + status + one-line summaries), recent transitions, active sprint context, in-flight work references.
- Purpose: a fresh-context agent ingests the snapshot and resumes work without re-deriving state. Compact references, not payloads.

#### `jira_vector_sync_status` — kept (cheap, observability). `jira_vector_reload` dropped from MCP (ops action; CLI covers it).

#### `jira_keys_from_text` — **deleted** (0 calls; Claude extracts keys natively).

### Confluence (replaces 12 tools → 4)

- `confluence_find(query, space=None, limit)` — replaces `search`, `search_user`.
- `confluence_get(page_id_or_title, include=None)` — `include` ⊆ `["children", "comments", "labels", "views"]`. Replaces `get_page`, `get_page_children`, `get_comments`, `get_labels`, `confluence_get_page_views`.
- `confluence_write(page, ...)` — create or update (id present → update); label add folded in via `labels` param. Replaces `create_page`, `update_page`, `add_label`, `delete_page` (delete via `delete=True` + confirm).
- `confluence_comment(page_id, body)` — replaces `add_comment`.

## Tool count

| Group | Before | After |
|---|---|---|
| Jira core | 40 | 14 (`get`, `find`, `create`, `update`, `assign`, `transition`, `comment`, `worklog`, `link`, `delete`, `agile`, `versions`, `projects`, `handoff`) |
| Vector/AI | 21 | 2 (`jira_knowledge`, `jira_vector_sync_status`; semantic search lives inside `jira_find`) |
| Confluence | 12 | 4 |
| **Total** | **~73** | **20** |

## Docstring steering

Every tool description cross-references neighbors and states when *not* to use it, e.g. `jira_get`: "summary format answers status/assignee/triage questions — only request full when you need complete description or comment text." Per the corpus finding (section E), descriptions are the adoption mechanism.

## Coordinated break — non-code changes in the same change set

- `CLAUDE.md` MCP tools table rewritten for the new surface.
- `/jira-*` skills and any local agent configs referencing old tool names updated.
- The "verify rendering after every comment post" CLAUDE.md rule **removed** — superseded by `rendered_preview`.

## Error handling

- Invalid transition name / link type → error listing valid options for that specific issue (actionable; replaces lookup tools).
- Oversized result → truncate + message suggesting narrower query or pagination params (steering).
- Write path → write-success envelope (above); shaping failures degrade to minimal success payload, never to a false error.

## Testing strategy

1. **Unit**: per-tool tests for parameter routing (single vs. batch keys, JQL vs. semantic detection, summary truncation boundaries, idempotency-guard window, write-envelope fallback under forced serialization failure).
2. **Eval scenarios from the miner's patterns** — replayed against the new surface with asserted budgets:
   - Triage sweep (search + inspect 8 issues): ≤ 2 calls (was ~9), result ≤ 5 KB.
   - Transition 5 issues by status name: 1 call, 0 lookup calls (was ~10).
   - Post comment + confirm rendering: 1 call (was 2).
   - Duplicate-create retry: second identical create returns existing key, creates nothing.
3. **Existing test suite** updated to the new tool names; old-tool tests deleted with the tools.

## Out of scope

- Web UI (`src/mcp_atlassian/web/`) and sync pipeline internals — unchanged except where tool modules they import are renamed.
- Underlying Jira/Confluence client layers (`jira/`, `confluence/`) — reused as-is; this is a server-surface redesign.
- Worklog-discipline process overhead (A5) — process, not tooling.
