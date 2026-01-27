# Forced Agent Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the Jira Knowledge chat from AI-discretionary tool usage to a deterministic multi-phase research pipeline that ALWAYS digs deeper.

**Architecture:** Replace the current `streamText` with tools approach with a phased research pipeline:
1. **Classify** - Determine query type (semantic vs JQL)
2. **Search** - Execute initial search (forced)
3. **Expand** - Automatically fetch epic children, linked issues (forced when applicable)
4. **Synthesize** - AI generates comprehensive answer from ALL gathered data

**Tech Stack:** Next.js API routes, AI SDK 6 `createUIMessageStream`, TypeScript, existing Python FastAPI backend

---

## Task 1: Create Query Classifier

**Files:**
- Create: `web/src/app/api/chat/query-classifier.ts`

**Step 1: Create the query classifier module**

```typescript
// web/src/app/api/chat/query-classifier.ts

export type QueryType = 'semantic' | 'jql' | 'hybrid'

export interface QueryClassification {
  type: QueryType
  semanticQuery?: string
  jqlQuery?: string
  shouldExpandEpics: boolean
  shouldFetchLinks: boolean
}

// Patterns that indicate JQL-style queries
const JQL_PATTERNS = [
  /\b(open|closed|resolved|unresolved)\s+(bugs?|issues?|tasks?|stories?)/i,
  /\b(my|assigned to me)\s+(issues?|bugs?|tasks?)/i,
  /\b(in progress|backlog|done|to do)\b/i,
  /\b(recent|updated|created)\s+(this week|today|yesterday|-\d+d)/i,
  /\bstatus\s*[=:]/i,
  /\bassignee\s*[=:]/i,
  /\bproject\s*[=:]/i,
  /\bpriority\s*[=:]/i,
]

// Patterns that indicate conceptual/semantic queries
const SEMANTIC_PATTERNS = [
  /\bwhat is\b/i,
  /\bhow does\b/i,
  /\bwhy (do|does|did|is|are|was|were)\b/i,
  /\bexplain\b/i,
  /\btell me about\b/i,
  /\bwhat('s| is) the (status|progress|state) of\b/i,
  /\b(related to|about|regarding|concerning)\b/i,
]

// Patterns that suggest we should look for epics
const EPIC_PATTERNS = [
  /\bfeature/i,
  /\bproject\b/i,
  /\binitiative\b/i,
  /\bplatform\b/i,
  /\bsystem\b/i,
  /\bmodule\b/i,
]

/**
 * Classify a user query to determine the best search strategy.
 */
export function classifyQuery(query: string, currentUser: string): QueryClassification {
  const q = query.trim()

  // Check for explicit JQL patterns
  const isJqlStyle = JQL_PATTERNS.some(p => p.test(q))

  // Check for conceptual/semantic patterns
  const isSemanticStyle = SEMANTIC_PATTERNS.some(p => p.test(q))

  // Check if we should expand epics
  const shouldExpandEpics = EPIC_PATTERNS.some(p => p.test(q)) || isSemanticStyle

  // For now, always fetch links for semantic queries (they provide context)
  const shouldFetchLinks = isSemanticStyle

  // Determine query type
  let type: QueryType = 'semantic'
  if (isJqlStyle && !isSemanticStyle) {
    type = 'jql'
  } else if (isJqlStyle && isSemanticStyle) {
    type = 'hybrid'
  }

  // Build the classification result
  const result: QueryClassification = {
    type,
    shouldExpandEpics,
    shouldFetchLinks,
  }

  // Generate semantic query (always useful)
  result.semanticQuery = q

  // Generate JQL query for JQL-style queries
  if (type === 'jql' || type === 'hybrid') {
    result.jqlQuery = buildJqlFromQuery(q, currentUser)
  }

  return result
}

/**
 * Convert natural language to JQL query.
 */
function buildJqlFromQuery(query: string, currentUser: string): string {
  const parts: string[] = []
  const q = query.toLowerCase()

  // Project filter (default to DS)
  parts.push('project = DS')

  // Issue type detection
  if (/bugs?/i.test(q)) {
    parts.push('issuetype = Bug')
  } else if (/stories?/i.test(q)) {
    parts.push('issuetype = Story')
  } else if (/tasks?/i.test(q)) {
    parts.push('issuetype = Task')
  } else if (/epics?/i.test(q)) {
    parts.push('issuetype = Epic')
  }

  // Status detection
  if (/\b(open|unresolved)\b/i.test(q)) {
    parts.push('resolution = Unresolved')
  } else if (/\b(closed|resolved|done)\b/i.test(q)) {
    parts.push('resolution IS NOT EMPTY')
  } else if (/\bin progress\b/i.test(q)) {
    parts.push('status = "In Progress"')
  } else if (/\bbacklog\b/i.test(q)) {
    parts.push('status = "Backlog"')
  }

  // Assignee detection
  if (/\b(my|assigned to me)\b/i.test(q)) {
    parts.push(`assignee = "${currentUser}"`)
  }

  // Time-based filters
  if (/\btoday\b/i.test(q)) {
    parts.push('updated >= startOfDay()')
  } else if (/\byesterday\b/i.test(q)) {
    parts.push('updated >= -1d')
  } else if (/\bthis week\b/i.test(q)) {
    parts.push('updated >= startOfWeek()')
  } else if (/\brecent(ly)?\b/i.test(q)) {
    parts.push('updated >= -7d')
  }

  // Order by most recently updated
  parts.push('ORDER BY updated DESC')

  return parts.join(' AND ').replace(' AND ORDER', ' ORDER')
}
```

**Step 2: Commit**

```bash
git add web/src/app/api/chat/query-classifier.ts
git commit -m "feat(chat): Add query classifier for forced agent loop"
```

---

## Task 2: Create Research Pipeline Module

**Files:**
- Create: `web/src/app/api/chat/research-pipeline.ts`

**Step 1: Create the research pipeline module**

```typescript
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
 */
function streamPhase(writer: UIMessageStreamWriter, phase: ResearchPhase) {
  // Use tool-invocation format so the UI can render it properly
  const toolType = `tool-${phase.toolName}` as const

  writer.write({
    type: toolType,
    id: phase.id,
    // @ts-expect-error - AI SDK types don't include all our custom fields
    input: phase.input,
    output: phase.output,
    state: phase.status === 'complete' || phase.status === 'error' ? 'output-available' : 'partial',
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

  // Phase 1: Initial Search (ALWAYS runs)
  const phase1: ResearchPhase = {
    id: generateId(),
    name: classification.type === 'jql' ? 'JQL Search' : 'Semantic Search',
    status: 'running',
    toolName: classification.type === 'jql' ? 'jql_search' : 'semantic_search',
    input: classification.type === 'jql'
      ? { jql: classification.jqlQuery }
      : { query: classification.semanticQuery },
  }
  phases.push(phase1)
  streamPhase(writer, phase1)

  // Execute initial search
  const initialResult = classification.type === 'jql'
    ? await searchJQL(classification.jqlQuery!, 15)
    : await searchVectorStore(classification.semanticQuery!, 15)

  phase1.status = initialResult.error ? 'error' : 'complete'
  phase1.output = initialResult
  streamPhase(writer, phase1)
  addIssues(initialResult.issues || [])

  // For hybrid queries, also run semantic search
  if (classification.type === 'hybrid' && classification.semanticQuery) {
    const phase1b: ResearchPhase = {
      id: generateId(),
      name: 'Semantic Search',
      status: 'running',
      toolName: 'semantic_search',
      input: { query: classification.semanticQuery },
    }
    phases.push(phase1b)
    streamPhase(writer, phase1b)

    const semanticResult = await searchVectorStore(classification.semanticQuery, 10)
    phase1b.status = semanticResult.error ? 'error' : 'complete'
    phase1b.output = semanticResult
    streamPhase(writer, phase1b)
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

  // Format issues by type
  for (const [type, issues] of byType.entries()) {
    parts.push(`### ${type}s (${issues.length})`)
    parts.push('')
    for (const issue of issues.slice(0, 20)) { // Limit per type
      const assignee = issue.assignee || 'Unassigned'
      const preview = issue.description_preview?.slice(0, 200) || ''
      parts.push(`**[${issue.issue_id}] ${issue.summary}**`)
      parts.push(`Status: ${issue.status} | Assignee: ${assignee}`)
      if (preview) {
        parts.push(`> ${preview}...`)
      }
      parts.push('')
    }
  }

  return parts.join('\n')
}
```

**Step 2: Commit**

```bash
git add web/src/app/api/chat/research-pipeline.ts
git commit -m "feat(chat): Add forced research pipeline with streaming phases"
```

---

## Task 3: Refactor Chat Route to Use Research Pipeline

**Files:**
- Modify: `web/src/app/api/chat/route.ts`

**Step 1: Replace the current implementation with the forced agent loop**

Replace the entire content of `route.ts` with this new implementation:

```typescript
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

import { executeResearchPipeline, buildResearchContext, type JiraIssue } from './research-pipeline'

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
        onFinish: async ({ text }) => {
          // Generate and emit refinements
          const refinementsData = generateSearchRefinements(researchResult.allIssues, lastUserMessage)
          if (refinementsData) {
            writer.write({
              type: 'data-refinements',
              id: generateId(),
              data: refinementsData
            })
          }

          // Generate and emit follow-up suggestions
          const suggestions = generateFollowUpSuggestions(text, researchResult.allIssues)
          if (suggestions.length > 0) {
            writer.write({
              type: 'data-suggestions',
              id: generateId(),
              data: { prompts: suggestions }
            })
          }
        }
      })

      // Merge the AI synthesis stream
      writer.merge(result.toUIMessageStream())
    }
  })

  return createUIMessageStreamResponse({ stream })
}
```

**Step 2: Commit**

```bash
git add web/src/app/api/chat/route.ts
git commit -m "feat(chat): Implement forced agent loop with deterministic research"
```

---

## Task 4: Update Chat Message Component for New Tool Types

**Files:**
- Modify: `web/src/components/chat/chat-message.tsx` (minor update)

**Step 1: Verify the component handles the tool types correctly**

The existing `chat-message.tsx` already handles tool parts via `toolPartsToSteps()`. The research pipeline emits tool parts in the same format, so no changes are needed unless we want to add labels.

Update the `toolDisplayConfig` to ensure all tool names are mapped:

```typescript
// In chat-message.tsx, verify this config exists around line 130:
const toolDisplayConfig: Record<string, { icon: typeof Search; label: string }> = {
  semantic_search: { icon: Search, label: "Semantic Search" },
  jql_search: { icon: Database, label: "JQL Query" },
  get_epic_children: { icon: GitBranch, label: "Epic Children" },
  get_linked_issues: { icon: Link2, label: "Linked Issues" },
}
```

This is already correct. No changes needed.

**Step 2: Commit (if changes were made)**

```bash
# Only if changes were made
git add web/src/components/chat/chat-message.tsx
git commit -m "fix(chat): Ensure tool display config handles all research tools"
```

---

## Task 5: Test the Implementation

**Step 1: Start the backend server**

```bash
cd /Users/jack/Developer/mcp-atlassian
uv run python -m mcp_atlassian.web.server
```

Expected: Server starts on port 8000

**Step 2: Start the frontend dev server**

```bash
cd /Users/jack/Developer/mcp-atlassian/web
pnpm dev
```

Expected: Frontend starts on port 3000

**Step 3: Test with a conceptual query**

Open http://localhost:3000 and enter:
```
What is Changemaker and what features are being developed?
```

Expected behavior:
1. "View thinking process" should show multiple steps:
   - Semantic Search - X results
   - Epic Children: DS-XXXX - Y results (if epic found)
   - Linked Issues: DS-XXXX - Z results
2. Response should be comprehensive, covering the epic and its children
3. Follow-up suggestions should appear

**Step 4: Test with a JQL-style query**

Enter:
```
Show me open bugs
```

Expected behavior:
1. Thinking process shows:
   - JQL Query - X results
2. Response lists bug issues with status

**Step 5: Test with a hybrid query**

Enter:
```
What open bugs are related to authentication?
```

Expected behavior:
1. Thinking process shows:
   - JQL Query - X results (for open bugs)
   - Semantic Search - Y results (for authentication concept)
2. Response synthesizes both result sets

---

## Task 6: Commit and Push

**Step 1: Create final commit**

```bash
git add -A
git commit -m "feat(chat): Complete forced agent loop implementation

- Add query classifier for semantic vs JQL detection
- Add research pipeline with streaming phase updates
- Refactor chat route to use deterministic multi-phase research
- AI now only synthesizes - cannot skip research phases

The chat now ALWAYS:
1. Classifies the query type
2. Runs initial search (semantic or JQL based on query)
3. Expands epics when found (fetches children)
4. Fetches linked issues for context
5. Synthesizes comprehensive answer from ALL data

This fixes the issue where AI would stop after a single search."
```

**Step 2: Push to remote**

```bash
git push origin feature/jira-command-center
```

---

## Success Criteria

After implementation:

1. **Multi-step research is FORCED** - The thinking process always shows 2+ steps for conceptual queries
2. **Epics are automatically expanded** - When an Epic is found, its children are fetched
3. **Links are fetched for context** - Primary issue's links are retrieved
4. **AI synthesizes, doesn't decide** - The AI only generates the answer, it cannot skip research
5. **Streaming works correctly** - Each phase appears in real-time with status indicators
6. **Refinements and suggestions still work** - Post-response UI elements function

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Too many API calls | Limited to 3 epics max, 1 link fetch |
| Slow responses | Research phases stream immediately, showing progress |
| Query misclassification | Hybrid mode catches ambiguous queries |
| Backend errors | Each phase handles errors gracefully, continues to synthesis |
