// Context assembler - smart context formatting based on query intent

import type {
  QueryAnalysis,
  QueryIntent,
  RetrieverResult,
  JiraIssue,
  ProjectAggregations,
  TrendData,
  VelocityMetrics,
  IssueCluster,
} from './types/query-analysis'

/**
 * UI data to be streamed alongside the text context.
 */
export interface UIData {
  /** Aggregation data for bar charts */
  aggregations?: ProjectAggregations[]
  /** Trend data for line charts */
  trends?: TrendData
  /** Velocity metrics */
  velocity?: VelocityMetrics
  /** Issue clusters */
  clusters?: IssueCluster[]
}

/**
 * Assembled context ready for the synthesis phase.
 */
export interface AssembledContext {
  /** Text context for the LLM prompt */
  textContext: string
  /** UI data to be streamed to the client */
  uiData: UIData
  /** Issues found during research */
  allIssues: JiraIssue[]
}

// ---- Formatting functions by intent ----

/**
 * Format context for analytical queries.
 * Uses markdown tables with stats - optimized for LLM understanding.
 */
function formatAnalyticalContext(
  analysis: QueryAnalysis,
  results: RetrieverResult[],
  allIssues: JiraIssue[]
): { textContext: string; uiData: UIData } {
  const parts: string[] = []
  const uiData: UIData = {}

  parts.push('## Research Summary')
  parts.push(`Query type: Analytical`)
  parts.push(`Intent confidence: ${(analysis.confidence * 100).toFixed(0)}%`)
  parts.push('')

  // Process aggregation results
  const aggregations = results
    .filter(r => r.type === 'aggregation' && r.aggregations)
    .flatMap(r => r.aggregations || [])

  if (aggregations.length > 0) {
    uiData.aggregations = aggregations

    for (const agg of aggregations) {
      parts.push(`### Project: ${agg.project_key}`)
      parts.push(`Total issues: **${agg.total_issues}**`)
      parts.push('')

      // Distribution by type
      if (Object.keys(agg.by_type).length > 0) {
        parts.push('#### By Issue Type')
        parts.push('| Type | Count | % |')
        parts.push('|------|-------|---|')
        const total = agg.total_issues || 1
        for (const [type, count] of Object.entries(agg.by_type).sort((a, b) => b[1] - a[1])) {
          const pct = ((count / total) * 100).toFixed(1)
          parts.push(`| ${type} | ${count} | ${pct}% |`)
        }
        parts.push('')
      }

      // Distribution by status
      if (Object.keys(agg.by_status_category).length > 0) {
        parts.push('#### By Status')
        parts.push('| Status | Count | % |')
        parts.push('|--------|-------|---|')
        const total = agg.total_issues || 1
        for (const [status, count] of Object.entries(agg.by_status_category).sort((a, b) => b[1] - a[1])) {
          const pct = ((count / total) * 100).toFixed(1)
          parts.push(`| ${status} | ${count} | ${pct}% |`)
        }
        parts.push('')
      }

      // Top assignees
      if (Object.keys(agg.top_assignees).length > 0) {
        parts.push('#### Top Assignees')
        parts.push('| Assignee | Issues |')
        parts.push('|----------|--------|')
        for (const [assignee, count] of Object.entries(agg.top_assignees).slice(0, 10)) {
          parts.push(`| ${assignee} | ${count} |`)
        }
        parts.push('')
      }

      // Top labels
      if (Object.keys(agg.top_labels).length > 0) {
        parts.push('#### Top Labels')
        parts.push(`${Object.entries(agg.top_labels).slice(0, 10).map(([l, c]) => `\`${l}\` (${c})`).join(', ')}`)
        parts.push('')
      }
    }
  }

  // Process trend results
  const trendResults = results.find(r => r.type === 'trends' && r.trends)
  if (trendResults?.trends) {
    uiData.trends = trendResults.trends
    const trends = trendResults.trends

    parts.push(`### Trends (${trends.days_analyzed} days)`)
    parts.push('| Period | Created | Resolved | Net |')
    parts.push('|--------|---------|----------|-----|')

    for (const period of trends.periods) {
      const start = new Date(period.period_start).toLocaleDateString()
      const end = new Date(period.period_end).toLocaleDateString()
      const netSign = period.net_change >= 0 ? '+' : ''
      parts.push(`| ${start} - ${end} | ${period.total_created} | ${period.total_resolved} | ${netSign}${period.net_change} |`)
    }
    parts.push('')
  }

  // Process velocity results
  const velocityResult = results.find(r => r.type === 'velocity' && r.velocity)
  if (velocityResult?.velocity) {
    uiData.velocity = velocityResult.velocity
    const v = velocityResult.velocity

    parts.push(`### Velocity (${v.project_key})`)
    parts.push(`- **Avg created/week**: ${v.averages.avg_created_per_week}`)
    parts.push(`- **Avg resolved/week**: ${v.averages.avg_resolved_per_week}`)
    parts.push(`- **Backlog trend**: ${v.backlog_trend}`)
    parts.push('')
  }

  // Add sample issues if available
  if (allIssues.length > 0) {
    parts.push(`### Sample Issues (${Math.min(5, allIssues.length)} of ${allIssues.length})`)
    for (const issue of allIssues.slice(0, 5)) {
      parts.push(`- **[${issue.issue_id}]** ${issue.summary} (${issue.status})`)
    }
    parts.push('')
  }

  return { textContext: parts.join('\n'), uiData }
}

/**
 * Format context for exploratory queries.
 * Uses prose with issue summaries grouped logically.
 */
function formatExploratoryContext(
  analysis: QueryAnalysis,
  results: RetrieverResult[],
  allIssues: JiraIssue[]
): { textContext: string; uiData: UIData } {
  const parts: string[] = []
  const uiData: UIData = {}

  parts.push('## Research Summary')
  parts.push(`Query type: Exploratory`)
  parts.push(`Total issues found: ${allIssues.length}`)
  parts.push(`Research phases: ${results.length}`)
  parts.push('')

  // Group issues by type
  const byType = new Map<string, JiraIssue[]>()
  for (const issue of allIssues) {
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

    for (const issue of issues.slice(0, 20)) {
      const assignee = issue.assignee || 'Unassigned'
      const preview = issue.description_preview?.slice(0, 200) || ''

      parts.push(`**[${issue.issue_id}] ${issue.summary}**`)

      // Include timestamps when available
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

  // Include aggregation data if available (for complex queries)
  const aggregations = results
    .filter(r => r.type === 'aggregation' && r.aggregations)
    .flatMap(r => r.aggregations || [])

  if (aggregations.length > 0) {
    uiData.aggregations = aggregations
  }

  return { textContext: parts.join('\n'), uiData }
}

/**
 * Format context for factual queries.
 * Detailed issue info with linked issues.
 */
function formatFactualContext(
  analysis: QueryAnalysis,
  results: RetrieverResult[],
  allIssues: JiraIssue[]
): { textContext: string; uiData: UIData } {
  const parts: string[] = []
  const uiData: UIData = {}

  parts.push('## Issue Details')
  parts.push('')

  // Primary issue (first one, usually the one asked about)
  if (allIssues.length > 0) {
    const primary = allIssues[0]

    parts.push(`### ${primary.issue_id}: ${primary.summary}`)
    parts.push('')
    parts.push(`- **Status**: ${primary.status}`)
    parts.push(`- **Type**: ${primary.issue_type}`)
    parts.push(`- **Assignee**: ${primary.assignee || 'Unassigned'}`)
    parts.push(`- **Project**: ${primary.project_key}`)

    if (primary.labels && primary.labels.length > 0) {
      parts.push(`- **Labels**: ${primary.labels.join(', ')}`)
    }

    if (primary.created_at) {
      parts.push(`- **Created**: ${primary.created_at}`)
    }
    if (primary.updated_at) {
      parts.push(`- **Updated**: ${primary.updated_at}`)
    }

    parts.push('')

    if (primary.description_preview) {
      parts.push('**Description:**')
      parts.push(`> ${primary.description_preview}`)
      parts.push('')
    }
  }

  // Linked issues
  const linkedIssues = allIssues.slice(1)
  if (linkedIssues.length > 0) {
    parts.push('### Related Issues')
    parts.push('')

    for (const issue of linkedIssues.slice(0, 10)) {
      parts.push(`- **[${issue.issue_id}]** ${issue.summary} (${issue.status})`)
    }
    parts.push('')
  }

  return { textContext: parts.join('\n'), uiData }
}

/**
 * Format context for complex queries.
 * Combines multiple formats.
 */
function formatComplexContext(
  analysis: QueryAnalysis,
  results: RetrieverResult[],
  allIssues: JiraIssue[]
): { textContext: string; uiData: UIData } {
  // Complex queries get both analytical and exploratory context
  const analytical = formatAnalyticalContext(analysis, results, allIssues)
  const exploratory = formatExploratoryContext(analysis, results, allIssues)

  return {
    textContext: [
      analytical.textContext,
      '---',
      exploratory.textContext,
    ].join('\n\n'),
    uiData: {
      ...analytical.uiData,
      ...exploratory.uiData,
    },
  }
}

// ---- Main assembler ----

/**
 * Assemble context from retriever results based on query intent.
 *
 * This is the key function that formats research results appropriately
 * for the query type - tables for analytical, prose for exploratory, etc.
 */
export function assembleContext(
  analysis: QueryAnalysis,
  results: RetrieverResult[],
  allIssues: JiraIssue[]
): AssembledContext {
  let formatted: { textContext: string; uiData: UIData }

  switch (analysis.intent) {
    case 'analytical':
      formatted = formatAnalyticalContext(analysis, results, allIssues)
      break
    case 'factual':
      formatted = formatFactualContext(analysis, results, allIssues)
      break
    case 'complex':
      formatted = formatComplexContext(analysis, results, allIssues)
      break
    case 'exploratory':
    default:
      formatted = formatExploratoryContext(analysis, results, allIssues)
      break
  }

  return {
    textContext: formatted.textContext,
    uiData: formatted.uiData,
    allIssues,
  }
}
