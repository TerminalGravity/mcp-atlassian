// web/src/app/api/chat/research-pipeline.ts

import type { UIMessageStreamWriter } from 'ai'
import { generateId } from 'ai'
import { classifyQuery, type QueryClassification } from './query-classifier'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// Types
export interface JiraIssue {
  issue_id: string
  summary: string
  status: string
  issue_type: string
  project_key: string
  assignee?: string | null
  description_preview?: string | null
  labels?: string[]
  score: number
  // Timestamps for temporal filtering
  created_at?: string
  updated_at?: string
}

export interface ResearchPhase {
  id: string
  name: string
  status: 'pending' | 'running' | 'complete' | 'error'
  toolName: string
  input: Record<string, unknown>
  output?: { issues: JiraIssue[]; count: number; error?: string }
}

export interface ResearchResult {
  phases: ResearchPhase[]
  allIssues: JiraIssue[]
  classification: QueryClassification
}

// API helpers
async function searchVectorStore(query: string, limit: number = 10): Promise<{ issues: JiraIssue[]; count: number; error?: string }> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/vector-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, limit }),
    })
    if (!response.ok) {
      return { issues: [], count: 0, error: `Search failed: ${response.status}` }
    }
    return response.json()
  } catch (error) {
    return { issues: [], count: 0, error: `Search error: ${error}` }
  }
}

async function searchJQL(jql: string, limit: number = 10): Promise<{ issues: JiraIssue[]; count: number; error?: string }> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      return { issues: [], count: 0, error: `JQL failed: ${response.status}` }
    }
    return response.json()
  } catch (error) {
    return { issues: [], count: 0, error: `JQL error: ${error}` }
  }
}

async function getLinkedIssues(issueKey: string): Promise<{ issues: JiraIssue[]; count: number; error?: string }> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/linked-issues`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issueKey }),
    })
    if (!response.ok) {
      return { issues: [], count: 0, error: `Links failed: ${response.status}` }
    }
    return response.json()
  } catch (error) {
    return { issues: [], count: 0, error: `Links error: ${error}` }
  }
}

/**
 * Stream a research phase update to the client.
 * Uses data-research-phase custom type which the UI will render.
 */
function streamPhase(writer: UIMessageStreamWriter, phase: ResearchPhase) {
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

/**
 * Execute the full research pipeline with streaming updates.
 *
 * This is the core of the "forced agent loop" - it ALWAYS executes
 * multiple phases regardless of what the AI might want to do.
 */
export async function executeResearchPipeline(
  query: string,
  currentUser: string,
  writer: UIMessageStreamWriter
): Promise<ResearchResult> {
  const phases: ResearchPhase[] = []
  const allIssues: JiraIssue[] = []
  const seenIssueIds = new Set<string>()

  // Helper to add issues without duplicates
  const addIssues = (issues: JiraIssue[]) => {
    for (const issue of issues) {
      if (!seenIssueIds.has(issue.issue_id)) {
        seenIssueIds.add(issue.issue_id)
        allIssues.push(issue)
      }
    }
  }

  // Phase 0: Classify the query
  const classification = classifyQuery(query, currentUser)
  console.log('[Research] Classification:', classification)

  // Phase 1: JQL Search (runs for 'jql' or 'hybrid' types)
  // For temporal queries like "most recently updated", JQL with ORDER BY is essential
  if ((classification.type === 'jql' || classification.type === 'hybrid') && classification.jqlQuery) {
    const jqlPhase: ResearchPhase = {
      id: generateId(),
      name: 'JQL Search',
      status: 'running',
      toolName: 'jql_search',
      input: { jql: classification.jqlQuery },
    }
    phases.push(jqlPhase)
    streamPhase(writer, jqlPhase)

    const jqlResult = await searchJQL(classification.jqlQuery, 20)
    jqlPhase.status = jqlResult.error ? 'error' : 'complete'
    jqlPhase.output = jqlResult
    streamPhase(writer, jqlPhase)
    addIssues(jqlResult.issues || [])
  }

  // Phase 2: Semantic Search (runs for 'semantic' or 'hybrid' types)
  if ((classification.type === 'semantic' || classification.type === 'hybrid') && classification.semanticQuery) {
    const semanticPhase: ResearchPhase = {
      id: generateId(),
      name: 'Semantic Search',
      status: 'running',
      toolName: 'semantic_search',
      input: { query: classification.semanticQuery },
    }
    phases.push(semanticPhase)
    streamPhase(writer, semanticPhase)

    const semanticResult = await searchVectorStore(classification.semanticQuery, 15)
    semanticPhase.status = semanticResult.error ? 'error' : 'complete'
    semanticPhase.output = semanticResult
    streamPhase(writer, semanticPhase)
    addIssues(semanticResult.issues || [])
  }

  // Phase 2: Epic Expansion (FORCED when applicable)
  if (classification.shouldExpandEpics) {
    const epics = allIssues.filter(i => i.issue_type === 'Epic')

    for (const epic of epics.slice(0, 3)) { // Limit to 3 epics to avoid too many calls
      const phase2: ResearchPhase = {
        id: generateId(),
        name: `Epic Children: ${epic.issue_id}`,
        status: 'running',
        toolName: 'get_epic_children',
        input: { epicKey: epic.issue_id, epicSummary: epic.summary },
      }
      phases.push(phase2)
      streamPhase(writer, phase2)

      // Try parent field first, then Epic Link
      let childResult = await searchJQL(`parent = ${epic.issue_id} ORDER BY issuetype, status`, 30)

      if ((childResult.issues?.length || 0) < 3 && !childResult.error) {
        const epicLinkResult = await searchJQL(`"Epic Link" = ${epic.issue_id} ORDER BY issuetype, status`, 30)
        if ((epicLinkResult.issues?.length || 0) > (childResult.issues?.length || 0)) {
          childResult = epicLinkResult
        }
      }

      phase2.status = childResult.error ? 'error' : 'complete'
      phase2.output = childResult
      streamPhase(writer, phase2)
      addIssues(childResult.issues || [])
    }
  }

  // Phase 3: Link Expansion (FORCED when applicable)
  if (classification.shouldFetchLinks && allIssues.length > 0) {
    // Get links for the most relevant issue (first one found)
    const primaryIssue = allIssues[0]

    const phase3: ResearchPhase = {
      id: generateId(),
      name: `Linked Issues: ${primaryIssue.issue_id}`,
      status: 'running',
      toolName: 'get_linked_issues',
      input: { issueKey: primaryIssue.issue_id },
    }
    phases.push(phase3)
    streamPhase(writer, phase3)

    const linksResult = await getLinkedIssues(primaryIssue.issue_id)
    phase3.status = linksResult.error ? 'error' : 'complete'
    phase3.output = linksResult
    streamPhase(writer, phase3)
    addIssues(linksResult.issues || [])
  }

  return {
    phases,
    allIssues,
    classification,
  }
}

/**
 * Build context string from research results for the AI synthesis phase.
 */
export function buildResearchContext(result: ResearchResult): string {
  const parts: string[] = []

  parts.push(`## Research Summary`)
  parts.push(`Query classified as: ${result.classification.type}`)
  parts.push(`Total issues found: ${result.allIssues.length}`)
  parts.push(`Research phases completed: ${result.phases.length}`)
  parts.push('')

  // Group issues by type
  const byType = new Map<string, JiraIssue[]>()
  for (const issue of result.allIssues) {
    const type = issue.issue_type || 'Unknown'
    if (!byType.has(type)) {
      byType.set(type, [])
    }
    byType.get(type)!.push(issue)
  }

  // Format issues by type (including timestamps for temporal analysis)
  for (const [type, issues] of byType.entries()) {
    parts.push(`### ${type}s (${issues.length})`)
    parts.push('')
    for (const issue of issues.slice(0, 20)) { // Limit per type
      const assignee = issue.assignee || 'Unassigned'
      const preview = issue.description_preview?.slice(0, 200) || ''
      parts.push(`**[${issue.issue_id}] ${issue.summary}**`)
      // Include timestamps when available for accurate temporal filtering
      const timestamps: string[] = []
      if (issue.updated_at) {
        timestamps.push(`Updated: ${issue.updated_at}`)
      }
      if (issue.created_at) {
        timestamps.push(`Created: ${issue.created_at}`)
      }
      const timestampStr = timestamps.length > 0 ? ` | ${timestamps.join(' | ')}` : ''
      parts.push(`Status: ${issue.status} | Assignee: ${assignee}${timestampStr}`)
      if (preview) {
        parts.push(`> ${preview}...`)
      }
      parts.push('')
    }
  }

  return parts.join('\n')
}
