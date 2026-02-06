// Query analyzer - intelligent intent classification and entity extraction

import type {
  QueryIntent,
  QueryAnalysis,
  QueryEntities,
  TimeRange,
  AnalyticalParams,
} from './types/query-analysis'

// ---- Pattern definitions ----

/**
 * Patterns that indicate ANALYTICAL queries (NEW - this is what was missing).
 * These queries want distributions, counts, trends - not individual issues.
 */
const ANALYTICAL_PATTERNS = [
  // Distribution/breakdown queries
  /\b(distribution|breakdown|split|composition)\b/i,
  /\bhow many\b/i,
  /\b(count|total|number) of\b/i,

  // Grouping queries - "by status", "by assignee", etc.
  /\bby\s+(status|type|assignee|priority|project|label|component)\b/i,
  /\bgrouped?\s+by\b/i,

  // Top/most/least queries
  /\b(top|most|least|highest|lowest)\s+\d*\s*(active|busy|productive)?\s*(assignees?|contributors?|developers?|people|issues?|bugs?)/i,
  /\bwho (has|have|is|are)\s+(the\s+)?(most|least)\b/i,

  // Trend/velocity queries
  /\b(trend|velocity|throughput|burn\s?down|burn\s?up)\b/i,
  /\b(this|last|past)\s+(week|month|quarter|sprint)\b.*\b(created|resolved|closed|done)\b/i,

  // Comparison queries
  /\bcompare\b/i,
  /\bvs\.?\b/i,

  // Statistical queries
  /\b(average|avg|mean|median|percentage|percent|%)\b/i,
]

/**
 * Patterns that indicate FACTUAL queries about specific issues.
 */
const FACTUAL_PATTERNS = [
  // Specific issue key
  /^(what is|tell me about|show me|describe)\s+[A-Z]+-\d+/i,
  /\b[A-Z]+-\d+\b/,  // Any issue key mentioned
]

/**
 * Patterns that indicate EXPLORATORY queries (open-ended research).
 */
const EXPLORATORY_PATTERNS = [
  /\bwhat (is|are) (the )?(status|progress|state) of\b/i,
  /\bwhat('s| is| are)?\s*(been\s+)?(done|happening|going on)\s+(with|on|in)\b/i,
  /\b(related to|about|regarding|concerning|involving)\b/i,
  /\bwork (done|completed|in progress)\s+(on|for|with)\b/i,
  /\btell me about\b/i,
  /\bshow me\s+(issues?|work|activity)\b/i,
  /\bwhat do (we|I) know about\b/i,
  /\bhow (do|does|did|can|could|should)\b/i,
  /\bwhy (do|does|did|is|are|was|were)\b/i,
  /\bexplain\b/i,
]

/**
 * Patterns for JQL-style queries (structured search).
 */
const JQL_PATTERNS = [
  /\b(open|closed|resolved|unresolved)\s+(bugs?|issues?|tasks?|stories?)/i,
  /\b(my|assigned to me)\s+(issues?|bugs?|tasks?)/i,
  /\b(in progress|backlog|done|to do)\b/i,
  /\brecent(ly)?\s+(updated|created|modified)/i,
  /\b(most )?(recently|latest)\s+(updated|created|modified)/i,
  /\b(last|past)\s+\d+\s+(days?|weeks?|months?)/i,
  /\bstatus\s*[=:]/i,
  /\bassignee\s*[=:]/i,
  /\bproject\s*[=:]/i,
  /\bpriority\s*[=:]/i,
]

/**
 * Patterns for epic expansion.
 */
const EPIC_PATTERNS = [
  /\bfeature/i,
  /\binitiative\b/i,
  /\bplatform\b/i,
  /\bsystem\b/i,
  /\bmodule\b/i,
]

// ---- Entity extraction ----

const PROJECT_KEYS = ['DS', 'AI', 'INFRA', 'OPS', 'QA']  // Known project keys
const ISSUE_TYPES = ['Bug', 'Story', 'Task', 'Epic', 'Sub-task', 'Improvement', 'New Feature']
const STATUSES = ['Backlog', 'To Do', 'In Progress', 'In Review', 'Done', 'Closed', 'Open']
const PRIORITIES = ['Highest', 'High', 'Medium', 'Low', 'Lowest', 'Critical', 'Major', 'Minor', 'Trivial']

function extractEntities(query: string, currentUser: string): QueryEntities {
  const q = query.toLowerCase()
  const entities: QueryEntities = {
    projects: [],
    timeRange: null,
    assignees: [],
    issueTypes: [],
    statuses: [],
    issueKeys: [],
    priorities: [],
    labels: [],
  }

  // Extract issue keys (e.g., DS-1234)
  const issueKeyMatches = query.match(/\b[A-Z]+-\d+\b/g)
  if (issueKeyMatches) {
    entities.issueKeys = issueKeyMatches
    // Also extract project keys from issue keys
    for (const key of issueKeyMatches) {
      const project = key.split('-')[0]
      if (!entities.projects.includes(project)) {
        entities.projects.push(project)
      }
    }
  }

  // Extract project keys
  for (const project of PROJECT_KEYS) {
    if (new RegExp(`\\b${project}\\b`, 'i').test(query)) {
      if (!entities.projects.includes(project)) {
        entities.projects.push(project)
      }
    }
  }

  // Default to DS if no project specified and not asking for "all projects"
  if (entities.projects.length === 0 &&
      !/\b(all|every|any)\s+projects?\b/i.test(q) &&
      !/\bacross\s+(all\s+)?projects?\b/i.test(q)) {
    entities.projects = ['DS']
  }

  // Extract issue types
  for (const type of ISSUE_TYPES) {
    if (new RegExp(`\\b${type}s?\\b`, 'i').test(query)) {
      entities.issueTypes.push(type)
    }
  }

  // Extract statuses
  for (const status of STATUSES) {
    if (new RegExp(`\\b${status}\\b`, 'i').test(query)) {
      entities.statuses.push(status)
    }
  }

  // Extract priorities
  for (const priority of PRIORITIES) {
    if (new RegExp(`\\b${priority}\\b`, 'i').test(query)) {
      entities.priorities.push(priority)
    }
  }

  // Extract time ranges
  const timeRange = extractTimeRange(query)
  if (timeRange) {
    entities.timeRange = timeRange
  }

  // Extract assignee references
  if (/\b(my|assigned to me)\b/i.test(q)) {
    entities.assignees.push(currentUser)
  }

  return entities
}

function extractTimeRange(query: string): TimeRange | null {
  const q = query.toLowerCase()

  // Relative time patterns
  if (/\btoday\b/.test(q)) {
    return { type: 'relative', relative: 'startOfDay()' }
  }
  if (/\byesterday\b/.test(q)) {
    return { type: 'relative', relative: '-1d' }
  }
  if (/\bthis week\b/.test(q)) {
    return { type: 'relative', relative: 'startOfWeek()' }
  }
  if (/\bthis month\b/.test(q)) {
    return { type: 'relative', relative: 'startOfMonth()' }
  }

  // "last/past N days/weeks/months"
  const daysMatch = q.match(/\b(last|past)\s+(\d+)\s+days?\b/)
  if (daysMatch) {
    return { type: 'relative', relative: `-${daysMatch[2]}d` }
  }
  const weeksMatch = q.match(/\b(last|past)\s+(\d+)\s+weeks?\b/)
  if (weeksMatch) {
    return { type: 'relative', relative: `-${parseInt(weeksMatch[2]) * 7}d` }
  }
  const monthsMatch = q.match(/\b(last|past)\s+(\d+)\s+months?\b/)
  if (monthsMatch) {
    return { type: 'relative', relative: `-${parseInt(monthsMatch[2]) * 30}d` }
  }

  // "recent" fallback
  if (/\brecent(ly)?\b/.test(q)) {
    return { type: 'relative', relative: '-7d' }
  }

  return null
}

// ---- Analytical parameter extraction ----

function extractAnalyticalParams(query: string): AnalyticalParams | undefined {
  const q = query.toLowerCase()
  const groupBy: string[] = []

  // Check for grouping patterns
  const groupByMatch = q.match(/\bby\s+(status|type|assignee|priority|project|label|component)/i)
  if (groupByMatch) {
    groupBy.push(groupByMatch[1].toLowerCase())
  }

  // Determine aggregation type
  let aggregationType: 'count' | 'distribution' | 'trend' | 'velocity' = 'distribution'

  if (/\b(trend|over time|weekly|monthly)\b/i.test(q)) {
    aggregationType = 'trend'
  } else if (/\b(velocity|throughput)\b/i.test(q)) {
    aggregationType = 'velocity'
  } else if (/\b(count|total|how many)\b/i.test(q)) {
    aggregationType = 'count'
  }

  if (groupBy.length > 0 || aggregationType !== 'distribution') {
    return {
      aggregationType,
      groupBy: groupBy.length > 0 ? groupBy : ['status'],  // Default grouping
    }
  }

  return undefined
}

// ---- JQL generation ----

function buildJqlFromAnalysis(entities: QueryEntities, currentUser: string): string {
  const parts: string[] = []

  // Project filter
  if (entities.projects.length > 0) {
    if (entities.projects.length === 1) {
      parts.push(`project = ${entities.projects[0]}`)
    } else {
      parts.push(`project IN (${entities.projects.join(', ')})`)
    }
  }

  // Issue types
  if (entities.issueTypes.length > 0) {
    if (entities.issueTypes.length === 1) {
      parts.push(`issuetype = ${entities.issueTypes[0]}`)
    } else {
      parts.push(`issuetype IN (${entities.issueTypes.join(', ')})`)
    }
  }

  // Statuses
  if (entities.statuses.length > 0) {
    if (entities.statuses.includes('Open') || entities.statuses.includes('Backlog')) {
      parts.push('resolution = Unresolved')
    } else if (entities.statuses.includes('Done') || entities.statuses.includes('Closed')) {
      parts.push('resolution IS NOT EMPTY')
    } else {
      parts.push(`status IN ("${entities.statuses.join('", "')}")`)
    }
  }

  // Assignee
  if (entities.assignees.length > 0) {
    parts.push(`assignee = "${entities.assignees[0]}"`)
  }

  // Time range
  if (entities.timeRange) {
    parts.push(`updated >= ${entities.timeRange.relative}`)
  }

  // Default ordering
  const orderBy = 'ORDER BY updated DESC'

  // Build final JQL
  if (parts.length === 0) {
    // Default filter for safety
    return `updated >= -30d ${orderBy}`
  }

  return `${parts.join(' AND ')} ${orderBy}`
}

// ---- Main analyzer ----

/**
 * Analyze a user query to determine intent, extract entities, and generate search parameters.
 *
 * This replaces the simpler regex-based classifier with a more sophisticated analysis
 * that can properly route analytical queries to aggregation endpoints.
 */
export function analyzeQuery(query: string, currentUser: string): QueryAnalysis {
  const q = query.trim()

  // Extract entities first
  const entities = extractEntities(q, currentUser)

  // Determine intent by pattern matching
  const isAnalytical = ANALYTICAL_PATTERNS.some(p => p.test(q))
  const isFactual = FACTUAL_PATTERNS.some(p => p.test(q)) && entities.issueKeys.length > 0
  const isExploratory = EXPLORATORY_PATTERNS.some(p => p.test(q))
  const isJqlStyle = JQL_PATTERNS.some(p => p.test(q))

  // Classify intent
  let intent: QueryIntent = 'exploratory'  // Default
  let confidence = 0.6

  if (isFactual && entities.issueKeys.length > 0) {
    // Specific issue lookup takes priority
    intent = 'factual'
    confidence = 0.95
  } else if (isAnalytical) {
    // Analytical queries - distributions, trends, etc.
    intent = 'analytical'
    confidence = 0.9
  } else if (isExploratory && isJqlStyle) {
    // Mixed intent
    intent = 'complex'
    confidence = 0.7
  } else if (isExploratory) {
    intent = 'exploratory'
    confidence = 0.8
  } else if (isJqlStyle) {
    // Pure JQL-style query
    intent = 'exploratory'  // JQL is still exploratory, just structured
    confidence = 0.85
  }

  // Should we expand epics?
  const shouldExpandEpics =
    intent === 'exploratory' ||
    intent === 'complex' ||
    EPIC_PATTERNS.some(p => p.test(q))

  // Should we fetch links?
  const shouldFetchLinks =
    intent === 'factual' ||
    intent === 'exploratory'

  // Build result
  const analysis: QueryAnalysis = {
    originalQuery: q,
    intent,
    confidence,
    entities,
    shouldExpandEpics,
    shouldFetchLinks,
    semanticQuery: q,  // Always provide for potential semantic search
  }

  // Add JQL for structured queries
  if (isJqlStyle || intent === 'factual' || intent === 'complex') {
    analysis.jqlQuery = buildJqlFromAnalysis(entities, currentUser)
  }

  // Add analytical params for analytical queries
  if (intent === 'analytical') {
    analysis.analyticalParams = extractAnalyticalParams(q)
  }

  return analysis
}

/**
 * Convenience function for backward compatibility with existing code.
 * Maps the new QueryAnalysis to the old QueryClassification format.
 */
export function analyzeQueryCompat(query: string, currentUser: string): {
  type: 'semantic' | 'jql' | 'hybrid' | 'analytical'
  semanticQuery?: string
  jqlQuery?: string
  shouldExpandEpics: boolean
  shouldFetchLinks: boolean
  analyticalParams?: AnalyticalParams
  entities: QueryEntities
} {
  const analysis = analyzeQuery(query, currentUser)

  // Map intent to legacy type
  let type: 'semantic' | 'jql' | 'hybrid' | 'analytical' = 'semantic'
  if (analysis.intent === 'analytical') {
    type = 'analytical'
  } else if (analysis.jqlQuery && analysis.semanticQuery && analysis.intent !== 'factual') {
    type = 'hybrid'
  } else if (analysis.jqlQuery) {
    type = 'jql'
  }

  return {
    type,
    semanticQuery: analysis.semanticQuery,
    jqlQuery: analysis.jqlQuery,
    shouldExpandEpics: analysis.shouldExpandEpics,
    shouldFetchLinks: analysis.shouldFetchLinks,
    analyticalParams: analysis.analyticalParams,
    entities: analysis.entities,
  }
}
