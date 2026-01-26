# MCP Atlassian (ADR Fork)

[![Run Tests](https://github.com/TerminalGravity/mcp-atlassian/actions/workflows/tests.yml/badge.svg)](https://github.com/TerminalGravity/mcp-atlassian/actions/workflows/tests.yml)
![License](https://img.shields.io/github/license/TerminalGravity/mcp-atlassian)

A fork of [mcp-atlassian](https://github.com/sooperset/mcp-atlassian) with enhanced vector search, a web UI, and optimizations for AI-assisted development.

## What's Different in This Fork

| Feature | Description |
|---------|-------------|
| **Semantic Vector Search** | LanceDB-powered search with OpenAI embeddings for finding issues by meaning |
| **Jira Knowledge Web UI** | Next.js chat interface for natural language queries against your Jira data |
| **Query Caching** | In-memory caching with configurable TTL for faster repeated queries |
| **Response Compression** | Optimized output formatting for Claude Code and other MCP clients |
| **Tiered Tool Architecture** | Separate list vs. detail endpoints to reduce token usage |
| **Comment Indexing** | Search across issue comments, not just titles and descriptions |
| **Project Insights** | Aggregated analytics and pattern detection across issues |

---

## Quick Start (Docker)

The fastest way to get started. Requires only Docker.

### 1. Clone and Configure

```bash
git clone https://github.com/TerminalGravity/mcp-atlassian.git
cd mcp-atlassian
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start Everything

```bash
docker-compose up
```

This will:
- Build the backend and frontend containers
- Sync your Jira issues to the vector database (first run)
- Start the API server on http://localhost:8000
- Start the Web UI on http://localhost:3000

### 3. Subsequent Runs

```bash
# Skip sync for faster startup
SKIP_SYNC=true docker-compose up

# Rebuild after code changes
docker-compose up --build
```

---

## Quick Start (Native)

For development without Docker.

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Node.js 20+
- Jira Cloud account with API token
- OpenAI API key (for vector embeddings)

### 1. Clone and Install

```bash
git clone https://github.com/TerminalGravity/mcp-atlassian.git
cd mcp-atlassian
uv sync --frozen --all-extras --dev
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Jira and OpenAI credentials
```

### 3. Sync Your Issues

```bash
# Full sync of specific projects
uv run python -m mcp_atlassian.vector.cli sync --full --projects DS,AI

# Check sync status
uv run python -m mcp_atlassian.vector.cli status
```

### 4. Run the MCP Server

```bash
uv run mcp-atlassian -v
```

---

## Web UI (Jira Knowledge Chat)

A conversational interface for querying your Jira data using natural language.

![Jira Knowledge UI](web/docs/screenshots/jira-knowledge-results.png)

### Running the Web UI

**Terminal 1 - Backend:**
```bash
uv run uvicorn mcp_atlassian.web.server:app --host 0.0.0.0 --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000

### Features

- Natural language queries with AI-generated summaries
- Semantic search with vector embeddings
- JQL search with graceful error handling
- Issue statistics visualization (charts by status, type, project)
- Dark theme UI
- Starter prompts for common queries

See [web/docs/JIRA-KNOWLEDGE-UI.md](web/docs/JIRA-KNOWLEDGE-UI.md) for detailed documentation.

---

## Vector Search Tools

These tools are available when the MCP server is connected:

| Tool | Description |
|------|-------------|
| `jira_semantic_search` | Find issues by meaning, not just keywords |
| `jira_knowledge_query` | Natural language queries with auto-extracted filters |
| `jira_find_similar` | Find issues related to a specific issue |
| `jira_detect_duplicates` | Check for potential duplicates before creating |
| `jira_project_insights` | Aggregated patterns and analytics |
| `jira_search_comments` | Search across issue comments |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_EMBEDDING_PROVIDER` | `openai` | `openai` or `local` |
| `VECTOR_EMBEDDING_MODEL` | `text-embedding-3-small` | Model for embeddings |
| `VECTOR_DB_PATH` | `./data/lancedb` | Vector database location |
| `VECTOR_SYNC_PROJECTS` | `*` | Projects to sync (comma-separated or `*`) |
| `VECTOR_SYNC_INTERVAL_MINUTES` | `30` | Background sync interval |

---

## Standard MCP Tools

All upstream tools are available:

| Jira | Confluence |
|------|------------|
| `jira_search` - Search with JQL | `confluence_search` - Search with CQL |
| `jira_get_issue` - Get issue details | `confluence_get_page` - Get page content |
| `jira_create_issue` - Create issues | `confluence_create_page` - Create pages |
| `jira_update_issue` - Update issues | `confluence_update_page` - Update pages |
| `jira_transition_issue` - Change status | `confluence_add_comment` - Add comments |

---

## IDE Configuration

### Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "mcp-atlassian": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcp-atlassian", "run", "mcp-atlassian"],
      "env": {
        "JIRA_URL": "https://your-company.atlassian.net",
        "JIRA_USERNAME": "your.email@company.com",
        "JIRA_API_TOKEN": "your_api_token",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

---

## Development

### Setup

```bash
uv sync --frozen --all-extras --dev
pre-commit install
```

### Commands

```bash
# Run tests
uv run pytest

# Run linting
pre-commit run --all-files

# Run server locally
uv run mcp-atlassian -v

# Vector CLI
uv run python -m mcp_atlassian.vector.cli --help
```

### Project Structure

```
src/mcp_atlassian/
├── jira/          # Jira client and operations
├── confluence/    # Confluence client and operations
├── models/        # Pydantic data models
├── servers/       # MCP server implementations
├── vector/        # Vector search (LanceDB + embeddings)
├── web/           # FastAPI backend for web UI
└── utils/         # Shared utilities

web/               # Next.js frontend
tests/             # Test suite
```

See [AGENTS.md](AGENTS.md) for detailed development guidelines.

---

## Upstream

This fork is based on [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian). Full upstream documentation is available at [personal-1d37018d.mintlify.app](https://personal-1d37018d.mintlify.app).

---

## License

MIT - See [LICENSE](LICENSE).
