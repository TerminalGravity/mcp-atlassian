// web/src/app/api/chat/eval-logger.ts

import type { JiraIssue, ResearchPhase, ResearchResult } from './research-pipeline'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * Tool call data captured for evaluation.
 */
export interface ToolCallData {
  tool_name: string
  input: Record<string, unknown>
  output: Record<string, unknown> | null
  latency_ms: number
  error?: string
}

/**
 * Citation extracted from response text.
 * Format: [1], [2], etc. with corresponding issue IDs.
 */
export interface Citation {
  index: number
  issue_id: string
}

/**
 * Data structure for logging a chat turn for evaluation.
 */
export interface EvalLogData {
  conversation_id: string
  turn_index: number
  query: string
  tool_calls: ToolCallData[]
  retrieved_issues: string[]
  response_text: string
  citations: Citation[]
  model_id: string
  output_mode_id: string | null
}

/**
 * Extract citations from response text.
 * Looks for patterns like [1], [2], [DS-1234], etc.
 */
export function extractCitations(responseText: string, issues: JiraIssue[]): Citation[] {
  const citations: Citation[] = []

  // Match numeric citations like [1], [2]
  const numericCitationRegex = /\[(\d+)\]/g
  let match
  while ((match = numericCitationRegex.exec(responseText)) !== null) {
    const index = parseInt(match[1], 10)
    // Map citation index to issue (1-indexed in response, 0-indexed in array)
    if (index > 0 && index <= issues.length) {
      citations.push({
        index,
        issue_id: issues[index - 1].issue_id
      })
    }
  }

  // Also match explicit issue references like [DS-1234]
  const issueKeyRegex = /\[([A-Z]+-\d+)\]/g
  while ((match = issueKeyRegex.exec(responseText)) !== null) {
    const issueKey = match[1]
    const issue = issues.find(i => i.issue_id === issueKey)
    if (issue) {
      // Find or assign an index
      const existingCitation = citations.find(c => c.issue_id === issueKey)
      if (!existingCitation) {
        citations.push({
          index: citations.length + 1,
          issue_id: issueKey
        })
      }
    }
  }

  return citations
}

/**
 * Convert research phases to tool call data for evaluation.
 */
export function phasesToToolCalls(phases: ResearchPhase[]): ToolCallData[] {
  return phases.map(phase => ({
    tool_name: phase.toolName,
    input: phase.input,
    output: phase.output ? {
      issues: phase.output.issues?.map(i => i.issue_id) || [],
      count: phase.output.count,
      error: phase.output.error
    } : null,
    latency_ms: 0, // We don't track per-phase latency currently
    error: phase.status === 'error' ? phase.output?.error : undefined
  }))
}

/**
 * Log a chat turn for evaluation.
 * This sends data to the backend to be stored in MongoDB.
 */
export async function logEvaluation(data: EvalLogData): Promise<{ success: boolean; id?: string; error?: string }> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/eval/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...data,
        timestamp: new Date().toISOString()
      })
    })

    if (!response.ok) {
      const errorText = await response.text()
      console.error('[EvalLogger] Failed to log evaluation:', errorText)
      return { success: false, error: errorText }
    }

    const result = await response.json()
    return { success: true, id: result.id }
  } catch (error) {
    console.error('[EvalLogger] Error logging evaluation:', error)
    return { success: false, error: String(error) }
  }
}

/**
 * Helper to build EvalLogData from research results and response.
 */
export function buildEvalLogData(
  conversationId: string,
  turnIndex: number,
  query: string,
  researchResult: ResearchResult,
  responseText: string,
  modelId: string,
  outputModeId: string | null
): EvalLogData {
  const toolCalls = phasesToToolCalls(researchResult.phases)
  const retrievedIssues = researchResult.allIssues.map(i => i.issue_id)
  const citations = extractCitations(responseText, researchResult.allIssues)

  return {
    conversation_id: conversationId,
    turn_index: turnIndex,
    query,
    tool_calls: toolCalls,
    retrieved_issues: retrievedIssues,
    response_text: responseText,
    citations,
    model_id: modelId,
    output_mode_id: outputModeId
  }
}
