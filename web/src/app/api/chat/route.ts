import { openai } from "@ai-sdk/openai"
import { streamText, tool, stepCountIs, convertToModelMessages, type UIMessage } from "ai"
import { z } from "zod"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

// Supported models
const MODELS = {
  "gpt-4.1": "gpt-4.1",
  "gpt-5.2": "gpt-5.2",
} as const

type ModelId = keyof typeof MODELS

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

// Tool to search via JQL - returns graceful error if backend not configured
async function searchJQL(jql: string, limit: number = 10) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      // Return structured error instead of throwing
      return {
        error: "JQL search unavailable - Jira connection not configured",
        issues: [],
        count: 0,
        suggestion: "Use semantic_search instead for now"
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

export async function POST(request: Request) {
  const body = await request.json()
  const messages: UIMessage[] = body.messages || []
  const modelId: ModelId = body.model && body.model in MODELS ? body.model : "gpt-4.1"
  const currentUser: string = body.currentUser || "Josh Houghtelin"

  if (!messages || messages.length === 0) {
    return new Response(
      JSON.stringify({ error: "No messages provided" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    )
  }

  const result = streamText({
    model: openai(MODELS[modelId]),
    system: `You are a Jira knowledge assistant for All Digital Rewards (ADR). You help users find information about Jira issues, past decisions, and project context.

## Current User Context
The user is role-playing as: **${currentUser}**
When queries mention "my issues", "assigned to me", or use currentUser(), use this person's name in JQL:
- Instead of \`assignee = currentUser()\`, use \`assignee = "${currentUser}"\`

## Tools Available
1. **semantic_search** - Natural language search across 400K+ indexed issues. ALWAYS WORKS. Use this first.
2. **jql_search** - Direct Jira queries using JQL syntax. May return errors if Jira not connected.

## ABSOLUTE REQUIREMENTS - NEVER SKIP THESE

### 1. YOU MUST ALWAYS WRITE A TEXT RESPONSE
After EVERY search, you MUST write a helpful text response. This is NOT optional.
- If you find results: Summarize what you learned and answer the question
- If you find nothing: Say so and suggest alternatives
- If there's an error: Explain it and offer to try semantic_search instead

### 2. ANSWER THE ACTUAL QUESTION
Users ask questions like "What is Changemaker?" - they want an EXPLANATION, not just a list of issues.
- Read the issue summaries and descriptions
- Synthesize an answer that explains the concept/project/feature
- Reference specific issues as evidence (e.g., "According to DS-1234...")

### 3. HANDLE ERRORS GRACEFULLY
If a tool returns an error field:
- Acknowledge the error briefly
- Suggest using semantic_search as a fallback
- Never leave the user without a helpful response

## Response Template

ALWAYS respond in this format after searching:

"[Direct answer to their question in 1-2 sentences]

| Issue | Summary | Status | Assignee |
|-------|---------|--------|----------|
| [DS-1234](https://alldigitalrewards.atlassian.net/browse/DS-1234) | Brief description | Status | Person |
| [DS-5678](https://alldigitalrewards.atlassian.net/browse/DS-5678) | Brief description | Status | Person |

[Optional: Additional context, patterns noticed, or key insights]"

## Search Strategy

### CRITICAL: Choose the RIGHT tool for the query type

**Use jql_search FIRST for these queries:**
- "open bugs" → \`project = DS AND issuetype = Bug AND resolution = Unresolved ORDER BY updated DESC\`
- "my issues" → \`project = DS AND assignee = "${currentUser}" AND resolution = Unresolved\`
- "recent updates" → \`project = DS AND updated >= -7d ORDER BY updated DESC\`
- "in progress" → \`project = DS AND status = "In Progress" ORDER BY updated DESC\`
- Any query asking about STATUS (open, closed, in progress, etc.)

**Use semantic_search FIRST for these queries:**
- "What is X?" - conceptual questions
- "How does Y work?" - explanation questions
- "Issues related to Z" - topic-based discovery
- Any query asking about CONTENT or CONCEPTS

### Fallback Strategy
1. If jql_search returns an error, fall back to semantic_search
2. If semantic_search returns no results, try a broader query
3. ALWAYS provide a text response after searching`,
    messages: await convertToModelMessages(messages),
    tools: {
      semantic_search: tool({
        description: "Search Jira issues using natural language semantic search. Returns conceptually related issues.",
        inputSchema: z.object({
          query: z.string().describe("Natural language search query"),
          limit: z.number().describe("Max results to return, typically 10"),
        }),
        execute: async ({ query, limit }) => {
          const results = await searchVectorStore(query, limit || 10)
          return results
        },
      }),
      jql_search: tool({
        description: "Search Jira issues using JQL. NOTE: May be unavailable if Jira not connected - check for errors in response.",
        inputSchema: z.object({
          jql: z.string().describe("JQL query string, e.g. 'project = DS AND status = Open'"),
          limit: z.number().describe("Max results to return, typically 10"),
        }),
        execute: async ({ jql, limit }) => {
          const results = await searchJQL(jql, limit || 10)
          return results
        },
      }),
    },
    stopWhen: stepCountIs(5),  // Allow up to 5 steps for multi-step tool use
    temperature: 0.3,  // Lower temperature for more consistent responses
  })

  return result.toUIMessageStreamResponse()
}
