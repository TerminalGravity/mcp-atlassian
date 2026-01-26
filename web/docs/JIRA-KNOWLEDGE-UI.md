# Jira Knowledge UI - Sprint Status

> Single source of truth for the Jira Knowledge chat interface

## Current State

**Status:** MVP Complete - P0 Issues Fixed
**Last Updated:** 2026-01-23
**Stack:** Next.js 16.1.4 + Vercel AI SDK v3 + FastAPI + LanceDB
**Model:** GPT-4.1 (upgraded from gpt-4o-mini for better tool use)

## Screenshots

### Landing Page
![Landing Page](screenshots/jira-knowledge-landing.png)

### Search Results with AI Summary
![Search Results](screenshots/jira-knowledge-results.png)

### Search Results (Collapsed)
![Collapsed View](screenshots/jira-knowledge-collapsed.png)

## Features

### Completed

- [x] **Chat Interface** - Conversational UI with AI SDK v3 `useChat` hook
- [x] **Semantic Search** - Vector search via LanceDB embeddings
- [x] **JQL Search** - Direct Jira query support with graceful error handling
- [x] **Tool Invocations** - Visible intermediate steps showing search progress
- [x] **Expand/Collapse** - Toggle visibility of tool results
- [x] **Stats Visualization** - Pie charts (By Status, By Type) and bar charts (By Project)
- [x] **Issue Cards** - Rich cards with status badges, assignees, and direct Jira links
- [x] **Starter Prompts** - Quick-start buttons for common queries
- [x] **Dark Theme** - Polished dark mode UI
- [x] **AI Text Responses** - Model generates explanatory text after tool calls
- [x] **Error State UI** - Visual feedback for failed searches with suggestions

### QC Results - Post P0 Fixes

| Query | Results | Verdict | Notes |
|-------|---------|---------|-------|
| What is Changemaker? | 6 | PASS | AI explains project purpose, references issues |
| Recent activity | 1 | PASS | AI acknowledges limitation, suggests JQL alternative |
| Open bugs | 1 | PASS | AI notes only closed bugs found, offers suggestions |
| AI initiatives | 5+ | PASS | AI summarizes AI project initiatives |
| Team workload | 1 | PASS | AI explains limited results, suggests alternatives |
| API integrations | 1+ | PASS | AI provides context on results |

### UI Components Working

| Component | Status | Notes |
|-----------|--------|-------|
| Expand/Collapse | PASS | Smooth animation, state persists |
| Stats charts | PASS | Renders for 3+ results |
| Issue cards | PASS | Links work, status badges display |
| Starter prompts | PASS | Buttons trigger queries |
| AI text response | PASS | Model generates helpful summaries |
| Error handling | PASS | Graceful fallback to semantic search |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Next.js UI    │────>│  FastAPI        │────>│   LanceDB       │
│   (AI SDK v3)   │     │  /api/*         │     │   Vector Store  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │
        │                       v
        │               ┌─────────────────┐
        └──────────────>│   OpenAI        │
                        │   GPT-4.1       │
                        └─────────────────┘
```

## Key Files

| File | Purpose |
|------|---------|
| `web/src/app/api/chat/route.ts` | AI SDK streaming endpoint with tools |
| `web/src/components/chat/chat-container.tsx` | Main chat component |
| `web/src/components/chat/chat-message.tsx` | Message rendering with tool invocations |
| `src/mcp_atlassian/web/server.py` | FastAPI backend with search endpoints |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | AI SDK streaming chat |
| `/api/vector-search` | POST | Semantic search |
| `/api/jql-search` | POST | JQL search |
| `/api/health` | GET | Health check |

## P0 Fixes Completed

### 1. AI Text Responses (FIXED)
- **Problem:** Model stopped after tool calls without generating text
- **Solution:**
  - Upgraded to GPT-4.1 for better agentic behavior
  - Changed `maxSteps: 5` to `stopWhen: stepCountIs(5)` per AI SDK v3 API
  - Strengthened system prompt with explicit requirements for text responses

### 2. JQL Search Errors (FIXED)
- **Problem:** JQL search returned 500 error when Jira not configured
- **Solution:**
  - Tool functions now return structured error objects instead of throwing
  - Error objects include `error`, `issues: []`, `count: 0`, `suggestion`
  - Model gracefully falls back to semantic_search when JQL fails

### 3. Error State UI (FIXED)
- **Problem:** Silent failures showed no feedback to user
- **Solution:**
  - Added error detection in ToolInvocation component
  - Red "Error" badge displays when tool returns error
  - Error message and suggestion displayed in UI
  - AlertCircle icon for visual feedback

## Remaining Issues (P1/P2)

### P1 - Major
- **Search relevance** - Vector search doesn't understand status filters
- **No descriptions** - Issue cards show title/assignee but no context

### P2 - Minor
- **Chart dimension warnings** - Recharts logs width(-1) errors on render
- **No issue type icons** - Bug vs Task vs Initiative not visually distinct

## Running Locally

```bash
# Backend
cd /Users/jack/Developer/mcp-atlassian
source .venv/bin/activate
python -m uvicorn mcp_atlassian.web.server:app --host 0.0.0.0 --port 8000

# Frontend
cd web
npm run dev
```

Open http://localhost:3000
