import { openai } from "@ai-sdk/openai"
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  streamText,
  tool,
  stepCountIs,
  convertToModelMessages,
  generateId,
  type UIMessage
} from "ai"
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

// Tool to get linked issues
async function getLinkedIssues(issueKey: string) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/linked-issues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ issueKey }),
    })
    if (!response.ok) {
      return { error: `Failed to get linked issues`, issues: [], count: 0 }
    }
    return response.json()
  } catch (error) {
    return { error: `Linked issues error: ${error}`, issues: [], count: 0 }
  }
}

// Generate contextual follow-up suggestions
function generateFollowUpSuggestions(responseText: string, lastUserMessage: string): string[] {
  const suggestions: string[] = []

  // Detect context from response
  const hasEpic = /epic/i.test(responseText) || /DS-\d+.*Epic/i.test(responseText)
  const hasBugs = /bug/i.test(responseText)
  const hasProject = /changemaker|rewardstack|marketplace/i.test(responseText)
  const hasAssignee = /assigned to|assignee/i.test(responseText)

  // Context-aware suggestions
  if (hasEpic || hasProject) {
    suggestions.push("Who's currently working on this?")
    suggestions.push("What's the current progress?")
  }

  if (hasBugs) {
    suggestions.push("Show me the open bugs")
    suggestions.push("What's blocking resolution?")
  }

  if (hasAssignee) {
    suggestions.push("Show their other open issues")
  }

  // Add generic useful suggestions
  if (suggestions.length < 3) {
    suggestions.push("Show me recent activity")
  }
  if (suggestions.length < 4) {
    suggestions.push("What are the blockers?")
  }

  return suggestions.slice(0, 4)
}

// Build the system prompt with research instructions
function buildSystemPrompt(currentUser: string): string {
  return `You are a Jira knowledge assistant for All Digital Rewards (ADR). You help users find information about Jira issues, past decisions, and project context.

## Current User Context
The user is role-playing as: **${currentUser}**
When queries mention "my issues", "assigned to me", or use currentUser(), use this person's name in JQL:
- Instead of \`assignee = currentUser()\`, use \`assignee = "${currentUser}"\`

## Tools Available
1. **semantic_search** - Natural language search across 400K+ indexed issues. ALWAYS WORKS.
2. **jql_search** - Direct Jira queries using JQL syntax. May return errors if Jira not connected.
3. **get_epic_children** - Get all child issues under an epic. USE THIS when you find an epic.
4. **get_linked_issues** - Get issues linked to a specific issue.

## RESEARCH BEHAVIOR - CRITICAL

You are a RESEARCH AGENT, not a simple search tool. You must dig deeper automatically.

### For "What is X?" or conceptual questions:
1. First search semantically for the concept
2. If you find an Epic, ALWAYS call get_epic_children to understand the full scope
3. If issues mention important linked items, call get_linked_issues
4. Synthesize a comprehensive answer from ALL gathered information

### For status/assignment questions:
1. Use jql_search with appropriate filters
2. Group results by status or priority in your response

### Multi-Step Research Pattern (USE THIS):
- Step 1: Initial semantic or JQL search to find the main topic
- Step 2: If Epic found → call get_epic_children
- Step 3: If important links mentioned → call get_linked_issues
- Step 4: Synthesize comprehensive answer

**NEVER stop at a single search when the user asks a broad question.**
**ALWAYS dig deeper to provide complete context.**

## Response Format

After ALL research is complete, provide:

1. **Direct answer** (1-2 sentences explaining the concept)

2. **Issues table** with clickable links:
| Issue | Summary | Status | Assignee |
|-------|---------|--------|----------|
| [DS-1234](https://alldigitalrewards.atlassian.net/browse/DS-1234) | Description | Status | Person |

3. **Key insights** (patterns, blockers, or notable findings)

## Search Strategy

**Use jql_search FIRST for:**
- "open bugs" → \`project = DS AND issuetype = Bug AND resolution = Unresolved ORDER BY updated DESC\`
- "my issues" → \`assignee = "${currentUser}" AND resolution = Unresolved ORDER BY updated DESC\`
- "recent updates" → \`project = DS AND updated >= -7d ORDER BY updated DESC\`
- "in progress" → \`project = DS AND status = "In Progress" ORDER BY updated DESC\`

**Use semantic_search FIRST for:**
- "What is X?" - conceptual questions
- "How does Y work?" - explanation questions
- "Issues related to Z" - topic-based discovery

## Error Handling
If a tool returns an error, fall back to semantic_search and continue.
ALWAYS provide a helpful response even if some tools fail.`
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

  // Get the last user message for suggestion context
  const lastUserMsg = messages.filter(m => m.role === "user").pop()
  const lastUserMessage = lastUserMsg?.parts
    ?.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map(p => p.text)
    .join('') || ""

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const result = streamText({
        model: openai(MODELS[modelId]),
        system: buildSystemPrompt(currentUser),
        messages: await convertToModelMessages(messages),
        tools: {
          semantic_search: tool({
            description: "Search Jira issues using natural language semantic search. Returns conceptually related issues.",
            inputSchema: z.object({
              query: z.string().describe("Natural language search query"),
              limit: z.number().default(10).describe("Max results to return"),
            }),
            execute: async ({ query, limit }) => {
              return await searchVectorStore(query, limit || 10)
            },
          }),

          jql_search: tool({
            description: "Search Jira issues using JQL syntax. Use for status/assignee queries.",
            inputSchema: z.object({
              jql: z.string().describe("JQL query string"),
              limit: z.number().default(10).describe("Max results to return"),
            }),
            execute: async ({ jql, limit }) => {
              return await searchJQL(jql, limit || 10)
            },
          }),

          get_epic_children: tool({
            description: "Get all child issues (stories, tasks, bugs) under an epic. ALWAYS use this when you find an epic to understand its full scope.",
            inputSchema: z.object({
              epicKey: z.string().describe("Epic issue key like DS-11641"),
            }),
            execute: async ({ epicKey }) => {
              // Use JQL to find epic children
              const jql = `"Epic Link" = ${epicKey} ORDER BY issuetype, status`
              return await searchJQL(jql, 50)
            },
          }),

          get_linked_issues: tool({
            description: "Get issues linked to a specific issue (blocks, is blocked by, relates to, etc.)",
            inputSchema: z.object({
              issueKey: z.string().describe("Issue key like DS-1234"),
            }),
            execute: async ({ issueKey }) => {
              return await getLinkedIssues(issueKey)
            },
          }),
        },
        stopWhen: stepCountIs(5),
        temperature: 0.3,
        onFinish: async ({ text }) => {
          // Generate and stream follow-up suggestions
          const suggestions = generateFollowUpSuggestions(text, lastUserMessage)
          if (suggestions.length > 0) {
            writer.write({
              type: 'data-suggestions',
              id: generateId(),
              data: { prompts: suggestions }
            })
          }
        }
      })

      // Merge the streamText result into our UIMessageStream
      writer.merge(result.toUIMessageStream())
    }
  })

  return createUIMessageStreamResponse({ stream })
}
