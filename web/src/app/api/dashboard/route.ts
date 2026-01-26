import { openai } from "@ai-sdk/openai"
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  streamText,
  tool,
  stepCountIs,
} from "ai"
import { z } from "zod"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

// Tool to search vector store
async function searchVectorStore(query: string, limit: number = 10) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/vector-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit }),
    })
    if (!response.ok) {
      return { error: `Search failed with status ${response.status}`, issues: [], count: 0 }
    }
    return response.json()
  } catch (error) {
    return { error: `Search error: ${error}`, issues: [], count: 0 }
  }
}

// Tool to search via JQL
async function searchJQL(jql: string, limit: number = 10) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      return {
        error: "JQL search unavailable",
        issues: [],
        count: 0,
        suggestion: "Use semantic_search instead"
      }
    }
    return response.json()
  } catch (error) {
    return {
      error: `JQL search error: ${error}`,
      issues: [],
      count: 0,
      suggestion: "Use semantic_search instead"
    }
  }
}

function buildDashboardPrompt(currentUser: string): string {
  return `You are analyzing Jira for ${currentUser} to create a dashboard overview.

## Your Task
Analyze the Jira landscape and provide a "What Needs Attention" summary for ${currentUser}.

## Research Steps (do all of these automatically)
1. **Find blockers** - Issues blocking work or marked as blockers
2. **Find stale issues** - Issues assigned to ${currentUser} not updated in 14+ days
3. **Check sprint status** - Current sprint issues for ${currentUser}

## Tools Available
- semantic_search: Natural language search across all issues
- jql_search: JQL queries for precise filtering

## Response Format
After researching, provide:

### Summary
A 1-2 sentence overview of the current state.

### Blockers (if any)
| Issue | Summary | Status |
|-------|---------|--------|
| [DS-XXX](https://alldigitalrewards.atlassian.net/browse/DS-XXX) | ... | ... |

### Stale Issues (if any)
Issues not updated recently that need attention.

### Sprint Progress
Current sprint items and their status.

### Recommended Actions
1-3 actionable next steps for ${currentUser}.

Be concise and actionable. Focus on what needs immediate attention.`
}

export async function POST(request: Request) {
  const body = await request.json()
  const currentUser: string = body.currentUser || "Josh Houghtelin"

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const result = streamText({
        model: openai("gpt-4.1"),
        system: buildDashboardPrompt(currentUser),
        messages: [{ role: "user", content: "Analyze my Jira landscape and tell me what needs attention today." }],
        tools: {
          semantic_search: tool({
            description: "Search Jira issues using natural language semantic search.",
            inputSchema: z.object({
              query: z.string().describe("Natural language search query"),
              limit: z.number().default(10).describe("Max results"),
            }),
            execute: async ({ query, limit }) => {
              return await searchVectorStore(query, limit || 10)
            },
          }),

          jql_search: tool({
            description: "Search Jira issues using JQL syntax.",
            inputSchema: z.object({
              jql: z.string().describe("JQL query string"),
              limit: z.number().default(10).describe("Max results"),
            }),
            execute: async ({ jql, limit }) => {
              return await searchJQL(jql, limit || 10)
            },
          }),
        },
        stopWhen: stepCountIs(5),
        temperature: 0.3,
      })

      writer.merge(result.toUIMessageStream())
    }
  })

  return createUIMessageStreamResponse({ stream })
}
