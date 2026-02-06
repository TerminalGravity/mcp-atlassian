"use client"

import { useState, useCallback, useEffect, useMemo } from "react"
import {
  Activity,
  Database,
  RefreshCw,
  Settings,
  CheckCircle2,
  XCircle,
  Loader2,
  Zap,
  HardDrive,
  CircleDot,
  MessageSquare,
  FolderKanban,
  Search,
  Trash2,
  Calendar,
  StopCircle,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchSystemHealth,
  fetchAdminConfig,
  fetchJiraProjects,
  testJiraConnection,
  triggerFullSync,
  triggerIncrementalSync,
  compactDatabase,
  fetchSyncStatus,
  previewSync,
  clearProjects,
  cancelSync,
  type SystemHealth,
  type AdminConfig,
  type JiraProject,
  type ConnectionTest,
  type SyncPreview,
  type SyncOptions,
} from "@/lib/api"

// ---------------------------------------------------------------------------
// Chart colors (using CSS chart vars via oklch)
// ---------------------------------------------------------------------------

const CHART_COLORS = [
  "oklch(0.646 0.222 41.116)",   // chart-1 warm orange
  "oklch(0.6 0.118 184.704)",    // chart-2 teal
  "oklch(0.398 0.07 227.392)",   // chart-3 steel
  "oklch(0.828 0.189 84.429)",   // chart-4 gold
  "oklch(0.769 0.188 70.08)",    // chart-5 amber
  "oklch(0.55 0.15 280)",        // purple
  "oklch(0.65 0.18 150)",        // green
  "oklch(0.5 0.12 20)",          // brown
]

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  if (hours < 24) return `${hours}h ${mins}m`
  const days = Math.floor(hours / 24)
  return `${days}d ${hours % 24}h`
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${minutes}m ${secs}s`
}

function formatNumber(n: number): string {
  return n.toLocaleString()
}

// ---------------------------------------------------------------------------
// Visual Components
// ---------------------------------------------------------------------------

/** SVG circular progress ring */
function ProgressRing({
  value,
  max,
  size = 80,
  strokeWidth = 6,
  color = "var(--primary)",
  label,
  sublabel,
}: {
  value: number
  max: number
  size?: number
  strokeWidth?: number
  color?: string
  label: string
  sublabel?: string
}) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const pct = max > 0 ? Math.min(value / max, 1) : 0
  const offset = circumference * (1 - pct)

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: "stroke-dashoffset 0.8s ease-out",
          }}
        />
      </svg>
      <div className="text-center -mt-[calc(var(--size)/2+12px)]" style={{ "--size": `${size}px` } as React.CSSProperties}>
        <div className="font-semibold text-lg tabular-nums" style={{ lineHeight: `${size}px` }}>
          {formatNumber(value)}
        </div>
      </div>
      <span className="text-xs font-medium mt-1">{label}</span>
      {sublabel && (
        <span className="text-[10px] text-muted-foreground">{sublabel}</span>
      )}
    </div>
  )
}

/** Horizontal bar chart for project distribution */
function ProjectDistribution({
  counts,
  total,
}: {
  counts: Record<string, number>
  total: number
}) {
  const sorted = useMemo(
    () =>
      Object.entries(counts)
        .sort(([, a], [, b]) => b - a),
    [counts]
  )

  if (sorted.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-2">No project data</p>
    )
  }

  const maxCount = sorted[0]?.[1] ?? 1

  return (
    <div className="space-y-1.5">
      {sorted.map(([key, count], i) => {
        const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
        const color = CHART_COLORS[i % CHART_COLORS.length]
        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-8 font-mono font-medium text-right shrink-0">
              {key}
            </span>
            <div className="flex-1 h-5 bg-muted/50 rounded overflow-hidden relative">
              <div
                className="h-full rounded transition-all duration-700 ease-out"
                style={{
                  width: `${pct}%`,
                  backgroundColor: color,
                  minWidth: count > 0 ? "4px" : "0px",
                }}
              />
            </div>
            <span className="w-12 text-right tabular-nums text-muted-foreground shrink-0">
              {formatNumber(count)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** Pulsing status dot */
function StatusDot({ active, color }: { active: boolean; color: "green" | "red" | "yellow" }) {
  const colors = {
    green: "bg-emerald-500",
    red: "bg-red-500",
    yellow: "bg-amber-500",
  }
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {active && (
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${colors[color]}`}
        />
      )}
      <span
        className={`relative inline-flex rounded-full h-2.5 w-2.5 ${colors[color]}`}
      />
    </span>
  )
}

/** Sync progress bar with animated stripes during sync */
function SyncProgressBar({ running }: { running: boolean }) {
  return (
    <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
      {running ? (
        <div
          className="h-full rounded-full"
          style={{
            background:
              "repeating-linear-gradient(-45deg, var(--primary), var(--primary) 4px, transparent 4px, transparent 8px)",
            backgroundSize: "200% 100%",
            animation: "stripe-slide 1s linear infinite",
            width: "100%",
          }}
        />
      ) : (
        <div className="h-full bg-primary/20 rounded-full w-full" />
      )}
    </div>
  )
}

/** Stat card with big number */
function StatCard({
  icon: Icon,
  label,
  value,
  sublabel,
  accent,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string | number
  sublabel?: string
  accent?: boolean
}) {
  return (
    <div className={`rounded-lg border p-4 ${accent ? "bg-primary/[0.03]" : "bg-card"}`}>
      <div className="flex items-center gap-2 text-muted-foreground mb-2">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <div className="text-2xl font-bold tabular-nums tracking-tight">
        {typeof value === "number" ? formatNumber(value) : value}
      </div>
      {sublabel && (
        <div className="text-[11px] text-muted-foreground mt-1">{sublabel}</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skeleton helpers
// ---------------------------------------------------------------------------

function SkeletonCard() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <Skeleton className="h-5 w-32" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Key-Value Row
// ---------------------------------------------------------------------------

function KVRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SystemHealthTab
// ---------------------------------------------------------------------------

function SystemHealthTab() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connectionResult, setConnectionResult] =
    useState<ConnectionTest | null>(null)
  const [testingConnection, setTestingConnection] = useState(false)

  const loadHealth = useCallback(async () => {
    try {
      const data = await fetchSystemHealth()
      setHealth(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health data")
    }
  }, [])

  useEffect(() => {
    loadHealth()
    const interval = setInterval(loadHealth, 10_000)
    return () => clearInterval(interval)
  }, [loadHealth])

  const handleTestConnection = useCallback(async () => {
    setTestingConnection(true)
    setConnectionResult(null)
    try {
      const result = await testJiraConnection()
      setConnectionResult(result)
    } catch (err) {
      setConnectionResult({
        connected: false,
        message: err instanceof Error ? err.message : "Connection test failed",
        projects_count: null,
      })
    } finally {
      setTestingConnection(false)
    }
  }, [])

  if (error && !health) {
    return <p className="text-sm text-destructive py-4">{error}</p>
  }

  if (!health) {
    return (
      <div className="space-y-4 pt-4">
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    )
  }

  const totalIndexed = health.vector_store.total_issues + health.vector_store.total_comments
  const projectCount = health.vector_store.projects.length

  return (
    <div className="space-y-4 pt-4">
      {/* CSS for stripe animation */}
      <style>{`
        @keyframes stripe-slide {
          0% { background-position: 0 0; }
          100% { background-position: 16px 0; }
        }
      `}</style>

      {/* Top stat cards */}
      <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard
          icon={Activity}
          label="Server Status"
          value={health.server.status === "healthy" ? "Healthy" : "Unhealthy"}
          sublabel={`Uptime: ${formatUptime(health.server.uptime_seconds)}`}
          accent={health.server.status === "healthy"}
        />
        <StatCard
          icon={CircleDot}
          label="Indexed Issues"
          value={health.vector_store.total_issues}
          sublabel={`${projectCount} project${projectCount !== 1 ? "s" : ""}`}
        />
        <StatCard
          icon={MessageSquare}
          label="Indexed Comments"
          value={health.vector_store.total_comments}
          sublabel={`${totalIndexed.toLocaleString()} total records`}
        />
        <StatCard
          icon={RefreshCw}
          label="Sync Runs"
          value={health.sync.sync_count}
          sublabel={
            health.sync.last_sync
              ? `Last: ${formatRelativeTime(health.sync.last_sync)}`
              : "Never synced"
          }
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Index Distribution */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <FolderKanban className="h-4 w-4" />
              Index Distribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ProjectDistribution
              counts={health.vector_store.project_counts}
              total={health.vector_store.total_issues}
            />
          </CardContent>
        </Card>

        {/* Connection & Sync Status */}
        <div className="space-y-4">
          {/* Jira Connection */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <StatusDot active={false} color={health.jira.connected ? "green" : "red"} />
                Jira Connection
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <KVRow label="Status">
                <Badge variant={health.jira.connected ? "default" : "destructive"}>
                  {health.jira.connected ? "Connected" : "Disconnected"}
                </Badge>
              </KVRow>
              {health.jira.url && (
                <KVRow label="URL">
                  <span className="font-mono text-xs truncate max-w-[200px] inline-block">
                    {health.jira.url}
                  </span>
                </KVRow>
              )}
              {health.jira.user && (
                <KVRow label="User">
                  <span className="text-xs truncate max-w-[200px] inline-block">
                    {health.jira.user}
                  </span>
                </KVRow>
              )}
              <div className="pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleTestConnection}
                  disabled={testingConnection}
                  className="w-full"
                >
                  {testingConnection ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Test Connection
                </Button>
              </div>
              {connectionResult && (
                <div
                  className={`text-xs flex items-start gap-1.5 pt-1 ${
                    connectionResult.connected
                      ? "text-green-600 dark:text-green-400"
                      : "text-destructive"
                  }`}
                >
                  {connectionResult.connected ? (
                    <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  )}
                  <span>{connectionResult.message}</span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Sync Status */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <StatusDot active={health.sync.running} color={health.sync.running ? "yellow" : "green"} />
                Sync Status
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <SyncProgressBar running={health.sync.running} />
              <KVRow label="Auto-Sync">
                <Badge variant={health.sync.enabled ? "default" : "secondary"}>
                  {health.sync.enabled ? "Enabled" : "Disabled"}
                </Badge>
              </KVRow>
              <KVRow label="Interval">{health.sync.interval_minutes}m</KVRow>
              {health.sync.error_count > 0 && (
                <KVRow label="Errors">
                  <span className="text-destructive font-medium">
                    {health.sync.error_count}
                  </span>
                </KVRow>
              )}
              {health.sync.last_result && (
                <div className="pt-2 border-t space-y-1.5">
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                    Last Run
                  </p>
                  <SyncResultBar result={health.sync.last_result} />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

/** Visual breakdown of last sync result */
function SyncResultBar({
  result,
}: {
  result: NonNullable<SystemHealth["sync"]["last_result"]>
}) {
  const total =
    result.issues_processed > 0
      ? result.issues_processed
      : result.issues_embedded + result.issues_skipped + result.errors

  if (total === 0) {
    return (
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>No issues processed</span>
        <span>{formatDuration(result.duration_seconds)}</span>
      </div>
    )
  }

  const segments = [
    { label: "Embedded", count: result.issues_embedded, color: "bg-emerald-500" },
    { label: "Skipped", count: result.issues_skipped, color: "bg-amber-400" },
    { label: "Errors", count: result.errors, color: "bg-red-500" },
  ].filter((s) => s.count > 0)

  return (
    <div className="space-y-1.5">
      {/* Stacked bar */}
      <div className="flex h-3 rounded-full overflow-hidden bg-muted/50">
        {segments.map((seg) => (
          <div
            key={seg.label}
            className={`${seg.color} transition-all duration-500`}
            style={{ width: `${(seg.count / total) * 100}%`, minWidth: seg.count > 0 ? "3px" : 0 }}
          />
        ))}
      </div>
      {/* Legend */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
        {segments.map((seg) => (
          <span key={seg.label} className="flex items-center gap-1">
            <span className={`inline-block h-2 w-2 rounded-full ${seg.color}`} />
            {seg.label}: {seg.count}
          </span>
        ))}
        <span className="ml-auto tabular-nums">{formatDuration(result.duration_seconds)}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SyncManagementTab
// ---------------------------------------------------------------------------

function SyncManagementTab() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [syncRunning, setSyncRunning] = useState(false)
  const [projects, setProjects] = useState<JiraProject[]>([])
  const [selectedProjects, setSelectedProjects] = useState<Set<string>>(
    new Set()
  )
  const [error, setError] = useState<string | null>(null)
  const [compactResult, setCompactResult] = useState<string | null>(null)
  const [compacting, setCompacting] = useState(false)
  const [syncElapsed, setSyncElapsed] = useState(0)

  // Date range state
  const defaultStartDate = useMemo(() => {
    const d = new Date()
    d.setFullYear(d.getFullYear() - 1)
    return d.toISOString().split("T")[0]
  }, [])
  const defaultEndDate = useMemo(() => new Date().toISOString().split("T")[0], [])
  const [startDate, setStartDate] = useState(defaultStartDate)
  const [endDate, setEndDate] = useState(defaultEndDate)

  // Sync options
  const [syncComments, setSyncComments] = useState(true)

  // Preview state
  const [preview, setPreview] = useState<SyncPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)

  // Clear state
  const [clearing, setClearing] = useState(false)
  const [clearResult, setClearResult] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [healthData, projectData] = await Promise.all([
        fetchSystemHealth(),
        fetchJiraProjects().catch(() => [] as JiraProject[]),
      ])
      setHealth(healthData)
      setProjects(projectData)
      setSyncRunning(healthData.sync.running)
      setError(null)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load sync data"
      )
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Poll while sync is running — fast polling for responsive UI
  useEffect(() => {
    if (!syncRunning) return
    const interval = setInterval(async () => {
      try {
        const [status, healthData] = await Promise.all([
          fetchSyncStatus(),
          fetchSystemHealth(),
        ])
        setHealth(healthData)
        setSyncRunning(status.running)
        if (!status.running) {
          loadData()
          setSyncElapsed(0)
        }
      } catch {
        // Ignore polling errors
      }
    }, 2_000)
    return () => clearInterval(interval)
  }, [syncRunning, loadData])

  // Elapsed timer while syncing
  useEffect(() => {
    if (!syncRunning) return
    setSyncElapsed(0)
    const t = setInterval(() => setSyncElapsed((e) => e + 1), 1_000)
    return () => clearInterval(t)
  }, [syncRunning])

  // Reset preview when selection or dates change
  useEffect(() => {
    setPreview(null)
  }, [selectedProjects, startDate, endDate])

  const handlePreview = useCallback(async () => {
    const projectKeys =
      selectedProjects.size > 0
        ? Array.from(selectedProjects)
        : projects.map((p) => p.key)
    if (projectKeys.length === 0) return
    setPreviewing(true)
    setPreview(null)
    try {
      const result = await previewSync(projectKeys, startDate, endDate)
      setPreview(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed")
    } finally {
      setPreviewing(false)
    }
  }, [selectedProjects, projects, startDate, endDate])

  const handleIncremental = useCallback(async () => {
    setSyncRunning(true)
    try {
      await triggerIncrementalSync()
      await loadData()
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Incremental sync failed"
      )
    } finally {
      setSyncRunning(false)
    }
  }, [loadData])

  const handleFullSync = useCallback(async () => {
    setSyncRunning(true)
    setError(null)
    try {
      const projectKeys =
        selectedProjects.size > 0
          ? Array.from(selectedProjects)
          : undefined
      await triggerFullSync(projectKeys, startDate, endDate, {
        syncComments,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Full sync failed")
      setSyncRunning(false)
    }
  }, [selectedProjects, startDate, endDate, syncComments])

  const handleCompact = useCallback(async () => {
    setCompacting(true)
    setCompactResult(null)
    try {
      const result = await compactDatabase()
      setCompactResult(
        result.success ? result.message : `Error: ${result.message}`
      )
    } catch (err) {
      setCompactResult(
        err instanceof Error ? err.message : "Compact failed"
      )
    } finally {
      setCompacting(false)
    }
  }, [])

  const handleClear = useCallback(async () => {
    if (selectedProjects.size === 0) return
    setClearing(true)
    setClearResult(null)
    try {
      const result = await clearProjects(Array.from(selectedProjects))
      const details = Object.entries(result.cleared)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ")
      setClearResult(`Cleared ${result.total} issues (${details})`)

      // Optimistic update: immediately zero out cleared projects in health state
      setHealth((prev) => {
        if (!prev) return prev
        const updatedCounts = { ...prev.vector_store.project_counts }
        let removedTotal = 0
        for (const key of selectedProjects) {
          removedTotal += updatedCounts[key] ?? 0
          delete updatedCounts[key]
        }
        return {
          ...prev,
          vector_store: {
            ...prev.vector_store,
            total_issues: Math.max(0, prev.vector_store.total_issues - removedTotal),
            project_counts: updatedCounts,
            projects: prev.vector_store.projects.filter((p) => !selectedProjects.has(p)),
          },
        }
      })

      // Also refresh from server for accuracy
      loadData()
    } catch (err) {
      setClearResult(
        err instanceof Error ? err.message : "Clear failed"
      )
    } finally {
      setClearing(false)
    }
  }, [selectedProjects, loadData])

  const handleCancel = useCallback(async () => {
    try {
      await cancelSync()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed")
    }
  }, [])

  const toggleProject = useCallback((key: string) => {
    setSelectedProjects((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  const selectAllProjects = useCallback(() => {
    setSelectedProjects(new Set(projects.map((p) => p.key)))
  }, [projects])

  const clearSelection = useCallback(() => {
    setSelectedProjects(new Set())
  }, [])

  // Compute total indexed issues for selected projects (for clear button text)
  const selectedIndexedCount = useMemo(() => {
    if (!health) return 0
    return Array.from(selectedProjects).reduce(
      (sum, key) => sum + (health.vector_store.project_counts[key] ?? 0),
      0
    )
  }, [selectedProjects, health])

  if (error && !health) {
    return <p className="text-sm text-destructive py-4">{error}</p>
  }

  if (!health) {
    return (
      <div className="grid gap-4 md:grid-cols-2 pt-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  return (
    <div className="space-y-4 pt-4">
      {/* CSS for stripe animation */}
      <style>{`
        @keyframes stripe-slide {
          0% { background-position: 0 0; }
          100% { background-position: 16px 0; }
        }
      `}</style>

      {/* Active sync banner */}
      {syncRunning && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20 p-4">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Loader2 className="h-5 w-5 animate-spin text-amber-600 dark:text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Sync in progress...</p>
              <p className="text-xs text-muted-foreground">
                Elapsed: {formatDuration(syncElapsed)}
              </p>
            </div>
            <div className="flex-1">
              <SyncProgressBar running />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCancel}
              className="shrink-0 border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40"
            >
              <StopCircle className="h-3.5 w-3.5 mr-1.5" />
              Stop
            </Button>
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {/* LEFT: Sync Configuration */}
        <div className="space-y-4">
          {/* Project Selector */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <FolderKanban className="h-4 w-4" />
                Projects
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {projects.length > 0 ? (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    {projects.map((p) => {
                      const count = health.vector_store.project_counts[p.key] ?? 0
                      return (
                        <button
                          key={p.key}
                          onClick={() => toggleProject(p.key)}
                          disabled={syncRunning}
                          className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-colors ${
                            selectedProjects.has(p.key)
                              ? "bg-primary text-primary-foreground border-primary"
                              : "bg-background text-foreground border-border hover:bg-accent"
                          } ${syncRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                        >
                          {p.key}
                          {count > 0 && (
                            <span className={`ml-1 text-[10px] ${
                              selectedProjects.has(p.key) ? "opacity-75" : "text-muted-foreground"
                            }`}>
                              ({formatNumber(count)})
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={selectAllProjects}
                      disabled={syncRunning}
                      className="text-[11px] text-primary hover:underline disabled:opacity-50"
                    >
                      Select All
                    </button>
                    <span className="text-muted-foreground text-[10px]">/</span>
                    <button
                      onClick={clearSelection}
                      disabled={syncRunning}
                      className="text-[11px] text-primary hover:underline disabled:opacity-50"
                    >
                      Clear
                    </button>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {selectedProjects.size === 0
                        ? "All projects"
                        : `${selectedProjects.size} selected`}
                    </span>
                  </div>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  No projects loaded
                </p>
              )}
            </CardContent>
          </Card>

          {/* Date Range */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Calendar className="h-4 w-4" />
                Date Range
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Issues updated between
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground">Start</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    disabled={syncRunning}
                    className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground">End</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    disabled={syncRunning}
                    className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs tabular-nums focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Sync Options */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Settings className="h-4 w-4" />
                Options
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <label className="flex items-center justify-between cursor-pointer">
                <div>
                  <span className="text-sm font-medium">Sync Comments</span>
                  <p className="text-[11px] text-muted-foreground">
                    Index issue comments for semantic search
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={syncComments}
                  disabled={syncRunning}
                  onClick={() => setSyncComments((v) => !v)}
                  className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    syncComments ? "bg-primary" : "bg-muted"
                  } ${syncRunning ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                >
                  <span
                    className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                      syncComments ? "translate-x-4" : "translate-x-0"
                    }`}
                  />
                </button>
              </label>
            </CardContent>
          </Card>

          {/* Preview + Actions */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Search className="h-4 w-4" />
                Preview & Sync
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button
                variant="outline"
                size="sm"
                onClick={handlePreview}
                disabled={syncRunning || previewing || projects.length === 0}
                className="w-full"
              >
                {previewing ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Search className="h-3.5 w-3.5 mr-1.5" />
                )}
                Preview Issue Counts
              </Button>

              {/* Preview results */}
              {preview && (
                <div className="space-y-2 rounded-md border bg-muted/30 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium">Preview Results</span>
                    <Badge variant="secondary" className="tabular-nums">
                      {formatNumber(preview.total)} total
                    </Badge>
                  </div>
                  <ProjectDistribution
                    counts={preview.counts}
                    total={preview.total}
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleFullSync}
                  disabled={syncRunning || !preview}
                  className="w-full"
                >
                  {syncRunning ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <Zap className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  {preview
                    ? `Sync ${formatNumber(preview.total)}`
                    : "Full Sync"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleIncremental}
                  disabled={syncRunning}
                  className="w-full"
                >
                  {syncRunning ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Incremental
                </Button>
              </div>

              {error && (
                <p className="text-xs text-destructive">{error}</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* RIGHT: Current Index */}
        <div className="space-y-4">
          {/* Project Distribution */}
          <Card className={`transition-opacity duration-300 ${clearing ? "opacity-50" : ""}`}>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <FolderKanban className="h-4 w-4" />
                Index Distribution
                {syncRunning && (
                  <span className="ml-auto flex items-center gap-1.5 text-[10px] font-normal text-amber-600 dark:text-amber-400">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Updating...
                  </span>
                )}
                {clearing && (
                  <span className="ml-auto flex items-center gap-1.5 text-[10px] font-normal text-destructive">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Clearing...
                  </span>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ProjectDistribution
                counts={health.vector_store.project_counts}
                total={health.vector_store.total_issues}
              />
            </CardContent>
          </Card>

          {/* Clear Controls */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Trash2 className="h-4 w-4" />
                Clear Index
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Remove indexed data for selected projects.
              </p>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleClear}
                disabled={clearing || selectedProjects.size === 0 || syncRunning}
                className="w-full"
              >
                {clearing ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                )}
                {selectedProjects.size > 0
                  ? `Clear ${formatNumber(selectedIndexedCount)} issues from ${selectedProjects.size} project${selectedProjects.size > 1 ? "s" : ""}`
                  : "Select projects to clear"}
              </Button>
              {clearResult && (
                <p
                  className={`text-xs ${
                    clearResult.startsWith("Clear")
                      ? "text-green-600 dark:text-green-400"
                      : "text-destructive"
                  }`}
                >
                  {clearResult}
                </p>
              )}
            </CardContent>
          </Card>

          {/* Database */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <HardDrive className="h-4 w-4" />
                Database
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <KVRow label="Path">
                <span className="font-mono text-xs truncate max-w-[200px] inline-block">
                  {health.vector_store.db_path}
                </span>
              </KVRow>
              <KVRow label="Total Records">
                <span className="tabular-nums flex items-center gap-1.5">
                  {formatNumber(
                    health.vector_store.total_issues +
                      health.vector_store.total_comments
                  )}
                  {syncRunning && (
                    <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                  )}
                </span>
              </KVRow>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCompact}
                disabled={compacting}
                className="w-full"
              >
                {compacting ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                ) : (
                  <Database className="h-3.5 w-3.5 mr-1.5" />
                )}
                Compact Database
              </Button>
              {compactResult && (
                <p
                  className={`text-xs ${
                    compactResult.startsWith("Error")
                      ? "text-destructive"
                      : "text-green-600 dark:text-green-400"
                  }`}
                >
                  {compactResult}
                </p>
              )}
            </CardContent>
          </Card>

          {/* Last Sync Result */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Activity className="h-4 w-4" />
                {syncRunning ? "Sync Progress" : "Last Sync Result"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {syncRunning ? (
                <div className="space-y-3">
                  <SyncProgressBar running />
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <StatusDot active color="yellow" />
                      Syncing...
                    </span>
                    <span className="tabular-nums">{formatDuration(syncElapsed)}</span>
                  </div>
                  {health.sync.last_result && (
                    <div className="pt-2 border-t">
                      <p className="text-[10px] text-muted-foreground mb-1.5">Live progress</p>
                      <SyncResultBar result={health.sync.last_result} />
                    </div>
                  )}
                </div>
              ) : health.sync.last_result ? (
                <SyncResultBar result={health.sync.last_result} />
              ) : (
                <p className="text-xs text-muted-foreground">
                  No sync has been run yet
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ConfigurationTab
// ---------------------------------------------------------------------------

function ConfigurationTab() {
  const [config, setConfig] = useState<AdminConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchAdminConfig()
      .then((data) => {
        setConfig(data)
        setError(null)
      })
      .catch((err) => {
        setError(
          err instanceof Error ? err.message : "Failed to load configuration"
        )
      })
  }, [])

  if (error) {
    return <p className="text-sm text-destructive py-4">{error}</p>
  }

  if (!config) {
    return (
      <div className="pt-4">
        <SkeletonCard />
      </div>
    )
  }

  return (
    <div className="pt-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Settings className="h-4 w-4" />
            Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Embedding */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Embedding
            </p>
            <KVRow label="Provider">
              <span className="font-mono text-sm">{config.embedding_provider}</span>
            </KVRow>
            <KVRow label="Model">
              <span className="font-mono text-sm">{config.embedding_model}</span>
            </KVRow>
            <KVRow label="Dimensions">{config.embedding_dimensions}</KVRow>
          </div>

          {/* Sync */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Sync
            </p>
            <KVRow label="Enabled">
              <Badge variant={config.sync_enabled ? "default" : "secondary"}>
                {config.sync_enabled ? "Yes" : "No"}
              </Badge>
            </KVRow>
            <KVRow label="Interval">
              {config.sync_interval_minutes}m
            </KVRow>
            <KVRow label="Projects">
              <span className="font-mono text-sm">
                {config.sync_projects.length > 0
                  ? config.sync_projects.join(", ")
                  : "All"}
              </span>
            </KVRow>
            <KVRow label="Comments">
              <Badge variant={config.sync_comments ? "default" : "secondary"}>
                {config.sync_comments ? "Yes" : "No"}
              </Badge>
            </KVRow>
          </div>

          {/* Performance */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Performance
            </p>
            <KVRow label="Batch Size">{config.batch_size}</KVRow>
            <KVRow label="Concurrent Embeddings">
              {config.max_concurrent_embeddings}
            </KVRow>
            <KVRow label="Cache">
              <Badge variant={config.cache_embeddings ? "default" : "secondary"}>
                {config.cache_embeddings ? "Yes" : "No"}
              </Badge>
            </KVRow>
          </div>

          {/* Search */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Search
            </p>
            <KVRow label="Min Score">{config.default_min_score}</KVRow>
            <KVRow label="Duplicate Threshold">
              {config.duplicate_threshold}
            </KVRow>
            <KVRow label="FTS Weight">{config.fts_weight}</KVRow>
          </div>

          {/* Database */}
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Database
            </p>
            <KVRow label="Path">
              <span className="font-mono text-sm">{config.db_path}</span>
            </KVRow>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SettingsPage (exported)
// ---------------------------------------------------------------------------

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState("health")

  return (
    <div className="space-y-4">
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="health">
            <Activity className="h-3.5 w-3.5 mr-1.5" />
            System Health
          </TabsTrigger>
          <TabsTrigger value="sync">
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Sync Management
          </TabsTrigger>
          <TabsTrigger value="config">
            <Settings className="h-3.5 w-3.5 mr-1.5" />
            Configuration
          </TabsTrigger>
        </TabsList>

        <TabsContent value="health">
          <SystemHealthTab />
        </TabsContent>
        <TabsContent value="sync">
          <SyncManagementTab />
        </TabsContent>
        <TabsContent value="config">
          <ConfigurationTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
