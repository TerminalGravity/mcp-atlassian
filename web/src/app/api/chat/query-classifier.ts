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
  /\b(most )?(recently|latest) (updated|created|modified)/i,  // "most recently updated", "latest created"
  /\b(last|past)\s+\d+\s+(days?|weeks?|months?)/i,  // "last 7 days", "past 2 weeks"
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

  // Project filter - only add if NOT asking for "all projects"
  if (!/\b(all|every|any)\s+projects?\b/i.test(q) && !/\bacross\s+(all\s+)?projects?\b/i.test(q)) {
    parts.push('project = DS')
  }

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
  } else if (/\b(last|past)\s+(\d+)\s+days?\b/i.test(q)) {
    const match = q.match(/\b(last|past)\s+(\d+)\s+days?\b/i)
    if (match) parts.push(`updated >= -${match[2]}d`)
  } else if (/\b(last|past)\s+(\d+)\s+weeks?\b/i.test(q)) {
    const match = q.match(/\b(last|past)\s+(\d+)\s+weeks?\b/i)
    if (match) parts.push(`updated >= -${parseInt(match[2]) * 7}d`)
  } else if (/\b(most )?(recently|latest)\s+(updated|modified)\b/i.test(q)) {
    // "most recently updated" - just order by updated, don't filter
    // (let ORDER BY handle it)
  } else if (/\brecent(ly)?\b/i.test(q)) {
    parts.push('updated >= -7d')
  }

  // Determine ordering
  if (/\b(created|newest|oldest)\b/i.test(q) && !/updated/i.test(q)) {
    parts.push('ORDER BY created DESC')
  } else {
    parts.push('ORDER BY updated DESC')
  }

  // Build final JQL
  const filterParts = parts.filter(p => !p.startsWith('ORDER'))
  const orderPart = parts.find(p => p.startsWith('ORDER')) || 'ORDER BY updated DESC'

  if (filterParts.length === 0) {
    return orderPart
  }
  return `${filterParts.join(' AND ')} ${orderPart}`
}
