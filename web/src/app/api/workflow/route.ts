import { openai } from "@ai-sdk/openai"
import { streamText, tool, stepCountIs } from "ai"
import { z } from "zod"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

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

async function searchJQL(jql: string, limit: number = 10) {
  try {
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      return { error: "JQL search unavailable", issues: [], count: 0 }
    }
    return response.json()
  } catch (error) {
    return { error: `JQL search error: ${error}`, issues: [], count: 0 }
  }
}

function buildWorkflowPrompt(workflow: string, currentUser: string): string {
  const base = `You are a Jira analyst for ${currentUser} at ADR.`

  const prompts: Record<string, string> = {
    priorities: `${base}

Based on the user's current issues, provide a prioritized list of what to work on today.
Consider:
- Blockers that are preventing progress
- Items that are close to completion
- Items with upcoming deadlines
- Dependencies between issues

Be specific about which issues to focus on and why.`,

    blockers: `${base}

Analyze blockers affecting the user's work:
- What issues are marked as blockers or blocked?
- What's causing the blocks?
- What actions can be taken to unblock?

Provide actionable recommendations.`,

    "sprint-health": `${base}

Assess the current sprint health:
- How many items are in progress vs done vs to-do?
- Are there any items at risk?
- What's the velocity looking like?

Provide a brief health summary with any concerns.`,
  }

  return prompts[workflow] || base
}

export async function POST(request: Request) {
  const body = await request.json()
  const workflow: string = body.workflow || "priorities"
  const currentUser: string = body.currentUser || "Josh Houghtelin"
  const prompt: string = body.prompt || "Analyze my work and provide insights."

  const result = streamText({
    model: openai("gpt-4.1"),
    system: buildWorkflowPrompt(workflow, currentUser),
    messages: [{ role: "user", content: prompt }],
    tools: {
      semantic_search: tool({
        description: "Search Jira issues using natural language.",
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

  return result.toTextStreamResponse()
}
