// Aggregation retriever - fetches project aggregations from the backend

import type { ProjectAggregations, RetrieverResult } from '../types/query-analysis'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * Fetch aggregations for a single project.
 */
export async function fetchProjectAggregations(
  projectKey: string
): Promise<RetrieverResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/aggregations/${projectKey}`)

    if (!response.ok) {
      return {
        type: 'aggregation',
        error: `Failed to fetch aggregations: ${response.status}`,
        metadata: { project_key: projectKey },
      }
    }

    const data: ProjectAggregations = await response.json()

    return {
      type: 'aggregation',
      aggregations: [data],
      metadata: {
        project_key: projectKey,
        count: data.total_issues,
      },
    }
  } catch (error) {
    return {
      type: 'aggregation',
      error: `Aggregation error: ${error}`,
      metadata: { project_key: projectKey },
    }
  }
}

/**
 * Fetch aggregations for multiple projects.
 */
export async function fetchMultiProjectAggregations(
  projectKeys: string[]
): Promise<RetrieverResult> {
  try {
    const response = await fetch(`${BACKEND_URL}/api/aggregations/multi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_keys: projectKeys }),
    })

    if (!response.ok) {
      return {
        type: 'aggregation',
        error: `Failed to fetch aggregations: ${response.status}`,
        metadata: { project_keys: projectKeys.join(', ') },
      }
    }

    const data: ProjectAggregations[] = await response.json()

    return {
      type: 'aggregation',
      aggregations: data,
      metadata: {
        project_keys: projectKeys.join(', '),
        count: data.reduce((sum, p) => sum + p.total_issues, 0),
      },
    }
  } catch (error) {
    return {
      type: 'aggregation',
      error: `Aggregation error: ${error}`,
      metadata: { project_keys: projectKeys.join(', ') },
    }
  }
}

/**
 * Fetch assignee distribution for a project.
 */
export async function fetchAssigneeDistribution(
  projectKey: string,
  limit: number = 20
): Promise<{
  project_key: string
  total_issues: number
  assignees: Array<{ name: string; count: number }>
  error?: string
}> {
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/aggregations/${projectKey}/assignees?limit=${limit}`
    )

    if (!response.ok) {
      return {
        project_key: projectKey,
        total_issues: 0,
        assignees: [],
        error: `Failed to fetch assignees: ${response.status}`,
      }
    }

    return response.json()
  } catch (error) {
    return {
      project_key: projectKey,
      total_issues: 0,
      assignees: [],
      error: `Assignee fetch error: ${error}`,
    }
  }
}

/**
 * Fetch type distribution for a project.
 */
export async function fetchTypeDistribution(
  projectKey: string
): Promise<{
  project_key: string
  total_issues: number
  types: Array<{ name: string; count: number }>
  error?: string
}> {
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/aggregations/${projectKey}/types`
    )

    if (!response.ok) {
      return {
        project_key: projectKey,
        total_issues: 0,
        types: [],
        error: `Failed to fetch types: ${response.status}`,
      }
    }

    return response.json()
  } catch (error) {
    return {
      project_key: projectKey,
      total_issues: 0,
      types: [],
      error: `Type fetch error: ${error}`,
    }
  }
}

/**
 * Fetch status distribution for a project.
 */
export async function fetchStatusDistribution(
  projectKey: string
): Promise<{
  project_key: string
  total_issues: number
  statuses: Array<{ name: string; count: number }>
  error?: string
}> {
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/aggregations/${projectKey}/statuses`
    )

    if (!response.ok) {
      return {
        project_key: projectKey,
        total_issues: 0,
        statuses: [],
        error: `Failed to fetch statuses: ${response.status}`,
      }
    }

    return response.json()
  } catch (error) {
    return {
      project_key: projectKey,
      total_issues: 0,
      statuses: [],
      error: `Status fetch error: ${error}`,
    }
  }
}
