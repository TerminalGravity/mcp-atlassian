# Web UI Dashboard Design

## Overview

Expand the Jira Knowledge web UI with Dashboard and My Work pages, leveraging AI SDK 6 for streaming insights and contextual AI assistance.

**Primary Audience:** Developers at ADR, accessible to everyone
**MVP Scope:** Staged - Dashboard + My Work first, Project Explorer later

## App Structure

```
/                 → Chat (existing Jira Knowledge interface - home page)
/dashboard        → Dashboard with AI-generated insights
/my-work          → My Work (user's issues + embedded AI)
```

## Navigation & Layout

### Shared Navigation
- Top navigation bar: Logo | Chat | Dashboard | My Work | UserSelector
- User selector is global (role-play dropdown) - affects Dashboard and My Work
- Consistent styling across all pages (Tailwind dark mode support)

### State Management
- `currentUser` stored in React context, persisted to localStorage
- URL can override: `/my-work?user=Josh%20Houghtelin`
- Passed to all API routes automatically

## Page Designs

### Dashboard (`/dashboard`)

**Purpose:** AI-generated overview of "what needs attention" - runs multi-step research on page load.

```
┌─────────────────────────────────────────────────────┐
│  Nav: Chat | Dashboard | My Work      [User: Josh]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  🔄 Analyzing your Jira landscape...                │
│  ├─ ✓ Checking open blockers                        │
│  ├─ ✓ Finding stale issues                          │
│  └─ ⏳ Reviewing sprint progress                    │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ## What Needs Attention                            │
│  [AI-generated summary streams in here]             │
│                                                     │
│  ### Blockers (3)                  ### Stale (5)    │
│  ┌──────────────────┐              ┌──────────────┐ │
│  │ DS-1234 Summary  │              │ DS-5678 ...  │ │
│  │ DS-1235 Summary  │              │ DS-5679 ...  │ │
│  └──────────────────┘              └──────────────┘ │
│                                                     │
│  ### Sprint Progress                                │
│  [Progress bar / mini chart]                        │
│                                                     │
│  [Suggestion chips: "Show all blockers" | ...]      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Behavior:**
1. On page load, triggers API call with predefined research prompt
2. AI runs 3-4 tool calls: blockers query, stale issues, sprint status
3. Research steps show with collapsible UI (reuse existing components)
4. AI streams a summary with categorized issues
5. Suggestion chips for drill-down actions

### My Work (`/my-work`)

**Purpose:** Personal issue tracker for selected user, with embedded AI assistant.

```
┌─────────────────────────────────────────────────────┐
│  Nav: Chat | Dashboard | My Work      [User: Josh]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ## My Work                                         │
│  ┌─────────────────────────────────────────────────┐│
│  │ Tabs: In Progress (4) | To Do (7) | Done (12)  ││
│  └─────────────────────────────────────────────────┘│
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │ DS-1234  Fix payment retry logic     In Progress││
│  │ DS-1235  Add webhook validation      In Progress││
│  │ DS-1236  Update API docs             In Progress││
│  │ DS-1237  Review PR #456              In Progress││
│  └─────────────────────────────────────────────────┘│
│                                                     │
├─────────────────────────────────────────────────────┤
│  💬 Ask about your work...                          │
│  ┌─────────────────────────────────────────────────┐│
│  │ "What's blocking me?" "Summarize my sprint"    ││
│  └─────────────────────────────────────────────────┘│
│  [Chat input - scoped to this user's issues]        │
└─────────────────────────────────────────────────────┘
```

**Features:**
1. Issue list fetched via JQL: `assignee = "{currentUser}" ORDER BY status, updated`
2. Tab filtering: In Progress / To Do / Done with counts
3. Issue cards: Click to expand or link to Jira
4. Embedded AI chat pre-scoped to user's issues
   - Starter prompts: "What's blocking me?" / "Summarize my sprint" / "What should I work on next?"

## Technical Implementation

### New Files

```
web/src/
├── app/
│   ├── layout.tsx          # Update: wrap with UserProvider
│   ├── page.tsx            # Existing chat (no changes)
│   ├── dashboard/
│   │   └── page.tsx        # New: Dashboard page
│   └── my-work/
│       └── page.tsx        # New: My Work page
├── components/
│   ├── layout/
│   │   ├── nav.tsx         # New: Top navigation
│   │   └── user-selector.tsx # New: Role-play dropdown
│   ├── dashboard/
│   │   └── dashboard-insights.tsx  # New: AI insights component
│   └── my-work/
│       ├── issue-list.tsx  # New: Tabbed issue list
│       └── my-work-chat.tsx # New: Scoped chat embed
├── contexts/
│   └── user-context.tsx    # New: Global user state
└── api/
    ├── chat/route.ts       # Existing (minor updates)
    ├── dashboard/route.ts  # New: Dashboard insights endpoint
    └── my-work/route.ts    # New: Fetch user's issues
```

### Reused Components
- `ResearchSteps`, `ToolInvocation` - Dashboard loading state
- `Sources`, `Reasoning` - AI responses
- `SuggestionChips` - Follow-up actions
- `ChatInput`, `ChatMessage` - Embedded chat on My Work

### API Endpoints
- `POST /api/dashboard` - Triggers AI research for dashboard insights
- `GET /api/my-work?user=X` - Returns user's issues via JQL

### Dependencies
No new packages - built on existing AI SDK 6 + shadcn/ui.

## Phase 2 (Future)

- Project Explorer page (`/projects`)
- More dashboard widgets (velocity charts, team view)
- Notifications/alerts
- Mobile-optimized views

## Success Criteria

1. Dashboard loads and streams AI insights within 5 seconds
2. My Work shows correct issues for selected user
3. Embedded chat on My Work is context-aware
4. Navigation feels cohesive across all pages
