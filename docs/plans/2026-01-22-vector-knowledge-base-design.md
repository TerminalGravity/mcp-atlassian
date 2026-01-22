# Jira Vector Knowledge Base Design

**Date**: 2026-01-22
**Status**: Draft
**Author**: Design Session with Claude

## Executive Summary

This design adds a **self-querying vector knowledge base** to mcp-atlassian, enabling semantic search, duplicate detection, cross-project discovery, and pattern analysis across Jira issues. The implementation uses **LanceDB** for embedded vector storage, **hybrid search** (semantic + keyword), and is optimized for **Claude Code integration** with token-efficient MCP responses.

## Goals

1. **Semantic search** - Find issues by meaning, not just keywords
2. **Cross-project discovery** - Find related work across projects without explicit links
3. **Knowledge retrieval** - Give Claude/LLMs rich context about organizational Jira history
4. **Pattern detection** - Find similar issues, detect duplicates, identify trends
5. **Self-querying** - Natural language queries automatically extract filters + semantic search
6. **Token efficiency** - MCP responses optimized for Claude Code context limits

## Architecture Overview

```
+---------------------------------------------------------------------+
|                      MCP Tools Layer                                 |
+---------------------------------------------------------------------+
|  jira_semantic_search    |  jira_find_similar                       |
|  jira_knowledge_query    |  jira_detect_duplicates                  |
|  jira_project_insights   |  jira_sync_status                        |
+---------------------------------------------------------------------+
                              |
                              v
+---------------------------------------------------------------------+
|              Self-Query Retriever                                   |
|  "Find auth bugs from last quarter" -->                             |
|    filter: {project: *, labels: [bug], created: >90d ago}           |
|    query: "authentication"                                          |
+---------------------------------------------------------------------+
                              |
                              v
+---------------------------------------------------------------------+
|              Hybrid Search Engine                                   |
|  +---------------+    +---------------+    +-------------------+    |
|  | Dense Vector  | +  | Sparse BM25   | +  | Metadata Filter   |    |
|  |   Search      |    |   Search      |    |    (JQL-like)     |    |
|  +---------------+    +---------------+    +-------------------+    |
+---------------------------------------------------------------------+
                              |
                              v
+---------------------------------------------------------------------+
|              LanceDB (Embedded Vector Store)                        |
|  Collections: jira_issues, jira_comments                            |
|  Metadata: project, status, assignee, labels, created, etc.         |
+---------------------------------------------------------------------+
                              |
                              v
+---------------------------------------------------------------------+
|              Sync Engine                                            |
|  * Initial bulk load via paginated JQL                              |
|  * Incremental sync via updated timestamp                           |
|  * Change detection via content hashing                             |
+---------------------------------------------------------------------+
```

## Technology Choices

### Vector Store: LanceDB

| Criteria | LanceDB | ChromaDB |
|----------|---------|----------|
| **Storage** | Columnar (Lance format) - 10x efficient | SQLite + Parquet |
| **Hybrid Search** | Native FTS + vector | Requires external BM25 |
| **Self-Query** | Built-in metadata filtering | Limited filtering |
| **Zero Config** | Single directory, no server | Optional server mode |
| **Scale** | Billions of vectors on disk | Memory-bound |
| **License** | Apache 2.0, fully embeddable | Apache 2.0 |

### Embedding Models

| Model | Dims | Cost | Quality | Use Case |
|-------|------|------|---------|----------|
| **text-embedding-3-small** | 1536 | $0.02/1M | Good | Default choice |
| Cohere embed-v3 | 1024 | $0.10/1M | Excellent | On-prem option |
| **nomic-embed-text** | 768 | Free | Good | Fully offline |

**Recommendation**: Default to `text-embedding-3-small`, support swap to local `nomic-embed-text` for air-gapped deployments.

## Data Model

### LanceDB Schema: `jira_issues`

```python
class JiraIssueEmbedding(LanceModel):
    # Identity
    issue_id: str          # PROJ-123
    project_key: str       # PROJ

    # Embedding (1536 for OpenAI)
    vector: Vector(1536)

    # Core text (stored for FTS)
    summary: str
    description_preview: str  # First 500 chars

    # Filterable metadata
    issue_type: str        # Bug, Story, Task, Epic
    status: str            # Open, In Progress, Done
    status_category: str   # To Do, In Progress, Done
    priority: Optional[str]
    assignee: Optional[str]
    reporter: str
    labels: list[str]
    components: list[str]

    # Temporal
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    # Relationships
    parent_key: Optional[str]
    linked_issues: list[str]

    # Sync metadata
    content_hash: str          # For change detection
    embedding_version: str     # Model version
    indexed_at: datetime
```

### LanceDB Schema: `jira_comments`

```python
class JiraCommentEmbedding(LanceModel):
    comment_id: str
    issue_key: str
    vector: Vector(1536)

    body_preview: str      # First 300 chars
    author: str
    created_at: datetime

    # Denormalized from parent issue
    project_key: str
    issue_type: str
    issue_status: str
```

## MCP Tools

### Token Budget Strategy

| Tool | Typical Tokens | Purpose |
|------|----------------|---------|
| `jira_semantic_search` | 500-800 | Find by meaning |
| `jira_knowledge_query` | 600-1000 | Natural language + auto-filters |
| `jira_find_similar` | 400-600 | Related issues |
| `jira_detect_duplicates` | 300-500 | Pre-creation check |
| `jira_project_insights` | 800-1200 | Aggregated patterns |

### Tool: `jira_semantic_search`

**Purpose**: Semantic search across Jira issues using natural language.

**Parameters**:
- `query` (str): Natural language search query
- `projects` (str, optional): Comma-separated project keys
- `issue_types` (str, optional): Filter by type
- `status_category` (str, optional): To Do, In Progress, Done
- `limit` (int, 1-20, default 10): Max results

**Response** (~500-800 tokens):
```json
{
  "query": "authentication failures",
  "total_matches": 12,
  "results": [
    {
      "key": "AUTH-456",
      "summary": "Login fails with invalid token error",
      "type": "Bug",
      "status": "Open",
      "score": 0.892
    }
  ],
  "hint": "Use jira_get_issue for full details"
}
```

### Tool: `jira_knowledge_query`

**Purpose**: Natural language query with automatic filter extraction (self-querying).

**Parameters**:
- `question` (str): Natural language question
- `limit` (int, 1-15, default 10): Max results

**Example**:
```
Input: "What authentication bugs were fixed last month?"

Parsed:
  - semantic_query: "authentication"
  - filters: {issue_type: "Bug", status: "Done", resolved_at: >30d ago}
```

### Tool: `jira_find_similar`

**Purpose**: Find semantically similar issues to a given issue.

**Parameters**:
- `issue_key` (str): Source issue key
- `limit` (int, 1-10, default 5): Max results
- `same_project_only` (bool, default false): Restrict to same project
- `exclude_linked` (bool, default true): Exclude already-linked issues

### Tool: `jira_detect_duplicates`

**Purpose**: Check for duplicates before creating a new issue.

**Parameters**:
- `summary` (str): Proposed issue summary
- `description` (str, optional): Proposed description
- `project` (str, optional): Target project
- `threshold` (float, 0.7-0.99, default 0.85): Similarity threshold

**Response**:
```json
{
  "proposed_summary": "Login page returns 500 error",
  "duplicate_check": {
    "threshold": 0.85,
    "potential_duplicates_found": 2
  },
  "candidates": [
    {
      "key": "AUTH-123",
      "summary": "500 error on login page after OAuth",
      "similarity": 0.94,
      "status": "Open",
      "recommendation": "Likely duplicate"
    }
  ],
  "verdict": "DUPLICATE_LIKELY"
}
```

### Tool: `jira_project_insights`

**Purpose**: Aggregated insights about project patterns.

**Parameters**:
- `project_key` (str): Project to analyze
- `insight_type` (str): common_themes, bug_patterns, velocity_trends

## Sync Engine

### Sync Modes

1. **Bootstrap**: Initial full sync of all issues
2. **Incremental**: Sync only issues updated since last sync
3. **Real-time** (optional): Webhook-triggered updates

### Sync Algorithm

```python
async def incremental_sync(projects, state):
    # JQL for changed issues
    jql = f"""
        project IN ({projects})
        AND updated >= '{state.last_issue_updated}'
        ORDER BY updated ASC
    """

    for issue in jira.search(jql):
        # Skip if content unchanged (hash match)
        if vector_store.get(issue.key).content_hash == hash(issue):
            continue

        # Embed and upsert
        embedding = await embed(prepare_for_embedding(issue))
        vector_store.upsert(issue_to_record(issue, embedding))

    state.last_sync_at = now()
```

### Change Detection

- **Content hash**: MD5 of summary + description + labels + status
- **Embedding version**: Track model version for re-embedding on upgrade
- **Deletion detection**: Compare indexed keys vs current project issues

## Embedding Strategy

### Content Preparation

```python
def prepare_issue_for_embedding(issue):
    parts = [
        f"Issue: {issue.summary}",
        f"Type: {issue.issue_type} in {issue.project_key}",
        f"Status: {issue.status}",
    ]

    if issue.labels:
        parts.append(f"Labels: {', '.join(issue.labels[:10])}")

    if issue.description:
        clean = clean_jira_markup(issue.description)
        parts.append(f"Description: {truncate(clean, 1000)}")

    return "\n".join(parts)
```

### Content Cleaning

- Remove code blocks (replace with `[code snippet]`)
- Remove images and attachments
- Convert user mentions to display names
- Strip URLs but keep link text
- Normalize whitespace

## Claude Code Integration

### Skills

| Skill | Purpose |
|-------|---------|
| `/jira-investigate` | Deep investigation with semantic context |
| `/jira-dedup` | Duplicate check workflow before creation |
| `/jira-knowledge` | Natural language knowledge queries |
| `/jira-standup` | Smart standup with related work context |

### MCP Configuration

```json
{
  "mcpServers": {
    "atlassian-vector": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/TerminalGravity/mcp-atlassian.git", "mcp-atlassian"],
      "env": {
        "VECTOR_EMBEDDING_PROVIDER": "openai",
        "VECTOR_DB_PATH": "${HOME}/.mcp-atlassian/lancedb",
        "VECTOR_SYNC_PROJECTS": "PROJ,ENG,PLATFORM",
        "MCP_MAX_RESPONSE_TOKENS": "2000"
      }
    }
  }
}
```

## Configuration

### Environment Variables

```bash
# Embedding provider
VECTOR_EMBEDDING_PROVIDER=openai  # openai, cohere, local
VECTOR_EMBEDDING_MODEL=text-embedding-3-small

# LanceDB storage
VECTOR_DB_PATH=./data/lancedb

# Sync
VECTOR_SYNC_ENABLED=true
VECTOR_SYNC_INTERVAL_MINUTES=30
VECTOR_SYNC_PROJECTS=PROJ,ENG,PLATFORM  # or "*" for all

# Self-query LLM
VECTOR_SELF_QUERY_MODEL=gpt-4o-mini

# Token optimization
MCP_MAX_RESPONSE_TOKENS=2000
MCP_COMPACT_RESPONSES=true
```

## Deployment

### Docker Compose

```yaml
services:
  mcp-atlassian:
    build: .
    volumes:
      - lancedb_data:/data/lancedb
    environment:
      - JIRA_URL=${JIRA_URL}
      - JIRA_API_TOKEN=${JIRA_API_TOKEN}
      - VECTOR_DB_PATH=/data/lancedb
      - MCP_MAX_RESPONSE_TOKENS=2000
    ports:
      - "8080:8080"

  sync-worker:
    build: .
    volumes:
      - lancedb_data:/data/lancedb
    command: ["python", "-m", "mcp_atlassian.sync", "--daemon"]

volumes:
  lancedb_data:
```

### CLI Commands

```bash
# Initial sync
mcp-atlassian vector sync --projects PROJ,ENG --full

# Check status
mcp-atlassian vector status

# Test search
mcp-atlassian vector search "authentication errors"

# Compact storage
mcp-atlassian vector compact
```

## Implementation Phases

### Phase 1: Foundation
- [ ] LanceDB integration with schema
- [ ] Embedding pipeline (OpenAI)
- [ ] Bootstrap sync from Jira
- [ ] Basic `jira_semantic_search` tool

### Phase 2: Self-Querying
- [ ] Self-query parser (LLM-based)
- [ ] `jira_knowledge_query` tool
- [ ] Hybrid search (vector + FTS)

### Phase 3: Intelligence
- [ ] `jira_find_similar` tool
- [ ] `jira_detect_duplicates` tool
- [ ] Incremental sync with change detection

### Phase 4: Insights
- [ ] `jira_project_insights` tool
- [ ] Pre-computed aggregations
- [ ] Comment indexing

### Phase 5: Polish
- [ ] Local embedding support (nomic)
- [ ] Claude Code skills
- [ ] CLI management commands
- [ ] Documentation

## Success Metrics

1. **Search quality**: >80% relevant results in top 5
2. **Duplicate detection**: >90% accuracy at 0.85 threshold
3. **Token efficiency**: <2000 tokens per search response
4. **Sync latency**: <30 min from Jira update to indexed
5. **Index freshness**: <5% stale issues at any time

## Performance Architecture (Columnar Storage Insights)

Based on [research into columnar vector storage](https://www.freecodecamp.org/news/how-to-integrate-vector-search-in-columnar-storage/), LanceDB's architecture provides key advantages:

### Why Columnar Works for Vector Search

1. **I/O Efficiency**: Reading embeddings accesses a single column, reducing I/O by ~10x vs row-oriented formats
2. **SIMD Optimization**: Columnar layout aligns with AVX-512 processing (16 floats per operation)
3. **Compression**: Partition-specific codebooks enable semantic-aware compression

### Hybrid Query Architecture

```
Query: "Find auth bugs from last month"
                    |
        +-----------+-----------+
        |                       |
   Vector Search           Metadata Filter
   (columnar scan)         (partition pruning)
        |                       |
        +-----------+-----------+
                    |
              Result Merge
              (score fusion)
```

### Performance Trade-offs

| Approach | Latency | Throughput | Best For |
|----------|---------|------------|----------|
| In-memory (Pinecone) | <100ms | Medium | Real-time search |
| **Embedded columnar (LanceDB)** | 100-500ms | High | Batch + interactive |
| Analytical (BigQuery) | 1-10s | Very High | Massive batch ops |

**Our choice**: LanceDB hits the sweet spot for MCP tools - fast enough for interactive use (<500ms), efficient enough for large Jira instances.

### Optimization Strategies

1. **Partition by project**: Enable partition pruning when project filter specified
2. **Pre-filter before vector scan**: Apply metadata filters first to reduce vector comparisons
3. **Batch embeddings**: Amortize API overhead across many issues
4. **Async background sync**: Decouple indexing from query path

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Embedding API costs | Medium | Batch requests, cache, local model option |
| Large Jira instances | High | Paginated sync, project filtering, partitioning |
| Stale data | Medium | Incremental sync, webhooks |
| Self-query misparse | Low | Fallback to pure semantic, show parsed query |
| Query latency spikes | Low | Partition pruning, result caching |

## Open Questions

1. **Confluence support**: Should we extend to Confluence pages in same index?
2. **Multi-tenant**: How to handle multiple Jira instances?
3. **Retention**: How long to keep embeddings for closed issues?
4. **Fine-tuning**: Should we support custom embedding models?

---

## Appendix: Self-Query Attribute Specification

```python
JIRA_ATTRIBUTE_INFO = [
    {"name": "project_key", "description": "Jira project key", "type": "string"},
    {"name": "issue_type", "description": "Bug, Story, Task, Epic", "type": "string"},
    {"name": "status", "description": "Open, In Progress, Done", "type": "string"},
    {"name": "status_category", "description": "To Do, In Progress, Done", "type": "string"},
    {"name": "priority", "description": "Highest, High, Medium, Low", "type": "string"},
    {"name": "assignee", "description": "Username or display name", "type": "string"},
    {"name": "labels", "description": "Issue labels/tags", "type": "list[string]"},
    {"name": "created_at", "description": "Issue creation date", "type": "datetime"},
    {"name": "updated_at", "description": "Last update date", "type": "datetime"},
]
```
