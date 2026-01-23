# CLAUDE.md - MCP Atlassian Knowledge Base

> **Audience**: Claude Code agents using this MCP server at ADR (All Digital Rewards)

This document provides context for effectively using the MCP Atlassian server as a power tool for Jira integration.

---

## Quick Start

This MCP server provides semantic search and direct Jira access. Use it to:
- Search for relevant issues using natural language
- Get issue details, comments, and history
- Create, update, and transition issues
- Explore project structure and relationships

---

## ADR Jira Projects

| Project | Key | Description |
|---------|-----|-------------|
| Development Services | DS | Main engineering project (~100K issues) |
| AI Initiatives | AI | AI/automation experiments |
| Other | Various | Additional projects as needed |

### DS Project Conventions
- **Issue Types**: Epic, Story, Bug, Task, Sub-task, Quote
- **Status Flow**: Backlog → In Progress → Review → Done
- **Labels**: Used for categorization (frontend, backend, api, etc.)
- **Components**: Functional areas within the platform

---

## MCP Tools Available

### Search Tools
- `jira_search` - JQL-based search with full Jira query syntax
- `jira_get_issue` - Get detailed issue with comments and history
- `jira_get_project_issues` - List issues for a project

### Write Tools (use carefully)
- `jira_create_issue` - Create new issues
- `jira_update_issue` - Modify existing issues
- `jira_add_comment` - Add comments to issues
- `jira_transition_issue` - Move issues through workflow

### Sprint/Board Tools
- `jira_get_agile_boards` - List scrum/kanban boards
- `jira_get_sprints_from_board` - Get sprint information
- `jira_get_sprint_issues` - Issues in a specific sprint

---

## Vector Search (Semantic)

The vector store provides semantic search across indexed issues:

### How It Works
1. Issues are converted to embeddings using OpenAI text-embedding-3-small
2. Stored in LanceDB for fast similarity search
3. Query in natural language to find conceptually related issues

### Using Vector Search
```python
# Search is done via the sync/search Python API
# or through skills like /jira-knowledge
```

### Database Location
- Path: `data/lancedb/`
- State: `data/lancedb/sync_state.json`

### Sync Commands
```bash
# Sync specific projects
uv run python -m mcp_atlassian.vector.cli sync --full --projects DS,AI

# Incremental sync (only changed issues)
uv run python -m mcp_atlassian.vector.cli sync
```

---

## Skills Available

### `/jira-knowledge <question>`
Query the Jira knowledge base using natural language:
- "How do we handle payment failures?"
- "What was decided about API versioning?"
- "Who worked on the authentication system?"

### `/jira-standup`
Generate standup notes from recent activity.

### `/jira-investigate <issue-key>`
Deep-dive into a specific issue with context.

### `/jira-dedup`
Find potential duplicate issues.

---

## JQL Quick Reference

Common JQL patterns for ADR:

```jql
# My open issues
assignee = currentUser() AND resolution = Unresolved

# Recent DS issues
project = DS AND updated >= -7d ORDER BY updated DESC

# Bugs in progress
project = DS AND issuetype = Bug AND status = "In Progress"

# Issues by label
project = DS AND labels = "api" AND status != Done

# Epic children
"Epic Link" = DS-1234

# Text search
project = DS AND text ~ "payment"
```

---

## Best Practices

### DO
- Use semantic search for exploratory questions
- Use JQL for precise, structured queries
- Check issue context before making changes
- Reference issue keys when discussing work

### DON'T
- Don't modify issues without explicit user request
- Don't create duplicate issues (search first)
- Don't assume issue state - always fetch current
- Don't push to production without user confirmation

---

## Environment Variables

Required for Jira connection:
```
JIRA_URL=https://alldigitalrewards.atlassian.net
JIRA_USERNAME=<email>
JIRA_API_TOKEN=<token>
```

For vector search:
```
OPENAI_API_KEY=<key>
VECTOR_DB_PATH=data/lancedb  # optional, defaults to this
```

---

## Troubleshooting

### Vector search returns no results
1. Check if sync has run: `ls -la data/lancedb/`
2. Run sync: `uv run python -m mcp_atlassian.vector.cli sync --full --projects DS`
3. Verify issues indexed in sync_state.json

### Jira connection errors
1. Check JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN are set
2. Test connection: `uv run python -c "from mcp_atlassian.jira import JiraFacade; JiraFacade()"`

### Slow searches
1. Use specific project filters in JQL
2. Limit result count with `limit` parameter
3. For large datasets, use pagination

---

## Development

See `AGENTS.md` for development workflow and code conventions.

```bash
# Run tests
uv run pytest

# Run linting
pre-commit run --all-files

# Run server locally
uv run mcp-atlassian -v
```
