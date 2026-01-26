# Agentic Jira Knowledge UI Design

> **Status**: Approved
> **Date**: 2026-01-26
> **Author**: Jack Felke + Claude

## Problem Statement

The current Jira Knowledge chat UI performs single-shot searches. When a user asks "What is Changemaker and what features are being developed?", the system:

1. Finds the epic (DS-11641)
2. Returns only that one result
3. Offers to search for more instead of doing it automatically

**Expected behavior**: The agent should automatically research deeper—fetching epic children, linked issues, and related context—then synthesize a comprehensive answer.

## Goals

1. **Streaming research log** - Show the agent's search process as it happens
2. **Multi-step depth** - Automatically follow epics, children, and links
3. **Interactive expansion** - Buttons to dig deeper on specific areas
4. **Suggested follow-ups** - Clickable prompts for natural conversation flow

## Technical Approach

### AI SDK 6 Patterns

Using the latest AI SDK 6.0.49 patterns:

- `createUIMessageStream` for custom data parts
- `writer.write()` for streaming `data-*` parts
- `writer.merge()` to combine with `streamText().toUIMessageStream()`
- `message.parts` iteration with `part.type` switching
- `part.state` tracking: `'partial'` → `'output-available'`

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ChatMessage                                          │    │
│  │  ├─ ResearchStep (tool-semantic_search)             │    │
│  │  ├─ ResearchStep (tool-get_epic_children)           │    │
│  │  ├─ MarkdownContent (text)                          │    │
│  │  └─ SuggestionChips (data-suggestions)              │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     API Route (route.ts)                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ createUIMessageStream                                │    │
│  │  ├─ streamText with tools                           │    │
│  │  │   ├─ semantic_search                             │    │
│  │  │   ├─ jql_search                                  │    │
│  │  │   ├─ get_epic_children (NEW)                     │    │
│  │  │   └─ get_linked_issues (NEW)                     │    │
│  │  ├─ writer.merge(result.toUIMessageStream())        │    │
│  │  └─ onFinish: writer.write(data-suggestions)        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Python Backend                           │
│  ├─ /api/vector-search (existing)                           │
│  ├─ /api/jql-search (existing)                              │
│  ├─ /api/epic-children (NEW)                                │
│  └─ /api/linked-issues (NEW)                                │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Details

### 1. Server Changes (`web/src/app/api/chat/route.ts`)

#### Use `createUIMessageStream`

```typescript
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  streamText,
  tool,
  convertToModelMessages,
  generateId,
  stepCountIs
} from "ai"
import { openai } from "@ai-sdk/openai"
import { z } from "zod"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

export async function POST(request: Request) {
  const { messages, model, currentUser } = await request.json()

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const result = streamText({
        model: openai(model),
        system: buildSystemPrompt(currentUser),
        messages: await convertToModelMessages(messages),
        tools: {
          semantic_search: tool({
            description: "Search Jira issues using natural language",
            inputSchema: z.object({
              query: z.string(),
              limit: z.number().default(10),
            }),
            execute: async ({ query, limit }) => searchVectorStore(query, limit),
          }),

          jql_search: tool({
            description: "Search using JQL syntax",
            inputSchema: z.object({
              jql: z.string(),
              limit: z.number().default(10),
            }),
            execute: async ({ jql, limit }) => searchJQL(jql, limit),
          }),

          get_epic_children: tool({
            description: "Get all child issues (stories, tasks, bugs) under an epic",
            inputSchema: z.object({
              epicKey: z.string().describe("Epic issue key like DS-11641"),
            }),
            execute: async ({ epicKey }) => getEpicChildren(epicKey),
          }),

          get_linked_issues: tool({
            description: "Get issues linked to a specific issue",
            inputSchema: z.object({
              issueKey: z.string().describe("Issue key like DS-1234"),
            }),
            execute: async ({ issueKey }) => getLinkedIssues(issueKey),
          }),
        },
        stopWhen: stepCountIs(5),
        onFinish: async ({ text }) => {
          // Generate contextual follow-up suggestions
          const suggestions = generateFollowUpSuggestions(text, messages)
          writer.write({
            type: 'data-suggestions',
            id: generateId(),
            data: { prompts: suggestions }
          })
        }
      })

      writer.merge(result.toUIMessageStream())
    }
  })

  return createUIMessageStreamResponse({ stream })
}
```

#### New Backend Helper Functions

```typescript
async function getEpicChildren(epicKey: string) {
  const jql = `"Epic Link" = ${epicKey} ORDER BY issuetype, status`
  return searchJQL(jql, 50)
}

async function getLinkedIssues(issueKey: string) {
  // Use the backend endpoint (to be created)
  const response = await fetch(`${BACKEND_URL}/api/linked-issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issueKey }),
  })
  return response.json()
}

function generateFollowUpSuggestions(response: string, messages: any[]): string[] {
  // Context-aware suggestions based on the response
  const suggestions: string[] = []

  // If we found an epic, suggest exploring it
  if (response.includes("Epic") || response.includes("epic")) {
    suggestions.push("Who's working on this?")
    suggestions.push("What's the current progress?")
  }

  // If we found bugs, suggest status check
  if (response.includes("Bug") || response.includes("bug")) {
    suggestions.push("Show me open bugs")
    suggestions.push("What's blocking these?")
  }

  // Generic useful follow-ups
  suggestions.push("Show me recent activity")
  suggestions.push("What are the blockers?")

  return suggestions.slice(0, 4) // Max 4 suggestions
}
```

#### Enhanced System Prompt

```typescript
function buildSystemPrompt(currentUser: string) {
  return `You are a Jira knowledge assistant for All Digital Rewards (ADR).

## Current User
Role-playing as: **${currentUser}**

## Research Behavior - CRITICAL

You are a RESEARCH AGENT, not a simple search tool. When answering questions:

### For "What is X?" questions:
1. First search semantically for the concept
2. If you find an Epic, ALWAYS call get_epic_children to understand the full scope
3. If issues mention linked items, call get_linked_issues for context
4. Synthesize a comprehensive answer from all gathered information

### For "My issues" or assignment questions:
1. Use jql_search with assignee = "${currentUser}"
2. Group by status and priority in your response

### Multi-Step Research Pattern:
- Step 1: Initial semantic or JQL search
- Step 2: Expand context (epic children, linked issues)
- Step 3: Synthesize comprehensive answer

NEVER stop at a single search when the user asks a broad question like "What is X?".
ALWAYS dig deeper to provide complete context.

## Response Format

After researching, provide:
1. Direct answer (1-2 sentences)
2. Table of relevant issues with links
3. Key insights or patterns noticed

| Issue | Summary | Status | Assignee |
|-------|---------|--------|----------|
| [DS-1234](https://alldigitalrewards.atlassian.net/browse/DS-1234) | Description | Status | Person |
`
}
```

### 2. Client Changes

#### Update `chat-message.tsx`

```tsx
"use client"

import type { UIMessage } from "ai"
import { motion } from "framer-motion"
import { Check, Loader2, Search, GitBranch, Link2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Streamdown } from "streamdown/react"

interface ChatMessageProps {
  message: UIMessage
  onSendMessage?: (text: string) => void
}

export function ChatMessage({ message, onSendMessage }: ChatMessageProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end py-2">
        <div className="bg-primary text-primary-foreground rounded-2xl px-4 py-2 max-w-[80%]">
          {message.parts.map((part, i) =>
            part.type === 'text' ? <span key={i}>{part.text}</span> : null
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="py-4">
      {message.parts.map((part, i) => {
        switch (part.type) {
          case 'text':
            return (
              <div key={i} className="prose prose-sm dark:prose-invert max-w-none">
                <Streamdown source="global" content={part.text} />
              </div>
            )

          case 'tool-semantic_search':
          case 'tool-jql_search':
          case 'tool-get_epic_children':
          case 'tool-get_linked_issues':
            return (
              <ResearchStep
                key={i}
                type={part.type}
                state={part.state}
                input={part.input}
                output={part.output}
              />
            )

          case 'data-suggestions':
            return (
              <SuggestionChips
                key={i}
                prompts={part.data.prompts}
                onSelect={onSendMessage}
              />
            )

          default:
            return null
        }
      })}
    </div>
  )
}
```

#### New Component: `ResearchStep`

```tsx
interface ResearchStepProps {
  type: string
  state: 'partial' | 'output-available'
  input: Record<string, any>
  output?: { count?: number; issues?: any[]; error?: string }
}

function ResearchStep({ type, state, input, output }: ResearchStepProps) {
  const isSearching = state !== 'output-available'
  const hasError = output?.error

  const config = {
    'tool-semantic_search': {
      icon: Search,
      label: `Searching: "${input?.query}"`,
    },
    'tool-jql_search': {
      icon: Search,
      label: `JQL: ${input?.jql?.slice(0, 40)}...`,
    },
    'tool-get_epic_children': {
      icon: GitBranch,
      label: `Fetching children of ${input?.epicKey}`,
    },
    'tool-get_linked_issues': {
      icon: Link2,
      label: `Getting links for ${input?.issueKey}`,
    },
  }[type] || { icon: Search, label: type }

  const Icon = config.icon
  const count = output?.count || output?.issues?.length

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      className="flex items-center gap-2 py-1.5 text-sm"
    >
      <div className="w-5 h-5 flex items-center justify-center">
        {isSearching ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
        ) : hasError ? (
          <span className="text-destructive">!</span>
        ) : (
          <Check className="w-3.5 h-3.5 text-green-500" />
        )}
      </div>

      <Icon className="w-3.5 h-3.5 text-muted-foreground" />

      <span className="text-muted-foreground">{config.label}</span>

      {!isSearching && count !== undefined && (
        <Badge variant="secondary" className="text-xs">
          {count} {count === 1 ? 'result' : 'results'}
        </Badge>
      )}

      {hasError && (
        <span className="text-xs text-destructive">{output.error}</span>
      )}
    </motion.div>
  )
}
```

#### New Component: `SuggestionChips`

```tsx
interface SuggestionChipsProps {
  prompts: string[]
  onSelect?: (text: string) => void
}

function SuggestionChips({ prompts, onSelect }: SuggestionChipsProps) {
  if (!prompts?.length || !onSelect) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="flex flex-wrap gap-2 mt-4 pt-4 border-t"
    >
      <span className="text-xs text-muted-foreground w-full mb-1">
        Continue exploring:
      </span>
      {prompts.map((prompt, i) => (
        <motion.button
          key={i}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1 * i }}
          onClick={() => onSelect(prompt)}
          className="px-3 py-1.5 text-sm rounded-full border
                     bg-background hover:bg-accent hover:border-accent-foreground/20
                     transition-colors"
        >
          {prompt}
        </motion.button>
      ))}
    </motion.div>
  )
}
```

### 3. Backend Changes (`server.py`)

Add new endpoint for linked issues:

```python
class LinkedIssuesRequest(BaseModel):
    """Get linked issues request."""
    issueKey: str


@app.post("/api/linked-issues")
async def get_linked_issues(request: LinkedIssuesRequest):
    """Get issues linked to a specific issue."""
    try:
        jira = get_jira()
        issue = jira.get_issue(request.issueKey)

        # Extract linked issue keys
        linked_keys = []
        if hasattr(issue, 'issuelinks') and issue.issuelinks:
            for link in issue.issuelinks:
                if hasattr(link, 'outwardIssue'):
                    linked_keys.append(link.outwardIssue.key)
                if hasattr(link, 'inwardIssue'):
                    linked_keys.append(link.inwardIssue.key)

        if not linked_keys:
            return {"issues": [], "count": 0}

        # Fetch linked issues
        jql = f"key in ({','.join(linked_keys)})"
        result = jira.search_issues(jql, limit=20)

        issues = [
            {
                "issue_id": issue.key,
                "summary": issue.summary,
                "status": issue.status.name if issue.status else "Unknown",
                "issue_type": issue.issue_type.name if issue.issue_type else "Unknown",
                "link_type": "linked",
            }
            for issue in result.issues
        ]

        return {"issues": issues, "count": len(issues)}

    except Exception as e:
        logger.warning(f"Linked issues error: {e}")
        return {"issues": [], "count": 0, "error": str(e)[:100]}
```

## Visual Design

### Research Log (Streaming)

```
┌─────────────────────────────────────────────────────────────┐
│ User: What is Changemaker and what features are developed?  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 🔍 Searching: "Changemaker project features"        ✓ 1     │
│ 🌿 Fetching children of DS-11641                    ✓ 12    │
│ 🔗 Getting links for DS-11641                       ✓ 2     │
│                                                             │
│ **Changemaker** is ADR's employee incentive platform...     │
│                                                             │
│ | Issue | Summary | Status | Assignee |                     │
│ |-------|---------|--------|----------|                     │
│ | DS-11641 | Launch Changemaker | Closed | Jack |           │
│ | DS-11650 | User Dashboard | Done | Stan |                 │
│ | DS-11655 | Points System | In Progress | Kim |            │
│ | ... | ... | ... | ... |                                   │
│                                                             │
│ ┌────────────────┐ ┌──────────────────┐ ┌────────────────┐  │
│ │ Who's working  │ │ Current progress │ │ Show blockers  │  │
│ │ on this?       │ │                  │ │                │  │
│ └────────────────┘ └──────────────────┘ └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Testing Plan

1. **Unit Tests**
   - `generateFollowUpSuggestions` returns appropriate suggestions
   - `ResearchStep` renders correctly for all tool types
   - `SuggestionChips` handles click events

2. **Integration Tests**
   - Multi-step tool execution completes within 5 steps
   - `data-suggestions` part appears after response
   - Epic children are fetched when epic is found

3. **E2E Tests**
   - "What is Changemaker?" triggers multi-step research
   - Clicking suggestion chip sends new message
   - Research steps animate smoothly

## Implementation Order

1. **Phase 1: Server Foundation**
   - [ ] Refactor `route.ts` to use `createUIMessageStream`
   - [ ] Add `get_epic_children` tool
   - [ ] Add `get_linked_issues` tool
   - [ ] Update system prompt with research instructions

2. **Phase 2: Client Components**
   - [ ] Create `ResearchStep` component
   - [ ] Create `SuggestionChips` component
   - [ ] Update `ChatMessage` to render new part types
   - [ ] Wire up `onSendMessage` for suggestion clicks

3. **Phase 3: Backend Endpoints**
   - [ ] Add `/api/linked-issues` endpoint
   - [ ] Test epic children JQL query

4. **Phase 4: Polish**
   - [ ] Add animations with Framer Motion
   - [ ] Implement collapsible research log
   - [ ] Add error states and fallbacks

## Risk Analysis

| Risk | Mitigation |
|------|------------|
| Too many API calls | `stepCountIs(5)` limits total steps |
| Slow responses | Research steps show progress immediately |
| LLM ignores instructions | Strong system prompt with examples |
| Suggestion quality | Start simple, iterate based on usage |

## Success Criteria

- User asks "What is Changemaker?" and sees automatic multi-step research
- Research steps stream in real-time with status indicators
- Comprehensive answer includes epic + children + links
- Suggested follow-ups appear and are clickable
- Total response time under 10 seconds for typical queries
