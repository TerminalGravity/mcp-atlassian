// Retrievers index - unified retriever execution

import type {
  JiraIssue,
  RetrieverResult,
  QueryAnalysis,
} from '../types/query-analysis'
import type { RetrieverRoute, QueryRoute } from '../query-router'
import { fetchProjectAggregations, fetchMultiProjectAggregations } from './aggregation-retriever'
import { fetchTrends, fetchVelocity, fetchClusters } from './insights-retriever'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ---- Existing search retrievers (refactored from research-pipeline.ts) ----

/**
 * Search issues using semantic/vector search.
 */
export async function searchVectorStore(
  query: string,
  limit: number = 10
): Promise<RetrieverResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/vector-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, limit }),
    })
    if (!response.ok) {
      return {
        type: 'semantic',
        issues: [],
        error: `Search failed: ${response.status}`,
        metadata: { query },
      }
    }
    const data = await response.json()
    return {
      type: 'semantic',
      issues: data.issues || [],
      metadata: { query, count: data.count || 0 },
    }
  } catch (error) {
    return {
      type: 'semantic',
      issues: [],
      error: `Search error: ${error}`,
      metadata: { query },
    }
  }
}

/**
 * Search issues using JQL.
 */
export async function searchJQL(
  jql: string,
  limit: number = 10
): Promise<RetrieverResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jql, limit }),
    })
    if (!response.ok) {
      return {
        type: 'jql',
        issues: [],
        error: `JQL failed: ${response.status}`,
        metadata: { jql },
      }
    }
    const data = await response.json()
    return {
      type: 'jql',
      issues: data.issues || [],
      error: data.error,
      metadata: { jql, count: data.count || 0 },
    }
  } catch (error) {
    return {
      type: 'jql',
      issues: [],
      error: `JQL error: ${error}`,
      metadata: { jql },
    }
  }
}

/**
 * Get linked issues for an issue key.
 */
export async function getLinkedIssues(
  issueKey: string
): Promise<RetrieverResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/linked-issues`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issueKey }),
    })
    if (!response.ok) {
      return {
        type: 'links',
        issues: [],
        error: `Links failed: ${response.status}`,
        metadata: { issueKey },
      }
    }
    const data = await response.json()
    return {
      type: 'links',
      issues: data.issues || [],
      error: data.error,
      metadata: { issueKey, count: data.count || 0 },
    }
  } catch (error) {
    return {
      type: 'links',
      issues: [],
      error: `Links error: ${error}`,
      metadata: { issueKey },
    }
  }
}

/**
 * Get children of an epic.
 */
export async function getEpicChildren(
  epicKey: string
): Promise<RetrieverResult> {
  // Try parent field first, then Epic Link
  let result = await searchJQL(`parent = ${epicKey} ORDER BY issuetype, status`, 30)

  if ((result.issues?.length || 0) < 3 && !result.error) {
    const epicLinkResult = await searchJQL(
      `"Epic Link" = ${epicKey} ORDER BY issuetype, status`,
      30
    )
    if ((epicLinkResult.issues?.length || 0) > (result.issues?.length || 0)) {
      result = epicLinkResult
    }
  }

  return {
    type: 'epic-children',
    issues: result.issues,
    error: result.error,
    metadata: { epicKey, count: result.issues?.length || 0 },
  }
}

// ---- Unified retriever execution ----

/**
 * Execute a single retriever route.
 */
async function executeRetriever(
  route: RetrieverRoute,
  context: { issues?: JiraIssue[] }
): Promise<RetrieverResult> {
  const { type, params } = route

  switch (type) {
    case 'semantic':
      return searchVectorStore(
        params?.query as string || '',
        params?.limit as number || 15
      )

    case 'jql':
      return searchJQL(
        params?.jql as string || '',
        params?.limit as number || 20
      )

    case 'aggregation': {
      const projectKey = params?.project_key as string
      if (!projectKey) {
        return {
          type: 'aggregation',
          error: 'No project key provided',
        }
      }
      return fetchProjectAggregations(projectKey)
    }

    case 'trends':
      return fetchTrends(
        params?.project_key as string | null,
        params?.days as number || 30,
        params?.period_days as number || 7
      )

    case 'velocity': {
      const projectKey = params?.project_key as string
      if (!projectKey) {
        return {
          type: 'velocity',
          error: 'No project key provided',
        }
      }
      return fetchVelocity(
        projectKey,
        params?.weeks as number || 4
      )
    }

    case 'clusters':
      return fetchClusters(
        params?.project_key as string | null,
        params?.n_clusters as number || 5,
        params?.min_cluster_size as number || 3
      )

    case 'epic-children': {
      // Get epics from context issues
      const epics = context.issues?.filter(i => i.issue_type === 'Epic') || []
      const maxEpics = params?.limit as number || 3
      const results: JiraIssue[] = []

      for (const epic of epics.slice(0, maxEpics)) {
        const childResult = await getEpicChildren(epic.issue_id)
        if (childResult.issues) {
          results.push(...childResult.issues)
        }
      }

      return {
        type: 'epic-children',
        issues: results,
        metadata: { count: results.length },
      }
    }

    case 'links': {
      // Get first issue from context or params
      const issueKey = params?.issueKey as string || context.issues?.[0]?.issue_id
      if (!issueKey) {
        return {
          type: 'links',
          issues: [],
          metadata: { count: 0 },
        }
      }
      return getLinkedIssues(issueKey)
    }

    default:
      return {
        type: type as RetrieverResult['type'],
        error: `Unknown retriever type: ${type}`,
      }
  }
}

/**
 * Execute all retrievers in a query route.
 *
 * Returns results as they complete, along with aggregated issues.
 */
export async function executeRetrievers(
  route: QueryRoute
): Promise<{
  results: RetrieverResult[]
  allIssues: JiraIssue[]
}> {
  const results: RetrieverResult[] = []
  const allIssues: JiraIssue[] = []
  const seenIssueIds = new Set<string>()

  const addIssues = (issues?: JiraIssue[]) => {
    if (!issues) return
    for (const issue of issues) {
      if (!seenIssueIds.has(issue.issue_id)) {
        seenIssueIds.add(issue.issue_id)
        allIssues.push(issue)
      }
    }
  }

  // Execute primary retrievers
  if (route.parallelPrimary) {
    // Run in parallel
    const primaryResults = await Promise.all(
      route.primary.map(r => executeRetriever(r, { issues: allIssues }))
    )
    for (const result of primaryResults) {
      results.push(result)
      addIssues(result.issues)
    }
  } else {
    // Run sequentially
    for (const retriever of route.primary) {
      const result = await executeRetriever(retriever, { issues: allIssues })
      results.push(result)
      addIssues(result.issues)
    }
  }

  // Execute secondary retrievers (always sequential, may depend on primary results)
  for (const retriever of route.secondary) {
    const result = await executeRetriever(retriever, { issues: allIssues })
    results.push(result)
    addIssues(result.issues)
  }

  return { results, allIssues }
}

// Re-export specific retrievers for direct use
export { fetchProjectAggregations, fetchMultiProjectAggregations }
export { fetchTrends, fetchVelocity, fetchClusters }
