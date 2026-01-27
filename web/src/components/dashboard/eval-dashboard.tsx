"use client"

import { useEffect, useState, useCallback } from "react"
import { motion } from "framer-motion"
import {
  RefreshCw,
  Play,
  CheckCircle2,
  XCircle,
  Loader2,
  Target,
  FileSearch,
  Quote,
  Wrench,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertCircle,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

interface MetricsData {
  total_evaluations: number
  evaluations_with_scores: number
  average_scores: {
    tool_selection_accuracy: number | null
    retrieval_precision: number | null
    retrieval_recall: number | null
    faithfulness: number | null
    citation_accuracy: number | null
  }
  score_trends: {
    faithfulness: Array<{ date: string; value: number }>
    citation_accuracy: Array<{ date: string; value: number }>
  }
  date_range: {
    start: string | null
    end: string | null
  }
}

interface PendingTurn {
  id: string
  query: string
  timestamp: string
  tool_calls: number
  issues_retrieved: number
}

interface RunStatus {
  run_id: string
  status: string
  total: number
  completed: number
  average_scores: Record<string, number | null>
  errors: string[]
}

export function EvalDashboard() {
  const [metrics, setMetrics] = useState<MetricsData | null>(null)
  const [pending, setPending] = useState<PendingTurn[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningEval, setRunningEval] = useState(false)
  const [lastRun, setLastRun] = useState<RunStatus | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const [metricsRes, pendingRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/eval/metrics?days=30`),
        fetch(`${BACKEND_URL}/api/eval/pending?limit=10`),
      ])

      if (!metricsRes.ok) throw new Error(`Metrics fetch failed: ${metricsRes.status}`)
      if (!pendingRes.ok) throw new Error(`Pending fetch failed: ${pendingRes.status}`)

      const metricsData = await metricsRes.json()
      const pendingData = await pendingRes.json()

      setMetrics(metricsData)
      setPending(pendingData.turns || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const startEvalRun = async (sampleSize: number = 10) => {
    setRunningEval(true)
    setLastRun(null)

    try {
      const response = await fetch(`${BACKEND_URL}/api/eval/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sample_size: sampleSize,
          fetch_issue_data: false,
          use_deepeval: true,
          use_ragas: false, // Start with simplified metrics
        }),
      })

      if (!response.ok) throw new Error(`Run failed: ${response.status}`)

      const result = await response.json()

      if (result.status === "skipped") {
        setLastRun({ ...result, run_id: "", total: 0, completed: 0, average_scores: {}, errors: [] })
        return
      }

      // Poll for status
      const runId = result.run_id
      let attempts = 0
      const maxAttempts = 60 // 5 minutes max

      const pollStatus = async () => {
        const statusRes = await fetch(`${BACKEND_URL}/api/eval/runs/${runId}`)
        if (!statusRes.ok) return

        const status: RunStatus = await statusRes.json()
        setLastRun(status)

        if (status.status === "completed" || status.status === "failed" || attempts >= maxAttempts) {
          setRunningEval(false)
          fetchData() // Refresh metrics
        } else {
          attempts++
          setTimeout(pollStatus, 5000)
        }
      }

      pollStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed")
      setRunningEval(false)
    }
  }

  const formatScore = (score: number | null): string => {
    if (score === null || score === undefined) return "—"
    return `${(score * 100).toFixed(1)}%`
  }

  const getScoreColor = (score: number | null): string => {
    if (score === null) return "text-muted-foreground"
    if (score >= 0.8) return "text-green-400"
    if (score >= 0.6) return "text-yellow-400"
    return "text-red-400"
  }

  const getScoreTrend = (current: number | null, _trends: Array<{ date: string; value: number }>) => {
    if (current === null || !_trends || _trends.length < 2) return null
    const previous = _trends[_trends.length - 2]?.value
    if (previous === undefined) return null

    const diff = current - previous
    if (Math.abs(diff) < 0.01) return { direction: "stable" as const, value: 0 }
    return { direction: diff > 0 ? "up" as const : "down" as const, value: Math.abs(diff) * 100 }
  }

  return (
    <div className="space-y-6">
      {/* Score Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <ScoreCard
          label="Tool Selection"
          icon={Wrench}
          score={metrics?.average_scores.tool_selection_accuracy ?? null}
          loading={loading}
          trend={getScoreTrend(metrics?.average_scores.tool_selection_accuracy ?? null, [])}
        />
        <ScoreCard
          label="Retrieval Precision"
          icon={Target}
          score={metrics?.average_scores.retrieval_precision ?? null}
          loading={loading}
        />
        <ScoreCard
          label="Retrieval Recall"
          icon={FileSearch}
          score={metrics?.average_scores.retrieval_recall ?? null}
          loading={loading}
        />
        <ScoreCard
          label="Faithfulness"
          icon={CheckCircle2}
          score={metrics?.average_scores.faithfulness ?? null}
          loading={loading}
          trend={getScoreTrend(
            metrics?.average_scores.faithfulness ?? null,
            metrics?.score_trends.faithfulness || []
          )}
        />
        <ScoreCard
          label="Citation Accuracy"
          icon={Quote}
          score={metrics?.average_scores.citation_accuracy ?? null}
          loading={loading}
          trend={getScoreTrend(
            metrics?.average_scores.citation_accuracy ?? null,
            metrics?.score_trends.citation_accuracy || []
          )}
        />
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Stats & Controls */}
        <div className="lg:col-span-2 space-y-4">
          {error ? (
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <XCircle className="w-5 h-5 text-destructive" />
                  <div>
                    <p className="font-medium text-destructive">{error}</p>
                    <Button variant="outline" size="sm" onClick={fetchData} className="mt-2">
                      Retry
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Overview Stats */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium">Evaluation Overview</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground">Total Logged</p>
                      {loading ? (
                        <Skeleton className="h-8 w-16 mt-1" />
                      ) : (
                        <p className="text-2xl font-bold tabular-nums">
                          {metrics?.total_evaluations || 0}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Scored</p>
                      {loading ? (
                        <Skeleton className="h-8 w-16 mt-1" />
                      ) : (
                        <p className="text-2xl font-bold tabular-nums text-green-400">
                          {metrics?.evaluations_with_scores || 0}
                        </p>
                      )}
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Pending</p>
                      {loading ? (
                        <Skeleton className="h-8 w-16 mt-1" />
                      ) : (
                        <p className="text-2xl font-bold tabular-nums text-amber-400">
                          {pending.length}
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Pending Evaluations */}
              <Card className="border-l-2 border-l-amber-500">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-amber-400" />
                      Pending Evaluations
                      <Badge variant="secondary" className="ml-1 text-[10px]">
                        {pending.length}
                      </Badge>
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  {loading ? (
                    <div className="space-y-2">
                      {[1, 2, 3].map((i) => (
                        <div key={i} className="flex items-center gap-3 p-2">
                          <Skeleton className="h-4 w-20" />
                          <Skeleton className="h-4 flex-1" />
                        </div>
                      ))}
                    </div>
                  ) : pending.length === 0 ? (
                    <p className="text-sm text-muted-foreground py-4 text-center">
                      All turns have been evaluated
                    </p>
                  ) : (
                    <ScrollArea className={pending.length > 5 ? "h-[200px]" : ""}>
                      <div className="space-y-1">
                        {pending.map((turn, index) => (
                          <motion.div
                            key={turn.id}
                            initial={{ opacity: 0, x: -5 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: index * 0.02 }}
                            className="flex items-center gap-3 p-2 rounded-md hover:bg-muted/50 transition-colors"
                          >
                            <Badge variant="outline" className="font-mono text-[10px] shrink-0">
                              {turn.tool_calls} tools
                            </Badge>
                            <span className="text-sm truncate flex-1 text-muted-foreground">
                              {turn.query}
                            </span>
                            <span className="text-[10px] text-muted-foreground shrink-0">
                              {turn.issues_retrieved} issues
                            </span>
                          </motion.div>
                        ))}
                      </div>
                    </ScrollArea>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Run Controls */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Play className="w-4 h-4 text-blue-400" />
                Run Evaluation
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Score pending chat turns using configured metrics.
              </p>

              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => startEvalRun(10)}
                  disabled={runningEval || pending.length === 0}
                  className="flex-1"
                >
                  {runningEval ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Running...
                    </>
                  ) : (
                    "Run 10"
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => startEvalRun(50)}
                  disabled={runningEval || pending.length === 0}
                >
                  50
                </Button>
              </div>

              {lastRun && (
                <div className="p-3 rounded-lg bg-muted/50 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Status:</span>
                    <Badge
                      variant={lastRun.status === "completed" ? "default" : "secondary"}
                      className="text-[10px]"
                    >
                      {lastRun.status}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Progress:</span>
                    <span>{lastRun.completed}/{lastRun.total}</span>
                  </div>
                  {lastRun.errors.length > 0 && (
                    <div className="text-red-400 mt-2">
                      {lastRun.errors.length} errors
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Refresh */}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            className="w-full"
          >
            <RefreshCw className={cn("w-4 h-4 mr-2", loading && "animate-spin")} />
            Refresh Data
          </Button>

          {/* CLI Instructions */}
          <Card className="bg-muted/30">
            <CardContent className="pt-4">
              <p className="text-xs text-muted-foreground mb-2">Run from CLI:</p>
              <code className="text-[10px] bg-black/20 p-2 rounded block overflow-x-auto">
                uv run python -m mcp_atlassian.eval.cli run --sample 10
              </code>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function ScoreCard({
  label,
  icon: Icon,
  score,
  loading,
  trend,
}: {
  label: string
  icon: typeof Target
  score: number | null
  loading?: boolean
  trend?: { direction: "up" | "down" | "stable"; value: number } | null
}) {
  const formatScore = (s: number | null): string => {
    if (s === null || s === undefined) return "—"
    return `${(s * 100).toFixed(0)}%`
  }

  const getScoreColor = (s: number | null): string => {
    if (s === null) return "text-muted-foreground"
    if (s >= 0.8) return "text-green-400"
    if (s >= 0.6) return "text-yellow-400"
    return "text-red-400"
  }

  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center gap-2 mb-1">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">
            {label}
          </p>
        </div>
        {loading ? (
          <Skeleton className="h-7 w-12 mt-1" />
        ) : (
          <div className="flex items-center gap-2">
            <p className={cn("text-xl font-bold tabular-nums", getScoreColor(score))}>
              {formatScore(score)}
            </p>
            {trend && trend.direction !== "stable" && (
              <span
                className={cn(
                  "text-[10px] flex items-center",
                  trend.direction === "up" ? "text-green-400" : "text-red-400"
                )}
              >
                {trend.direction === "up" ? (
                  <TrendingUp className="w-3 h-3" />
                ) : (
                  <TrendingDown className="w-3 h-3" />
                )}
                {trend.value.toFixed(1)}
              </span>
            )}
            {trend && trend.direction === "stable" && (
              <Minus className="w-3 h-3 text-muted-foreground" />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
