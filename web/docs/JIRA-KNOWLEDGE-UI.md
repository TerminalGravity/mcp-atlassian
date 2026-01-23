# Jira Knowledge UI - Sprint Status

> Single source of truth for the Jira Knowledge chat interface

## Current State

**Status:** MVP Complete
**Last Updated:** 2026-01-23
**Stack:** Next.js 16.1.4 + Vercel AI SDK v3 + FastAPI + LanceDB

## Screenshots

### Landing Page
![Landing Page](screenshots/jira-knowledge-landing.png)

### Search Results (Expanded)
![Search Results](screenshots/jira-knowledge-results.png)

### Search Results (Collapsed)
![Collapsed View](screenshots/jira-knowledge-collapsed.png)

## Features

### Completed

- [x] **Chat Interface** - Conversational UI with AI SDK v3 `useChat` hook
- [x] **Semantic Search** - Vector search via LanceDB embeddings
- [x] **JQL Search** - Direct Jira query support
- [x] **Tool Invocations** - Visible intermediate steps showing search progress
- [x] **Expand/Collapse** - Toggle visibility of tool results
- [x] **Stats Visualization** - Pie charts (By Status, By Type) and bar charts (By Project)
- [x] **Issue Cards** - Rich cards with status badges, assignees, and direct Jira links
- [x] **Starter Prompts** - Quick-start buttons for common queries
- [x] **Dark Theme** - Polished dark mode UI

### QC Results

| Query | Status | Results | Notes |
|-------|--------|---------|-------|
| What is Changemaker? | PASS | 4 issues | AI-3, AI-1, AI-4, DS-4636 - Shows stats charts |
| AI initiatives | PASS | 7 issues | AI-3, AI-5, AI-6, AI-1, AI-2, AI-4, DS-4636 - "+1 more" truncation |
| Open bugs | PASS | 1 issue | DS-4582 - No stats for single result |
| API integrations | PASS | 1 issue | DS-2461 - No stats for single result |
| Expand/Collapse toggle | PASS | - | Smooth animation, state persists |
| Stats charts | PASS | - | Pie/bar charts render for 4+ results |
| Issue links | PASS | - | Opens correct Jira URLs |

### Query Screenshots

#### Changemaker Query (4 results with stats)
![Changemaker Results](screenshots/jira-knowledge-results.png)

#### AI Initiatives (7 results with "+1 more")
![AI Initiatives](screenshots/ai-initiatives-results.png)

#### Open Bugs (1 result, no stats)
![Open Bugs](screenshots/open-bugs-results.png)

#### API Integrations (1 result)
![API Integrations](screenshots/api-integrations-results.png)

#### Collapsed State
![Collapsed](screenshots/jira-knowledge-collapsed.png)

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
                        │   gpt-4o-mini   │
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

## Known Issues

1. **Chart warnings** - Recharts logs width/height warnings on initial render (cosmetic only)
2. **No text response** - AI sometimes returns only tool results without summary text

## Next Sprint

- [ ] Add JQL search tool invocation UI
- [ ] Multi-turn conversation support
- [ ] Response streaming text
- [ ] Cross-project search (Changemaker + DS)
- [ ] Mobile responsive layout

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
