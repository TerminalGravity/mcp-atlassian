// Query analysis types for the research pipeline

/**
 * Primary intent classification for user queries.
 *
 * - factual: Looking for specific information about a known entity (e.g., "What is DS-1234?")
 * - analytical: Seeking aggregated data, distributions, trends (e.g., "Show me bugs by priority")
 * - exploratory: Open-ended research about a topic (e.g., "What work has been done on payments?")
 * - complex: Multi-faceted queries that need multiple retrieval strategies
 */
export type QueryIntent = 'factual' | 'analytical' | 'exploratory' | 'complex'

/**
 * Time range specification extracted from queries.
 */
export interface TimeRange {
  type: 'relative' | 'absolute'
  // For relative: "-7d", "-30d", "this week", etc.
  relative?: string
  // For absolute: specific date range
  start?: string
  end?: string
}

/**
 * Aggregation parameters for analytical queries.
 */
export interface AnalyticalParams {
  /** Type of aggregation: count, distribution, or trend */
  aggregationType: 'count' | 'distribution' | 'trend' | 'velocity'
  /** Fields to group by: status, type, assignee, priority, etc. */
  groupBy: string[]
  /** Optional metric to compute */
  metric?: 'count' | 'velocity' | 'cycle_time'
}

/**
 * Entities extracted from the query.
 */
export interface QueryEntities {
  /** Project keys mentioned (e.g., DS, AI) */
  projects: string[]
  /** Time range if specified */
  timeRange: TimeRange | null
  /** Assignee names mentioned */
  assignees: string[]
  /** Issue types mentioned (Bug, Story, Epic, etc.) */
  issueTypes: string[]
  /** Status values mentioned */
  statuses: string[]
  /** Specific issue keys mentioned (e.g., DS-1234) */
  issueKeys: string[]
  /** Priority values mentioned */
  priorities: string[]
  /** Labels mentioned */
  labels: string[]
}

/**
 * Full query analysis result.
 */
export interface QueryAnalysis {
  /** The original query string */
  originalQuery: string
  /** Primary intent classification */
  intent: QueryIntent
  /** Confidence score 0-1 */
  confidence: number
  /** Extracted entities */
  entities: QueryEntities
  /** Parameters for analytical queries */
  analyticalParams?: AnalyticalParams
  /** Generated semantic query for vector search */
  semanticQuery?: string
  /** Generated JQL for structured search */
  jqlQuery?: string
  /** Whether to expand epics found in results */
  shouldExpandEpics: boolean
  /** Whether to fetch linked issues */
  shouldFetchLinks: boolean
}

// ---- Retriever result types ----

/**
 * Common interface for Jira issues from any retriever.
 */
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
  created_at?: string
  updated_at?: string
}

/**
 * Aggregation data from the aggregations endpoint.
 */
export interface ProjectAggregations {
  project_key: string
  total_issues: number
  by_type: Record<string, number>
  by_status_category: Record<string, number>
  by_priority: Record<string, number>
  top_assignees: Record<string, number>
  top_labels: Record<string, number>
  top_components: Record<string, number>
  error?: string
}

/**
 * Trend data point from insights endpoint.
 */
export interface TrendPeriod {
  period_start: string
  period_end: string
  total_created: number
  total_resolved: number
  net_change: number
  by_type: Record<string, number>
  by_priority: Record<string, number>
  trending_labels: Array<{ label: string; count: number }>
}

/**
 * Trend analysis response.
 */
export interface TrendData {
  project_key: string | null
  days_analyzed: number
  period_days: number
  periods: TrendPeriod[]
}

/**
 * Weekly velocity metrics.
 */
export interface WeeklyMetric {
  week: number
  week_ending: string
  created: number
  resolved: number
  net: number
}

/**
 * Velocity metrics response.
 */
export interface VelocityMetrics {
  project_key: string
  weeks_analyzed: number
  weekly_metrics: WeeklyMetric[]
  averages: {
    avg_created_per_week: number
    avg_resolved_per_week: number
    avg_net_change: number
  }
  backlog_trend: 'growing' | 'shrinking'
  error?: string
}

/**
 * Issue cluster from clustering endpoint.
 */
export interface IssueCluster {
  cluster_id: number
  size: number
  representative_issues: string[]
  common_labels: string[]
  common_components: string[]
  theme_keywords: string[]
}

/**
 * Unified retriever result type.
 */
export interface RetrieverResult {
  type: 'semantic' | 'jql' | 'aggregation' | 'insights' | 'trends' | 'velocity' | 'clusters' | 'links' | 'epic-children'
  /** Issues from search-based retrievers */
  issues?: JiraIssue[]
  /** Aggregation data */
  aggregations?: ProjectAggregations[]
  /** Trend data */
  trends?: TrendData
  /** Velocity metrics */
  velocity?: VelocityMetrics
  /** Issue clusters */
  clusters?: IssueCluster[]
  /** Error message if retrieval failed */
  error?: string
  /** Metadata about the retrieval */
  metadata?: Record<string, unknown>
}

// ---- Message part types for streaming ----

/**
 * New message part types for the chat response.
 */
export interface AggregationsMessagePart {
  type: 'data-aggregations'
  id: string
  data: ProjectAggregations[]
}

export interface TrendsMessagePart {
  type: 'data-trends'
  id: string
  data: TrendData
}

export interface VelocityMessagePart {
  type: 'data-velocity'
  id: string
  data: VelocityMetrics
}

export interface ClustersMessagePart {
  type: 'data-clusters'
  id: string
  data: IssueCluster[]
}

export type AnalyticalMessagePart =
  | AggregationsMessagePart
  | TrendsMessagePart
  | VelocityMessagePart
  | ClustersMessagePart
