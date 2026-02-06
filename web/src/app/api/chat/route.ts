// web/src/app/api/chat/route.ts
// Research Pipeline v2 - Layered Architecture with Context Engineering

import { openai } from "@ai-sdk/openai"
import {
  streamText,
  convertToModelMessages,
  generateId,
  createUIMessageStream,
  createUIMessageStreamResponse,
  type UIMessage
} from "ai"

// New layered pipeline imports
import { analyzeQuery } from './query-analyzer'
import { routeQuery, describeRoute } from './query-router'
import { executeRetrievers } from './retrievers'
import { assembleContext, type UIData } from './context-assembler'
import { buildSynthesisPrompt } from './synthesis-prompts'
import type { QueryAnalysis, JiraIssue, RetrieverResult } from './types/query-analysis'

// Legacy imports for backward compatibility
import { buildEvalLogData, logEvaluation } from './eval-logger'

// Types for refinements
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
function generateFollowUpSuggestions(
  responseText: string,
  issues: JiraIssue[],
  analysis: QueryAnalysis
): string[] {
  const suggestions: string[] = []

  // Analytical query follow-ups
  if (analysis.intent === 'analytical') {
    if (analysis.analyticalParams?.groupBy?.includes('status')) {
      suggestions.push("Show me the open issues")
    }
    if (analysis.analyticalParams?.groupBy?.includes('assignee')) {
      suggestions.push("Who has the most bugs?")
    }
    suggestions.push("Show the trend over time")
  }

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

// Convert retriever results to research phases for streaming
function resultsToPhases(results: RetrieverResult[]): Array<{
  id: string
  name: string
  status: 'complete' | 'error'
  toolName: string
  input: Record<string, unknown>
  output?: { issues?: JiraIssue[]; count?: number; error?: string }
}> {
  return results.map(r => {
    // Map retriever type to tool name
    const toolNameMap: Record<string, string> = {
      'semantic': 'semantic_search',
      'jql': 'jql_search',
      'aggregation': 'get_aggregations',
      'trends': 'get_trends',
      'velocity': 'get_velocity',
      'clusters': 'get_clusters',
      'links': 'get_linked_issues',
      'epic-children': 'get_epic_children',
    }

    return {
      id: generateId(),
      name: `${r.type} retrieval`,
      status: r.error ? 'error' as const : 'complete' as const,
      toolName: toolNameMap[r.type] || r.type,
      input: r.metadata || {},
      output: {
        issues: r.issues,
        count: r.issues?.length || r.metadata?.count as number || 0,
        error: r.error,
      }
    }
  })
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

  // =====================================================
  // LAYER 1: QUERY UNDERSTANDING
  // Intelligent intent classification and entity extraction
  // =====================================================
  console.log('[Chat] Layer 1: Query Analysis for:', lastUserMessage)
  const analysis = analyzeQuery(lastUserMessage, currentUser)
  console.log('[Chat] Analysis:', {
    intent: analysis.intent,
    confidence: analysis.confidence,
    entities: analysis.entities,
    analyticalParams: analysis.analyticalParams,
  })

  // =====================================================
  // LAYER 2: ROUTING
  // Map intent to appropriate retrievers
  // =====================================================
  console.log('[Chat] Layer 2: Query Routing')
  const route = routeQuery(analysis)
  console.log('[Chat] Route:', describeRoute(route))

  // =====================================================
  // LAYER 3: RETRIEVAL
  // Execute retrievers (parallel where possible)
  // =====================================================
  console.log('[Chat] Layer 3: Executing Retrievers')
  const { results: retrieverResults, allIssues } = await executeRetrievers(route)
  console.log('[Chat] Retrieval complete:', {
    resultCount: retrieverResults.length,
    issueCount: allIssues.length,
  })

  // =====================================================
  // LAYER 4: CONTEXT ASSEMBLY
  // Smart formatting based on query type
  // =====================================================
  console.log('[Chat] Layer 4: Context Assembly')
  const assembled = assembleContext(analysis, retrieverResults, allIssues)
  console.log('[Chat] Context assembled:', {
    textLength: assembled.textContext.length,
    hasAggregations: !!assembled.uiData.aggregations,
    hasTrends: !!assembled.uiData.trends,
    hasVelocity: !!assembled.uiData.velocity,
  })

  // =====================================================
  // LAYER 5: SYNTHESIS
  // Query-type-aware LLM prompt generation
  // =====================================================
  const systemPrompt = buildSynthesisPrompt(analysis, currentUser, outputMode)

  // Build the synthesis messages
  const synthesisMessages = await convertToModelMessages(messages)
  const messagesWithContext = [
    ...synthesisMessages.slice(0, -1),
    {
      role: 'user' as const,
      content: `${lastUserMessage}

---

## Research Results (automatically gathered)

${assembled.textContext}`
    }
  ]

  // Generate refinements for exploratory queries
  const refinementsData = analysis.intent !== 'analytical'
    ? generateSearchRefinements(allIssues, lastUserMessage)
    : null

  // Convert results to phases for streaming
  const phases = resultsToPhases(retrieverResults)

  // =====================================================
  // LAYER 6: STREAMING RESPONSE WITH GENERATIVE UI
  // =====================================================
  const stream = createUIMessageStream({
    originalMessages: messages,
    execute: async ({ writer }) => {
      const messageId = generateId()
      const textId = generateId()

      console.log('[Chat] Layer 6: Streaming response')

      // 1. Send message start
      writer.write({ type: 'start', messageId })

      // 2. Stream research phases
      for (const phase of phases) {
        writer.write({
          type: 'data-research-phase',
          id: phase.id,
          data: {
            toolName: phase.toolName,
            input: phase.input,
            output: phase.output,
            state: phase.status === 'complete' || phase.status === 'error' ? 'output-available' : 'partial',
          },
        })
      }

      // 3. Stream analytical UI data BEFORE text
      // This ensures charts appear alongside the research phases
      const { uiData } = assembled

      if (uiData.aggregations && uiData.aggregations.length > 0) {
        writer.write({
          type: 'data-aggregations',
          id: generateId(),
          data: uiData.aggregations,
        })
      }

      if (uiData.trends) {
        writer.write({
          type: 'data-trends',
          id: generateId(),
          data: uiData.trends,
        })
      }

      if (uiData.velocity) {
        writer.write({
          type: 'data-velocity',
          id: generateId(),
          data: uiData.velocity,
        })
      }

      // 4. Send text-start
      writer.write({ type: 'text-start', id: textId })

      // 5. Stream the AI synthesis response
      const result = streamText({
        model: openai(MODELS[modelId]),
        system: systemPrompt,
        messages: messagesWithContext,
        temperature: 0.3,
      })

      let fullText = ''
      for await (const chunk of result.textStream) {
        fullText += chunk
        writer.write({ type: 'text-delta', id: textId, delta: chunk })
      }

      // 6. Send text-end
      writer.write({ type: 'text-end', id: textId })

      // 7. Stream refinements if available (for non-analytical queries)
      if (refinementsData) {
        writer.write({
          type: 'data-refinements',
          id: generateId(),
          data: refinementsData,
        })
      }

      // 8. Generate and stream follow-up suggestions
      const suggestions = generateFollowUpSuggestions(fullText, allIssues, analysis)
      if (suggestions.length > 0) {
        writer.write({
          type: 'data-suggestions',
          id: generateId(),
          data: { prompts: suggestions },
        })
      }

      // 9. Send message finish
      writer.write({ type: 'finish', finishReason: 'stop' })

      // Log for evaluation (async)
      const conversationId = body.conversationId || generateId()
      const turnIndex = messages.filter(m => m.role === 'user').length

      // Build eval log data in the expected format
      const toolCalls = phases.map(p => ({
        tool_name: p.toolName,
        input: p.input,
        output: p.output ? {
          issues: p.output.issues?.map(i => i.issue_id) || [],
          count: p.output.count,
          error: p.output.error
        } : null,
        latency_ms: 0,
        error: p.status === 'error' ? p.output?.error : undefined
      }))

      // Extract citations from response
      const citations: Array<{ index: number; issue_id: string }> = []
      const numericCitations = fullText.match(/\[(\d+)\]/g) || []
      for (const match of numericCitations) {
        const index = parseInt(match.slice(1, -1), 10)
        if (index > 0 && index <= allIssues.length) {
          citations.push({
            index,
            issue_id: allIssues[index - 1].issue_id
          })
        }
      }

      const evalData = {
        conversation_id: conversationId,
        turn_index: turnIndex,
        query: lastUserMessage,
        tool_calls: toolCalls,
        retrieved_issues: allIssues.map(i => i.issue_id),
        response_text: fullText,
        citations,
        model_id: modelId,
        output_mode_id: outputModeId
      }

      logEvaluation(evalData).catch(err => {
        console.error('[Chat] Eval logging error:', err)
      })
    },
    onError: (error) => {
      console.error('[Chat] Stream error:', error)
      return error instanceof Error ? error.message : String(error)
    }
  })

  return createUIMessageStreamResponse({ stream })
}
