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

// Types for refinements
interface JiraIssue {
  issue_id: string
  summary: string
  status: string
  issue_type: string
  project_key: string
  assignee?: string | null
  description_preview?: string | null
  labels?: string[]
  priority?: string
  score: number
}

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

// Maximum number of refinement chips to show for clean UX
const MAX_REFINEMENT_CHIPS = 8

// Pluralize issue type labels correctly
function pluralizeIssueType(type: string): string {
  const irregulars: Record<string, string> = {
    'Story': 'Stories',
    'story': 'stories',
    'Bug': 'Bugs',
    'bug': 'bugs',
    'Task': 'Tasks',
    'task': 'tasks',
    'Epic': 'Epics',
    'epic': 'epics',
    'Sub-task': 'Sub-tasks',
    'sub-task': 'sub-tasks',
    'Quote': 'Quotes',
    'quote': 'quotes',
  }
  return irregulars[type] || `${type}s`
}

// Generate search refinements from tool output issues
function generateSearchRefinements(issues: JiraIssue[], originalQuery: string): RefinementsData | null {
  // Don't generate refinements for small result sets
  if (issues.length < 3) {
    return null
  }

  const refinements: Refinement[] = []

  // Group by project_key
  const projectCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.project_key) {
      projectCounts.set(issue.project_key, (projectCounts.get(issue.project_key) || 0) + 1)
    }
  }

  // Only add project refinements if there are 2+ different projects
  if (projectCounts.size >= 2) {
    for (const [project, count] of projectCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `project-${project}`,
          label: `${project} only (${count})`,
          category: 'project',
          filter: {
            field: 'project_key',
            value: project,
            operator: '$eq'
          },
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

  // Only add status refinements if there are 2+ different statuses
  if (statusCounts.size >= 2) {
    for (const [status, count] of statusCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `status-${status.toLowerCase().replace(/\s+/g, '-')}`,
          label: `${status} (${count})`,
          category: 'status',
          filter: {
            field: 'status',
            value: status,
            operator: '$eq'
          },
          count
        })
      }
    }
  }

  // Group by issue_type
  const typeCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.issue_type) {
      typeCounts.set(issue.issue_type, (typeCounts.get(issue.issue_type) || 0) + 1)
    }
  }

  // Only add type refinements if there are 2+ different types
  if (typeCounts.size >= 2) {
    for (const [type, count] of typeCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `type-${type.toLowerCase().replace(/\s+/g, '-')}`,
          label: `${pluralizeIssueType(type)} (${count})`,
          category: 'type',
          filter: {
            field: 'issue_type',
            value: type,
            operator: '$eq'
          },
          count
        })
      }
    }
  }

  // Group by priority (if available)
  const priorityCounts = new Map<string, number>()
  for (const issue of issues) {
    if (issue.priority) {
      priorityCounts.set(issue.priority, (priorityCounts.get(issue.priority) || 0) + 1)
    }
  }

  // Only add priority refinements if there are 2+ different priorities
  if (priorityCounts.size >= 2) {
    for (const [priority, count] of priorityCounts.entries()) {
      if (count >= 2) {
        refinements.push({
          id: `priority-${priority.toLowerCase().replace(/\s+/g, '-')}`,
          label: `${priority} priority (${count})`,
          category: 'priority',
          filter: {
            field: 'priority',
            value: priority,
            operator: '$eq'
          },
          count
        })
      }
    }
  }

  // Add time-based refinements (static, JQL-compatible)
  // These don't have counts since JiraIssue doesn't include timestamp data,
  // but they enable filtering by time range in subsequent queries
  const timeRefinements = [
    { id: 'time-7d', label: 'Last 7 days', value: '-7d' },
    { id: 'time-30d', label: 'Last 30 days', value: '-30d' },
    { id: 'time-90d', label: 'Last 90 days', value: '-90d' },
  ]

  for (const timeRef of timeRefinements) {
    refinements.push({
      id: timeRef.id,
      label: timeRef.label,
      category: 'time',
      filter: {
        field: 'updated',
        value: timeRef.value,
        operator: '>='
      }
    })
  }

  // Only return refinements if we have at least one meaningful refinement
  if (refinements.length === 0) {
    return null
  }

  // Sort refinements by count (highest first) within each category
  refinements.sort((a, b) => (b.count || 0) - (a.count || 0))

  // Limit to MAX_REFINEMENT_CHIPS for clean UX
  const limitedRefinements = refinements.slice(0, MAX_REFINEMENT_CHIPS)

  return {
    originalQuery,
    totalResults: issues.length,
    refinements: limitedRefinements
  }
}

// Extract issues from tool results (steps from AI SDK)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractIssuesFromSteps(steps: any[]): JiraIssue[] {
  const allIssues: JiraIssue[] = []

  for (const step of steps) {
    if (step.toolResults && Array.isArray(step.toolResults)) {
      for (const toolResult of step.toolResults) {
        // Tool results have a 'result' property with the actual data
        const result = toolResult.result as { issues?: JiraIssue[] } | undefined
        if (result?.issues && Array.isArray(result.issues)) {
          allIssues.push(...result.issues)
        }
      }
    }
  }

  // Deduplicate by issue_id
  const seen = new Set<string>()
  return allIssues.filter(issue => {
    if (seen.has(issue.issue_id)) {
      return false
    }
    seen.add(issue.issue_id)
    return true
  })
}

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
    console.log(`[Vector Search] Query: "${query}", limit: ${limit}`)
    const response = await fetch(`${BACKEND_URL}/api/vector-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit }),
    })
    if (!response.ok) {
      console.error(`[Vector Search] Failed with status ${response.status}`)
      return { error: `Search failed with status ${response.status}`, issues: [], count: 0 }
    }
    const result = await response.json()
    console.log(`[Vector Search] Found ${result.issues?.length || 0} results`)
    return result
  } catch (error) {
    console.error(`[Vector Search] Error:`, error)
    return { error: `Search error: ${error}`, issues: [], count: 0 }
  }
}

// Tool to search via JQL
async function searchJQL(jql: string, limit: number = 10) {
  try {
    console.log(`[JQL Search] Query: "${jql}", limit: ${limit}`)
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      console.error(`[JQL Search] Failed with status ${response.status}`)
      return {
        error: "JQL search unavailable - Jira connection not configured",
        issues: [],
        count: 0,
        suggestion: "Use semantic_search instead for now"
      }
    }
    const result = await response.json()
    console.log(`[JQL Search] Found ${result.issues?.length || 0} results, error: ${result.error || 'none'}`)
    return result
  } catch (error) {
    console.error(`[JQL Search] Error:`, error)
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

// Generate contextual follow-up suggestions based on response content
function generateFollowUpSuggestions(responseText: string, lastUserMessage: string): string[] {
  const suggestions: string[] = []

  // Track what user already asked about to avoid repeating
  const alreadyAskedAbout = lastUserMessage.toLowerCase()

  // Extract specific issue keys mentioned (prioritize those called out specifically)
  const issueMatches = responseText.match(/DS-\d+/g) || []
  const uniqueIssues = [...new Set(issueMatches)]

  // Find issues that are highlighted/emphasized in the response
  const highlightedIssues = uniqueIssues.filter(i =>
    responseText.includes(`**${i}**`) ||
    responseText.includes(`[${i}]`) ||
    new RegExp(`${i}[^\\d].*(?:blocker|critical|urgent|open|in progress)`, 'i').test(responseText)
  )

  // Extract key topics/features mentioned with priority scores
  const topicPatterns = [
    { pattern: /QA|testing|test(?:ing)?/i, topic: "QA", suggestion: "What QA items are still open?", priority: 2 },
    { pattern: /permission|catalog|workspace/i, topic: "permissions", suggestion: "Tell me about permission issues", priority: 1 },
    { pattern: /MVP|demo|release/i, topic: "MVP", suggestion: "What's blocking the MVP release?", priority: 3 },
    { pattern: /phase\s*2/i, topic: "Phase 2", suggestion: "What's the Phase 2 roadmap?", priority: 2 },
    { pattern: /backlog/i, topic: "backlog", suggestion: "What's in the backlog?", priority: 1 },
    { pattern: /blocker|blocked|blocking/i, topic: "blockers", suggestion: "List all current blockers", priority: 4 },
    { pattern: /performance|N\+1|pagination|slow/i, topic: "performance", suggestion: "Show performance issues", priority: 2 },
    { pattern: /bug|defect|issue/i, topic: "bugs", suggestion: "What bugs are open?",  priority: 2 },
  ]

  // Filter to topics mentioned in response but NOT already asked about
  const detectedTopics = topicPatterns
    .filter(({ pattern, topic }) =>
      pattern.test(responseText) && !alreadyAskedAbout.includes(topic.toLowerCase())
    )
    .sort((a, b) => b.priority - a.priority)

  // Extract assignee names mentioned
  const assigneeMatch = responseText.match(/(?:assigned to|Assignee[:\s]+)([A-Z][a-z]+ [A-Z][a-z]+)/gi)
  const assignees = assigneeMatch
    ? [...new Set(assigneeMatch.map(m => m.replace(/assigned to|assignee[:\s]+/i, '').trim()))]
    : []

  // 1. First priority: Drill into a specific highlighted issue (not one already discussed)
  const issueToExplore = highlightedIssues.find(i => !alreadyAskedAbout.includes(i.toLowerCase()))
    || uniqueIssues.find(i => !alreadyAskedAbout.includes(i.toLowerCase()))
  if (issueToExplore && suggestions.length < 4) {
    suggestions.push(`Tell me more about ${issueToExplore}`)
  }

  // 2. Add topic-specific suggestions (highest priority topics first)
  for (const { suggestion } of detectedTopics) {
    if (suggestions.length >= 4) break
    if (!suggestions.includes(suggestion)) {
      suggestions.push(suggestion)
    }
  }

  // 3. Assignee-specific suggestion (if not already asked about that person)
  if (assignees.length > 0 && suggestions.length < 4) {
    const person = assignees.find(a => !alreadyAskedAbout.includes(a.toLowerCase().split(' ')[0]))
    if (person) {
      const firstName = person.split(' ')[0]
      suggestions.push(`What else is ${firstName} working on?`)
    }
  }

  // 4. Status-based suggestions
  if (suggestions.length < 4) {
    if (/in progress|development in progress/i.test(responseText) && !alreadyAskedAbout.includes('open')) {
      suggestions.push("Show only open items")
    } else if (/closed|done|completed/i.test(responseText) && !alreadyAskedAbout.includes('recent')) {
      suggestions.push("What was completed recently?")
    }
  }

  // 5. Comparison if multiple epics discussed
  const epicCount = (responseText.match(/epic/gi) || []).length
  if (epicCount > 1 && suggestions.length < 4 && !alreadyAskedAbout.includes('compare')) {
    suggestions.push("Compare the epics")
  }

  // 6. Context-aware fallbacks
  const fallbacks = [
    { text: "What needs attention?", avoid: ["attention", "urgent", "priority"] },
    { text: "Show recent activity", avoid: ["recent", "activity", "update"] },
    { text: "Summarize the timeline", avoid: ["timeline", "schedule", "when"] },
    { text: "Who should I talk to?", avoid: ["who", "contact", "owner"] },
  ]

  for (const { text, avoid } of fallbacks) {
    if (suggestions.length >= 4) break
    if (!avoid.some(word => alreadyAskedAbout.includes(word))) {
      suggestions.push(text)
    }
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
1. **semantic_search** - Natural language search across indexed issues. ALWAYS WORKS.
2. **jql_search** - Direct Jira queries using JQL syntax. May return errors if Jira not connected.
3. **get_epic_children** - Get all child issues under an epic. USE THIS when you find an epic.
   - IMPORTANT: Always pass both epicKey AND epicSummary for best results
   - Example: get_epic_children({ epicKey: "DS-11641", epicSummary: "Launch of the Changemaker Platform" })
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

1. **Direct answer** - A clear, concise explanation of the topic (1-3 paragraphs)

2. **Key insights** - Patterns, blockers, status breakdown, or notable findings grouped by theme

**IMPORTANT: Do NOT generate markdown tables listing issues.** The UI automatically displays all found issues in an expandable "Sources referenced" component. Your text should focus on analysis and insights, referencing specific issue keys inline when relevant (e.g., "The main blocker is DS-1234 which...").

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
              epicSummary: z.string().optional().describe("Epic summary text to search related issues by keyword"),
            }),
            execute: async ({ epicKey, epicSummary }) => {
              // Try parent field first (newer Jira)
              let result = await searchJQL(`parent = ${epicKey} ORDER BY issuetype, status`, 50)

              // If parent returns few results, try Epic Link custom field
              if ((result.issues?.length || 0) < 3 && !result.error) {
                const epicLinkResult = await searchJQL(`"Epic Link" = ${epicKey} ORDER BY issuetype, status`, 50)
                if ((epicLinkResult.issues?.length || 0) > (result.issues?.length || 0)) {
                  result = epicLinkResult
                }
              }

              // If still few results and we have epic summary, search by keyword
              if ((result.issues?.length || 0) < 3 && epicSummary) {
                // Extract main keyword from epic summary (first significant word)
                const keyword = epicSummary.split(/[\s\-–:]+/).find(w => w.length > 4) || epicSummary.split(' ')[0]
                if (keyword) {
                  const keywordResult = await searchJQL(
                    `project = DS AND summary ~ "${keyword}" AND key != ${epicKey} ORDER BY updated DESC`,
                    30
                  )
                  if ((keywordResult.issues?.length || 0) > (result.issues?.length || 0)) {
                    result = { ...keywordResult, note: `Found via keyword search for "${keyword}"` }
                  }
                }
              }
              return result
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
        onFinish: async ({ text, steps }) => {
          // Generate and emit refinements (before suggestions)
          const allIssues = extractIssuesFromSteps(steps)
          const refinementsData = generateSearchRefinements(allIssues, lastUserMessage)
          if (refinementsData) {
            writer.write({
              type: 'data-refinements',
              id: generateId(),
              data: refinementsData
            })
          }

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
