// Insights retriever - fetches trends, velocity, and clusters from the backend

import type {
  TrendData,
  VelocityMetrics,
  IssueCluster,
  RetrieverResult,
} from '../types/query-analysis'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * Fetch trend analysis for a project.
 */
export async function fetchTrends(
  projectKey: string | null,
  days: number = 30,
  periodDays: number = 7
): Promise<RetrieverResult> {
  try {
    const params = new URLSearchParams()
    if (projectKey) params.set('project_key', projectKey)
    params.set('days', days.toString())
    params.set('period_days', periodDays.toString())

    const response = await fetch(`${BACKEND_URL}/api/insights/trends?${params}`)

    if (!response.ok) {
      return {
        type: 'trends',
        error: `Failed to fetch trends: ${response.status}`,
        metadata: { project_key: projectKey || 'all' },
      }
    }

    const data: TrendData = await response.json()

    return {
      type: 'trends',
      trends: data,
      metadata: {
        project_key: projectKey || 'all',
        count: data.periods.length,
      },
    }
  } catch (error) {
    return {
      type: 'trends',
      error: `Trends error: ${error}`,
      metadata: { project_key: projectKey || 'all' },
    }
  }
}

/**
 * Fetch velocity metrics for a project.
 */
export async function fetchVelocity(
  projectKey: string,
  weeks: number = 4
): Promise<RetrieverResult> {
  try {
    const params = new URLSearchParams()
    params.set('weeks', weeks.toString())

    const response = await fetch(
      `${BACKEND_URL}/api/insights/velocity/${projectKey}?${params}`
    )

    if (!response.ok) {
      return {
        type: 'velocity',
        error: `Failed to fetch velocity: ${response.status}`,
        metadata: { project_key: projectKey },
      }
    }

    const data: VelocityMetrics = await response.json()

    return {
      type: 'velocity',
      velocity: data,
      metadata: {
        project_key: projectKey,
        count: data.weeks_analyzed,
      },
    }
  } catch (error) {
    return {
      type: 'velocity',
      error: `Velocity error: ${error}`,
      metadata: { project_key: projectKey },
    }
  }
}

/**
 * Fetch issue clusters.
 */
export async function fetchClusters(
  projectKey: string | null,
  nClusters: number = 5,
  minClusterSize: number = 3
): Promise<RetrieverResult> {
  try {
    const params = new URLSearchParams()
    if (projectKey) params.set('project_key', projectKey)
    params.set('n_clusters', nClusters.toString())
    params.set('min_cluster_size', minClusterSize.toString())

    const response = await fetch(`${BACKEND_URL}/api/insights/clusters?${params}`)

    if (!response.ok) {
      return {
        type: 'clusters',
        error: `Failed to fetch clusters: ${response.status}`,
        metadata: { project_key: projectKey || 'all' },
      }
    }

    const data: { clusters: IssueCluster[] } = await response.json()

    return {
      type: 'clusters',
      clusters: data.clusters,
      metadata: {
        project_key: projectKey || 'all',
        count: data.clusters.length,
      },
    }
  } catch (error) {
    return {
      type: 'clusters',
      error: `Clusters error: ${error}`,
      metadata: { project_key: projectKey || 'all' },
    }
  }
}

/**
 * Fetch bug patterns.
 */
export async function fetchBugPatterns(
  projectKey: string | null,
  minSimilarity: number = 0.8
): Promise<{
  project_key: string | null
  min_similarity: number
  patterns: Array<{
    pattern_id: number
    bug_count: number
    bugs: string[]
    common_summary_terms: string[]
    statuses: Record<string, number>
  }>
  error?: string
}> {
  try {
    const params = new URLSearchParams()
    if (projectKey) params.set('project_key', projectKey)
    params.set('min_similarity', minSimilarity.toString())

    const response = await fetch(`${BACKEND_URL}/api/insights/bug-patterns?${params}`)

    if (!response.ok) {
      return {
        project_key: projectKey,
        min_similarity: minSimilarity,
        patterns: [],
        error: `Failed to fetch bug patterns: ${response.status}`,
      }
    }

    return response.json()
  } catch (error) {
    return {
      project_key: projectKey,
      min_similarity: minSimilarity,
      patterns: [],
      error: `Bug patterns error: ${error}`,
    }
  }
}

/**
 * Fetch comprehensive project summary.
 */
export async function fetchProjectSummary(
  projectKey: string
): Promise<{
  project_key: string
  aggregations?: {
    total_issues: number
    by_type: Record<string, number>
    by_status_category: Record<string, number>
    by_priority: Record<string, number>
    top_assignees: Record<string, number>
  }
  velocity?: VelocityMetrics
  trends?: Array<{
    period_start: string
    period_end: string
    total_created: number
    total_resolved: number
    net_change: number
  }>
  error?: string
}> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/insights/summary/${projectKey}`)

    if (!response.ok) {
      return {
        project_key: projectKey,
        error: `Failed to fetch summary: ${response.status}`,
      }
    }

    return response.json()
  } catch (error) {
    return {
      project_key: projectKey,
      error: `Summary error: ${error}`,
    }
  }
}
