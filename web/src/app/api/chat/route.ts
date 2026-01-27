// web/src/app/api/chat/route.ts

import { openai } from "@ai-sdk/openai"
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  streamText,
  convertToModelMessages,
  generateId,
  type UIMessage
} from "ai"

import { executeResearchPipeline, buildResearchContext, type JiraIssue, type ResearchResult } from './research-pipeline'
import { buildEvalLogData, logEvaluation } from './eval-logger'

// Types for refinements (kept for backward compatibility)
interface Refinement {
  id: string
  label: string
  category: 'project' | 'time' | 'type' | 'priority' | 'status'
  filter: {
    field: string
    value: string
    operator: string
  }
  count?: number
}

interface RefinementsData {
  originalQuery: string
  totalResults: number
  refinements: Refinement[]
}

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

// Supported models
const MODELS = {
  "gpt-4.1": "gpt-4.1",
  "gpt-5.2": "gpt-5.2",
} as const

type ModelId = keyof typeof MODELS

// Output mode template from backend
interface OutputModeTemplate {
  id: string
  name: string
  display_name: string
  description: string
  system_prompt_sections: {
    formatting: string
    behavior?: string | null
    constraints?: string | null
  }
}

// Fetch output mode template from backend
async function fetchOutputMode(modeId: string): Promise<OutputModeTemplate | null> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/output-modes/${modeId}`)
    if (!response.ok) return null
    return await response.json()
  } catch {
    return null
  }
}

// Generate search refinements from issues
function generateSearchRefinements(issues: JiraIssue[], originalQuery: string): RefinementsData | null {
  if (issues.length < 3) return null

  const refinements: Refinement[] = []
  const MAX_REFINEMENT_CHIPS = 8

  // Group by project
  const projectCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.project_key) {
      projectCounts.set(issue.project_key, (projectCounts.get(issue.project_key) || 0) + 1)
    }
  }
  if (projectCounts.size >= 2) {
    for (const [project, count] of projectCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `project-${project}`,
          label: `${project} only (${count})`,
          category: 'project',
          filter: { field: 'project_key', value: project, operator: '$eq' },
          count
        })
      }
    }
  }

  // Group by status
  const statusCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.status) {
      statusCounts.set(issue.status, (statusCounts.get(issue.status) || 0) + 1)
    }
  }
  if (statusCounts.size >= 2) {
    for (const [status, count] of statusCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `status-${status.toLowerCase().replace(/\s+/g, '-')}`,
          label: `${status} (${count})`,
          category: 'status',
          filter: { field: 'status', value: status, operator: '$eq' },
          count
        })
      }
    }
  }

  // Group by type
  const typeCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.issue_type) {
      typeCounts.set(issue.issue_type, (typeCounts.get(issue.issue_type) || 0) + 1)
    }
  }
  if (typeCounts.size >= 2) {
    for (const [type, count] of typeCounts.entries()) {
      if (count >= 2) {
        const plural = type === 'Story' ? 'Stories' : `${type}s`
        refinements.push({
          id: `type-${type.toLowerCase().replace(/\s+/g, '-')}`,
          label: `${plural} (${count})`,
          category: 'type',
          filter: { field: 'issue_type', value: type, operator: '$eq' },
          count
        })
      }
    }
  }

  // Time refinements
  const timeRefinements = [
    { id: 'time-7d', label: 'Last 7 days', value: '-7d' },
    { id: 'time-30d', label: 'Last 30 days', value: '-30d' },
  ]
  for (const timeRef of timeRefinements) {
    refinements.push({
      id: timeRef.id,
      label: timeRef.label,
      category: 'time',
      filter: { field: 'updated', value: timeRef.value, operator: '>=' }
    })
  }

  if (refinements.length === 0) return null

  refinements.sort((a, b) => (b.count || 0) - (a.count || 0))
  return {
    originalQuery,
    totalResults: issues.length,
    refinements: refinements.slice(0, MAX_REFINEMENT_CHIPS)
  }
}

// Generate contextual follow-up suggestions
function generateFollowUpSuggestions(responseText: string, issues: JiraIssue[]): string[] {
  const suggestions: string[] = []

  // Find epics in results
  const epics = issues.filter(i => i.issue_type === 'Epic')
  if (epics.length > 0 && suggestions.length < 4) {
    suggestions.push(`Tell me more about ${epics[0].issue_id}`)
  }

  // Check for common patterns in response
  if (/blocker|blocked|blocking/i.test(responseText) && suggestions.length < 4) {
    suggestions.push("What are the current blockers?")
  }
  if (/in progress/i.test(responseText) && suggestions.length < 4) {
    suggestions.push("Show only open items")
  }
  if (/bug/i.test(responseText) && suggestions.length < 4) {
    suggestions.push("Show me open bugs")
  }

  // Generic useful follow-ups
  const fallbacks = [
    "What needs attention?",
    "Show recent activity",
    "Who should I talk to?",
  ]
  for (const fb of fallbacks) {
    if (suggestions.length < 4) {
      suggestions.push(fb)
    }
  }

  return suggestions.slice(0, 4)
}

// Build synthesis system prompt
function buildSynthesisPrompt(currentUser: string, outputMode?: OutputModeTemplate | null): string {
  let formatSection = `## Response Format

Provide a comprehensive answer based on ALL the research data:

1. **Direct answer** - A clear, concise explanation (1-3 paragraphs)
2. **Key insights** - Patterns, blockers, status breakdown, or notable findings

**IMPORTANT: Do NOT generate markdown tables listing issues.** The UI automatically displays all found issues in an expandable "Sources referenced" component. Reference specific issue keys inline when relevant (e.g., "The main blocker is DS-1234 which...").`

  if (outputMode?.system_prompt_sections) {
    const sections = outputMode.system_prompt_sections
    formatSection = `## Response Format (${outputMode.display_name})

${sections.formatting}
${sections.behavior ? `\n**Behavior**: ${sections.behavior}` : ""}
${sections.constraints ? `\n**Constraints**: ${sections.constraints}` : ""}

**IMPORTANT: Do NOT generate markdown tables listing issues unless your output mode explicitly requires it.**`
  }

  return `You are a Jira knowledge assistant for All Digital Rewards (ADR).

## Your Role
You are the SYNTHESIS phase of a research pipeline. The research has already been completed - you have been provided with ALL the gathered data. Your job is to analyze this data and provide a comprehensive, insightful answer.

## Current User
The user is: **${currentUser}**

${formatSection}

## Guidelines
- Focus on insights and patterns, not just listing what was found
- Reference specific issue keys when they're important (e.g., DS-1234)
- Highlight blockers, risks, or items needing attention
- Be helpful and actionable
- If the research found limited results, acknowledge this and suggest alternatives`
}

export async function POST(request: Request) {
  const body = await request.json()
  const messages: UIMessage[] = body.messages || []
  const modelId: ModelId = body.model && body.model in MODELS ? body.model : "gpt-4.1"
  const currentUser: string = body.currentUser || "Josh Houghtelin"
  const outputModeId: string | null = body.outputModeId || null

  if (!messages || messages.length === 0) {
    return new Response(
      JSON.stringify({ error: "No messages provided" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    )
  }

  // Fetch output mode template if provided
  let outputMode: OutputModeTemplate | null = null
  if (outputModeId) {
    outputMode = await fetchOutputMode(outputModeId)
  }

  // Get the last user message
  const lastUserMsg = messages.filter(m => m.role === "user").pop()
  const lastUserMessage = lastUserMsg?.parts
    ?.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
    .map(p => p.text)
    .join('') || ""

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      // =====================================================
      // PHASE 1-3: FORCED RESEARCH PIPELINE
      // This ALWAYS runs multiple searches - no AI discretion
      // =====================================================
      console.log('[Chat] Starting forced research pipeline for:', lastUserMessage)

      const researchResult = await executeResearchPipeline(
        lastUserMessage,
        currentUser,
        writer
      )

      console.log('[Chat] Research complete:', {
        phases: researchResult.phases.length,
        totalIssues: researchResult.allIssues.length,
        classification: researchResult.classification.type,
      })

      // =====================================================
      // PHASE 4: AI SYNTHESIS
      // The AI ONLY synthesizes - it cannot choose to skip research
      // =====================================================
      const researchContext = buildResearchContext(researchResult)

      // Build the synthesis messages
      const synthesisMessages = await convertToModelMessages(messages)

      // Add the research context as a system message
      const messagesWithContext = [
        ...synthesisMessages.slice(0, -1), // All but last user message
        {
          role: 'user' as const,
          content: `${lastUserMessage}

---

## Research Results (automatically gathered)

${researchContext}`
        }
      ]

      const result = streamText({
        model: openai(MODELS[modelId]),
        system: buildSynthesisPrompt(currentUser, outputMode),
        messages: messagesWithContext,
        temperature: 0.3,
      })

      // Stream the AI synthesis text using text-delta type
      let fullText = ''
      for await (const textPart of result.textStream) {
        fullText += textPart
        writer.write({ type: 'text-delta', id: generateId(), delta: textPart })
      }

      // Generate and emit refinements after synthesis completes
      const refinementsData = generateSearchRefinements(researchResult.allIssues, lastUserMessage)
      if (refinementsData) {
        writer.write({
          type: 'data-refinements',
          id: generateId(),
          data: refinementsData
        })
      }

      // Generate and emit follow-up suggestions
      const suggestions = generateFollowUpSuggestions(fullText, researchResult.allIssues)
      if (suggestions.length > 0) {
        writer.write({
          type: 'data-suggestions',
          id: generateId(),
          data: { prompts: suggestions }
        })
      }

      // Log this turn for evaluation (async, don't block response)
      const conversationId = body.conversationId || generateId()
      const turnIndex = messages.filter(m => m.role === 'user').length
      const evalData = buildEvalLogData(
        conversationId,
        turnIndex,
        lastUserMessage,
        researchResult,
        fullText,
        modelId,
        outputModeId
      )
      logEvaluation(evalData).catch(err => {
        console.error('[Chat] Eval logging error:', err)
      })
    }
  })

  return createUIMessageStreamResponse({ stream })
}
