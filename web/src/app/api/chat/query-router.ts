// Query router - maps intent to retriever combinations

import type { QueryAnalysis, QueryIntent } from './types/query-analysis'

/**
 * Retriever types available in the pipeline.
 */
export type RetrieverType =
  | 'semantic'
  | 'jql'
  | 'aggregation'
  | 'trends'
  | 'velocity'
  | 'clusters'
  | 'epic-children'
  | 'links'

/**
 * Route configuration for a retriever.
 */
export interface RetrieverRoute {
  /** The retriever to use */
  type: RetrieverType
  /** Priority order (lower = higher priority) */
  priority: number
  /** Whether this retriever is required */
  required: boolean
  /** Configuration parameters */
  params?: Record<string, unknown>
}

/**
 * Query route - the execution plan for a query.
 */
export interface QueryRoute {
  /** The analyzed query */
  analysis: QueryAnalysis
  /** Primary retrievers to run (can run in parallel) */
  primary: RetrieverRoute[]
  /** Secondary retrievers (run after primary, may depend on results) */
  secondary: RetrieverRoute[]
  /** Whether primary retrievers can run in parallel */
  parallelPrimary: boolean
}

/**
 * Route configuration by intent type.
 */
const INTENT_ROUTES: Record<QueryIntent, (analysis: QueryAnalysis) => Pick<QueryRoute, 'primary' | 'secondary' | 'parallelPrimary'>> = {
  /**
   * Factual queries - specific issue lookup.
   * Fast path: JQL to fetch the specific issue, then links.
   */
  factual: (analysis) => ({
    primary: [
      {
        type: 'jql',
        priority: 1,
        required: true,
        params: {
          jql: analysis.jqlQuery || `key IN (${analysis.entities.issueKeys.join(', ')})`,
          limit: 10,
        },
      },
    ],
    secondary: [
      {
        type: 'links',
        priority: 2,
        required: false,
        params: { issueKey: analysis.entities.issueKeys[0] },
      },
    ],
    parallelPrimary: false,
  }),

  /**
   * Analytical queries - aggregations, trends, distributions.
   * Route to aggregation endpoints, with optional JQL for samples.
   */
  analytical: (analysis) => {
    const routes: RetrieverRoute[] = []
    const secondary: RetrieverRoute[] = []
    const params = analysis.analyticalParams

    // Determine which analytical retrievers to use
    if (params?.aggregationType === 'trend') {
      routes.push({
        type: 'trends',
        priority: 1,
        required: true,
        params: {
          project_key: analysis.entities.projects[0] || null,
          days: 30,
          period_days: 7,
        },
      })
    } else if (params?.aggregationType === 'velocity') {
      routes.push({
        type: 'velocity',
        priority: 1,
        required: true,
        params: {
          project_key: analysis.entities.projects[0] || 'DS',
          weeks: 4,
        },
      })
    } else {
      // Default to aggregation for distribution/count queries
      for (const project of analysis.entities.projects.length > 0 ? analysis.entities.projects : ['DS']) {
        routes.push({
          type: 'aggregation',
          priority: 1,
          required: true,
          params: { project_key: project },
        })
      }
    }

    // Add JQL to fetch sample issues for context
    if (analysis.jqlQuery) {
      secondary.push({
        type: 'jql',
        priority: 2,
        required: false,
        params: { jql: analysis.jqlQuery, limit: 5 },  // Small sample
      })
    }

    return {
      primary: routes,
      secondary,
      parallelPrimary: true,
    }
  },

  /**
   * Exploratory queries - open-ended research.
   * Run semantic + JQL in parallel, then expand epics/links.
   */
  exploratory: (analysis) => {
    const primary: RetrieverRoute[] = []

    // Semantic search is always primary for exploratory
    primary.push({
      type: 'semantic',
      priority: 1,
      required: true,
      params: { query: analysis.semanticQuery, limit: 15 },
    })

    // Add JQL if we have structured constraints
    if (analysis.jqlQuery) {
      primary.push({
        type: 'jql',
        priority: 1,
        required: false,
        params: { jql: analysis.jqlQuery, limit: 20 },
      })
    }

    const secondary: RetrieverRoute[] = []

    // Epic expansion
    if (analysis.shouldExpandEpics) {
      secondary.push({
        type: 'epic-children',
        priority: 2,
        required: false,
        params: { limit: 3 },  // Max 3 epics
      })
    }

    // Link expansion
    if (analysis.shouldFetchLinks) {
      secondary.push({
        type: 'links',
        priority: 3,
        required: false,
        params: {},  // Will use first issue from results
      })
    }

    return {
      primary,
      secondary,
      parallelPrimary: true,
    }
  },

  /**
   * Complex queries - multi-faceted, need multiple strategies.
   * Run all relevant retrievers.
   */
  complex: (analysis) => {
    const primary: RetrieverRoute[] = []

    // Always include semantic
    primary.push({
      type: 'semantic',
      priority: 1,
      required: true,
      params: { query: analysis.semanticQuery, limit: 15 },
    })

    // Always include JQL if available
    if (analysis.jqlQuery) {
      primary.push({
        type: 'jql',
        priority: 1,
        required: false,
        params: { jql: analysis.jqlQuery, limit: 15 },
      })
    }

    // Add aggregation for context
    for (const project of analysis.entities.projects.slice(0, 2)) {
      primary.push({
        type: 'aggregation',
        priority: 2,
        required: false,
        params: { project_key: project },
      })
    }

    const secondary: RetrieverRoute[] = []

    // Epic expansion
    if (analysis.shouldExpandEpics) {
      secondary.push({
        type: 'epic-children',
        priority: 2,
        required: false,
        params: { limit: 2 },
      })
    }

    // Link expansion
    if (analysis.shouldFetchLinks) {
      secondary.push({
        type: 'links',
        priority: 3,
        required: false,
        params: {},
      })
    }

    return {
      primary,
      secondary,
      parallelPrimary: true,
    }
  },
}

/**
 * Route a query to the appropriate retrievers based on its analysis.
 *
 * @param analysis - The query analysis from the analyzer
 * @returns A route configuration with primary and secondary retrievers
 */
export function routeQuery(analysis: QueryAnalysis): QueryRoute {
  const intentRouter = INTENT_ROUTES[analysis.intent]
  const routes = intentRouter(analysis)

  return {
    analysis,
    ...routes,
  }
}

/**
 * Get a human-readable description of the route for logging.
 */
export function describeRoute(route: QueryRoute): string {
  const primary = route.primary.map(r => r.type).join(' + ')
  const secondary = route.secondary.map(r => r.type).join(' + ')

  return [
    `Intent: ${route.analysis.intent}`,
    `Primary: ${primary}`,
    secondary ? `Secondary: ${secondary}` : null,
    `Parallel: ${route.parallelPrimary}`,
  ].filter(Boolean).join(' | ')
}
