/**
 * API client for backend services.
 */

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

// -----------------------------------------------------------------------------
// Output Modes API
// -----------------------------------------------------------------------------

export interface QueryPatterns {
  keywords: string[]
  regex: string[]
  priority: number
}

export interface SystemPromptSections {
  formatting: string
  behavior?: string | null
  constraints?: string | null
}

export interface OutputMode {
  id: string
  name: string
  display_name: string
  description: string
  owner_id: string | null
  is_default: boolean
  query_patterns: QueryPatterns
  system_prompt_sections: SystemPromptSections
  created_at: string
  updated_at: string
}

export interface OutputModeCreate {
  name: string
  display_name: string
  description: string
  query_patterns: QueryPatterns
  system_prompt_sections: SystemPromptSections
  is_default?: boolean
}

export interface OutputModeUpdate {
  name?: string
  display_name?: string
  description?: string
  query_patterns?: QueryPatterns
  system_prompt_sections?: SystemPromptSections
  is_default?: boolean
}

export interface ClassifyQueryResponse {
  mode_id: string | null
  mode_name: string | null
  confidence: number
  matched_pattern: string | null
}

export interface UserPreferences {
  user_id: string
  default_output_mode_id: string | null
  auto_detect_mode: boolean
}

/**
 * Fetch all output modes (system defaults + user's custom modes).
 */
export async function fetchOutputModes(ownerId?: string): Promise<OutputMode[]> {
  const url = new URL(`${BACKEND_URL}/api/output-modes`)
  if (ownerId) {
    url.searchParams.set("owner_id", ownerId)
  }
  const response = await fetch(url.toString())
  if (!response.ok) {
    throw new Error(`Failed to fetch output modes: ${response.status}`)
  }
  return response.json()
}

/**
 * Fetch a single output mode by ID.
 */
export async function fetchOutputMode(modeId: string): Promise<OutputMode> {
  const response = await fetch(`${BACKEND_URL}/api/output-modes/${modeId}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch output mode: ${response.status}`)
  }
  return response.json()
}

/**
 * Create a new custom output mode.
 */
export async function createOutputMode(
  mode: OutputModeCreate,
  ownerId?: string
): Promise<OutputMode> {
  const url = new URL(`${BACKEND_URL}/api/output-modes`)
  if (ownerId) {
    url.searchParams.set("owner_id", ownerId)
  }
  const response = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mode),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `Failed to create output mode: ${response.status}`)
  }
  return response.json()
}

/**
 * Update an existing output mode.
 */
export async function updateOutputMode(
  modeId: string,
  mode: OutputModeUpdate,
  ownerId?: string
): Promise<OutputMode> {
  const url = new URL(`${BACKEND_URL}/api/output-modes/${modeId}`)
  if (ownerId) {
    url.searchParams.set("owner_id", ownerId)
  }
  const response = await fetch(url.toString(), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mode),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `Failed to update output mode: ${response.status}`)
  }
  return response.json()
}

/**
 * Delete an output mode (owner only, cannot delete system templates).
 */
export async function deleteOutputMode(modeId: string, ownerId?: string): Promise<void> {
  const url = new URL(`${BACKEND_URL}/api/output-modes/${modeId}`)
  if (ownerId) {
    url.searchParams.set("owner_id", ownerId)
  }
  const response = await fetch(url.toString(), { method: "DELETE" })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `Failed to delete output mode: ${response.status}`)
  }
}

/**
 * Clone an existing output mode.
 */
export async function cloneOutputMode(modeId: string, ownerId?: string): Promise<OutputMode> {
  const url = new URL(`${BACKEND_URL}/api/output-modes/${modeId}/clone`)
  if (ownerId) {
    url.searchParams.set("owner_id", ownerId)
  }
  const response = await fetch(url.toString(), { method: "POST" })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `Failed to clone output mode: ${response.status}`)
  }
  return response.json()
}

/**
 * Auto-detect the best output mode for a query.
 */
export async function classifyQuery(query: string): Promise<ClassifyQueryResponse> {
  const response = await fetch(`${BACKEND_URL}/api/output-modes/classify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  })
  if (!response.ok) {
    throw new Error(`Failed to classify query: ${response.status}`)
  }
  return response.json()
}

/**
 * Get user preferences for output modes.
 */
export async function fetchUserPreferences(userId: string): Promise<UserPreferences> {
  const response = await fetch(`${BACKEND_URL}/api/output-modes/user-preferences/${userId}`)
  if (!response.ok) {
    throw new Error(`Failed to fetch user preferences: ${response.status}`)
  }
  return response.json()
}

/**
 * Update user preferences for output modes.
 */
export async function updateUserPreferences(
  userId: string,
  prefs: Partial<UserPreferences>
): Promise<UserPreferences> {
  const response = await fetch(`${BACKEND_URL}/api/output-modes/user-preferences/${userId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  })
  if (!response.ok) {
    throw new Error(`Failed to update user preferences: ${response.status}`)
  }
  return response.json()
}

// -----------------------------------------------------------------------------
// Admin API
// -----------------------------------------------------------------------------

export interface SystemHealth {
  server: { status: string; uptime_seconds: number }
  jira: { connected: boolean; url: string | null; user: string | null }
  vector_store: {
    total_issues: number
    total_comments: number
    projects: string[]
    project_counts: Record<string, number>
    db_path: string
  }
  sync: SyncStatus
}

export interface SyncStatus {
  enabled: boolean
  running: boolean
  interval_minutes: number
  last_sync: string | null
  sync_count: number
  error_count: number
  last_result: SyncLastResult | null
}

export interface SyncLastResult {
  issues_processed: number
  issues_embedded: number
  issues_skipped: number
  errors: number
  duration_seconds: number
}

export interface AdminConfig {
  db_path: string
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: number
  sync_enabled: boolean
  sync_interval_minutes: number
  sync_projects: string[]
  sync_comments: boolean
  batch_size: number
  max_concurrent_embeddings: number
  cache_embeddings: boolean
  self_query_model: string
  max_response_tokens: number
  compact_responses: boolean
  fts_weight: number
  default_min_score: number
  duplicate_threshold: number
  similar_threshold: number
}

export interface JiraProject {
  key: string
  name: string
}

export interface ConnectionTest {
  connected: boolean
  message: string
  projects_count: number | null
}

export async function fetchSystemHealth(): Promise<SystemHealth> {
  const response = await fetch(`${BACKEND_URL}/api/admin/system`)
  if (!response.ok) {
    throw new Error(`Failed to fetch system health: ${response.status}`)
  }
  return response.json()
}

export async function fetchAdminConfig(): Promise<AdminConfig> {
  const response = await fetch(`${BACKEND_URL}/api/admin/config`)
  if (!response.ok) {
    throw new Error(`Failed to fetch config: ${response.status}`)
  }
  return response.json()
}

export async function fetchJiraProjects(): Promise<JiraProject[]> {
  const response = await fetch(`${BACKEND_URL}/api/admin/projects`)
  if (!response.ok) {
    throw new Error(`Failed to fetch projects: ${response.status}`)
  }
  const data = await response.json()
  return data.projects
}

export async function testJiraConnection(): Promise<ConnectionTest> {
  const response = await fetch(`${BACKEND_URL}/api/admin/jira/test`, {
    method: "POST",
  })
  if (!response.ok) {
    throw new Error(`Failed to test connection: ${response.status}`)
  }
  return response.json()
}

export interface SyncOptions {
  syncComments?: boolean
}

export async function triggerFullSync(
  projects?: string[],
  startDate?: string,
  endDate?: string,
  options?: SyncOptions,
): Promise<{ started: boolean }> {
  const response = await fetch(`${BACKEND_URL}/api/admin/sync/full`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      projects: projects ?? null,
      start_date: startDate ?? null,
      end_date: endDate ?? null,
      sync_comments: options?.syncComments ?? null,
    }),
  })
  if (!response.ok) {
    throw new Error(`Failed to trigger full sync: ${response.status}`)
  }
  return response.json()
}

export interface SyncPreview {
  counts: Record<string, number>
  total: number
}

export async function previewSync(
  projects: string[],
  startDate?: string,
  endDate?: string,
): Promise<SyncPreview> {
  const response = await fetch(`${BACKEND_URL}/api/admin/sync/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      projects,
      start_date: startDate ?? null,
      end_date: endDate ?? null,
    }),
  })
  if (!response.ok) {
    throw new Error(`Failed to preview sync: ${response.status}`)
  }
  return response.json()
}

export async function clearProjects(
  projects: string[],
): Promise<{ cleared: Record<string, number>; total: number }> {
  const response = await fetch(`${BACKEND_URL}/api/admin/sync/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ projects }),
  })
  if (!response.ok) {
    throw new Error(`Failed to clear projects: ${response.status}`)
  }
  return response.json()
}

export async function cancelSync(): Promise<{
  cancelled: boolean
  message: string
}> {
  const response = await fetch(`${BACKEND_URL}/api/admin/sync/cancel`, {
    method: "POST",
  })
  if (!response.ok) {
    throw new Error(`Failed to cancel sync: ${response.status}`)
  }
  return response.json()
}

export async function triggerIncrementalSync(): Promise<{
  success: boolean
  issues_processed: number
  issues_embedded: number
  duration_seconds: number
  errors: number
}> {
  const response = await fetch(`${BACKEND_URL}/api/sync/trigger`, {
    method: "POST",
  })
  if (!response.ok) {
    throw new Error(`Failed to trigger incremental sync: ${response.status}`)
  }
  return response.json()
}

export async function compactDatabase(): Promise<{
  success: boolean
  message: string
}> {
  const response = await fetch(`${BACKEND_URL}/api/admin/db/compact`, {
    method: "POST",
  })
  if (!response.ok) {
    throw new Error(`Failed to compact database: ${response.status}`)
  }
  return response.json()
}

export async function fetchSyncStatus(): Promise<SyncStatus> {
  const response = await fetch(`${BACKEND_URL}/api/sync/status`)
  if (!response.ok) {
    throw new Error(`Failed to fetch sync status: ${response.status}`)
  }
  return response.json()
}
