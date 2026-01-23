import { openai } from "@ai-sdk/openai"
import { streamText, tool, convertToModelMessages, type UIMessage } from "ai"
import { z } from "zod"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

// Tool to search vector store
async function searchVectorStore(query: string, limit: number = 10) {
  const response = await fetch(`${BACKEND_URL}/api/vector-search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit }),
  })
  if (!response.ok) {
    throw new Error("Vector search failed")
  }
  return response.json()
}

// Tool to search via JQL
async function searchJQL(jql: string, limit: number = 10) {
  const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jql, limit }),
  })
  if (!response.ok) {
    throw new Error("JQL search failed")
  }
  return response.json()
}

export async function POST(request: Request) {
  const { messages }: { messages: UIMessage[] } = await request.json()

  const result = streamText({
    model: openai("gpt-4o-mini"),
    system: `You are a Jira knowledge assistant for All Digital Rewards (ADR). You help users find information about Jira issues, past decisions, and project context.

You have access to tools to search the Jira knowledge base:
1. semantic_search - Use for natural language queries to find conceptually related issues
2. jql_search - Use for precise JQL queries when you need specific filters (project, status, assignee, labels, etc.)

IMPORTANT SEARCH STRATEGY:
- Always start with semantic_search for the user's query
- If the results mention a specific project or topic (like "Changemaker"), follow up with jql_search to find related issues in OTHER projects
- For example, if semantic search finds "Changemaker" in project AI, also search: text ~ "changemaker" AND project != AI
- Combine insights from both searches in your answer

When answering:
- Be concise but thorough
- Reference specific issue keys (e.g., DS-1234)
- Highlight key findings, assignees, and statuses
- If issues span multiple projects, explain the relationship
- When showing statistics, format numbers clearly`,
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
        description: "Search Jira issues using JQL (Jira Query Language). Use for precise filtering by project, status, assignee, labels, text search, etc.",
        inputSchema: z.object({
          jql: z.string().describe("JQL query string, e.g. 'project = DS AND text ~ \"changemaker\"'"),
          limit: z.number().describe("Max results to return, typically 10"),
        }),
        execute: async ({ jql, limit }) => {
          const results = await searchJQL(jql, limit || 10)
          return results
        },
      }),
    },
    maxSteps: 5,
  })

  return result.toUIMessageStreamResponse()
}
