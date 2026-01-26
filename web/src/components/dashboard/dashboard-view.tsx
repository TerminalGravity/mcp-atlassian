"use client"

import { useEffect, useState, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  RefreshCw,
  AlertTriangle,
  Clock,
  Zap,
  ExternalLink,
  Play,
  Sparkles,
  TrendingUp,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Streamdown } from "streamdown"
import { cn } from "@/lib/utils"

interface JiraIssue {
  issue_id: string
  summary: string
  status: string
  issue_type: string
  assignee?: string | null
  updated?: string
  labels?: string[]
}

interface DashboardData {
  blockers: JiraIssue[]
  staleIssues: JiraIssue[]
  sprintIssues: JiraIssue[]
  stats: {
    total: number
    inProgress: number
    blocked: number
    stale: number
  }
}

interface AIWorkflow {
  id: string
  label: string
  description: string
  icon: typeof Sparkles
  prompt: string
}

const AI_WORKFLOWS: AIWorkflow[] = [
  {
    id: "priorities",
    label: "Prioritize My Day",
    description: "AI suggests what to work on based on urgency and dependencies",
    icon: TrendingUp,
    prompt: "Based on my current issues, what should I prioritize today? Consider blockers, deadlines, and dependencies.",
  },
  {
    id: "blockers",
    label: "Analyze Blockers",
    description: "Deep dive into what's blocking progress and suggested actions",
    icon: AlertTriangle,
    prompt: "Analyze the blockers affecting my work. What's causing them and what actions can I take to unblock?",
  },
  {
    id: "sprint-health",
    label: "Sprint Health Check",
    description: "Assessment of sprint progress and risk areas",
    icon: Zap,
    prompt: "Assess my current sprint health. Are we on track? What risks do you see?",
  },
]

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

interface DashboardViewProps {
  currentUser: string
}

export function DashboardView({ currentUser }: DashboardViewProps) {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeWorkflow, setActiveWorkflow] = useState<string | null>(null)
  const [workflowResult, setWorkflowResult] = useState<string>("")
  const [workflowLoading, setWorkflowLoading] = useState(false)

  const fetchDashboardData = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      // Fetch user's issues via JQL
      const response = await fetch(`/api/my-work?user=${encodeURIComponent(currentUser)}`)
      if (!response.ok) throw new Error(`Failed to fetch: ${response.status}`)

      const result = await response.json()
      const issues: JiraIssue[] = result.issues || []

      // Process into categories
      const now = new Date()
      const twoWeeksAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000)

      const blockers = issues.filter(
        (i) =>
          i.status?.toLowerCase().includes("block") ||
          i.labels?.some((l) => l.toLowerCase().includes("block")) ||
          i.issue_type?.toLowerCase() === "blocker"
      )

      const staleIssues = issues.filter((i) => {
        if (!i.updated) return false
        const updated = new Date(i.updated)
        return updated < twoWeeksAgo && !["done", "closed", "resolved"].includes(i.status?.toLowerCase())
      })

      const inProgressStatuses = ["in progress", "development in progress", "code review", "qa", "uat", "in review"]
      const sprintIssues = issues.filter((i) => inProgressStatuses.includes(i.status?.toLowerCase()))

      setData({
        blockers,
        staleIssues,
        sprintIssues,
        stats: {
          total: issues.length,
          inProgress: sprintIssues.length,
          blocked: blockers.length,
          stale: staleIssues.length,
        },
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard")
    } finally {
      setLoading(false)
    }
  }, [currentUser])

  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  const runWorkflow = async (workflow: AIWorkflow) => {
    setActiveWorkflow(workflow.id)
    setWorkflowResult("")
    setWorkflowLoading(true)

    try {
      const response = await fetch("/api/workflow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow: workflow.id,
          prompt: workflow.prompt,
          currentUser,
        }),
      })

      if (!response.ok) throw new Error(`Request failed: ${response.status}`)

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No response body")

      const decoder = new TextDecoder()
      let buffer = ""
      let collected = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        // Plain text stream - just accumulate the text
        const chunk = decoder.decode(value, { stream: true })
        collected += chunk
        setWorkflowResult(collected)
      }
    } catch (err) {
      setWorkflowResult(`Error: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setWorkflowLoading(false)
    }
  }

  const clearWorkflow = () => {
    setActiveWorkflow(null)
    setWorkflowResult("")
  }

  return (
    <div className="space-y-6">
      {/* Stats Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total Issues"
          value={loading ? "—" : data?.stats.total || 0}
          loading={loading}
        />
        <StatCard
          label="In Progress"
          value={loading ? "—" : data?.stats.inProgress || 0}
          color="text-blue-400"
          loading={loading}
        />
        <StatCard
          label="Blocked"
          value={loading ? "—" : data?.stats.blocked || 0}
          color="text-amber-400"
          loading={loading}
        />
        <StatCard
          label="Stale (14d+)"
          value={loading ? "—" : data?.stats.stale || 0}
          color="text-orange-400"
          loading={loading}
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Data Panels - Left 2 columns */}
        <div className="lg:col-span-2 space-y-4">
          {error ? (
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <div className="flex items-center gap-3">
                  <XCircle className="w-5 h-5 text-destructive" />
                  <div>
                    <p className="font-medium text-destructive">{error}</p>
                    <Button variant="outline" size="sm" onClick={fetchDashboardData} className="mt-2">
                      Retry
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Blockers */}
              <IssuePanel
                title="Blockers"
                icon={AlertTriangle}
                iconColor="text-amber-400"
                issues={data?.blockers || []}
                loading={loading}
                emptyMessage="No blockers found"
                accentColor="border-l-amber-500"
              />

              {/* Stale Issues */}
              <IssuePanel
                title="Stale Issues"
                icon={Clock}
                iconColor="text-orange-400"
                issues={data?.staleIssues || []}
                loading={loading}
                emptyMessage="No stale issues"
                accentColor="border-l-orange-500"
                subtitle="Not updated in 14+ days"
              />

              {/* In Progress */}
              <IssuePanel
                title="In Progress"
                icon={Zap}
                iconColor="text-blue-400"
                issues={data?.sprintIssues || []}
                loading={loading}
                emptyMessage="Nothing in progress"
                accentColor="border-l-blue-500"
              />
            </>
          )}
        </div>

        {/* AI Workflows Panel - Right column */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-violet-400" />
                  AI Workflows
                </CardTitle>
                {activeWorkflow && (
                  <Button variant="ghost" size="sm" onClick={clearWorkflow} className="h-6 px-2 text-xs">
                    Clear
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {AI_WORKFLOWS.map((workflow) => {
                const Icon = workflow.icon
                const isActive = activeWorkflow === workflow.id
                return (
                  <motion.button
                    key={workflow.id}
                    onClick={() => runWorkflow(workflow)}
                    disabled={workflowLoading}
                    className={cn(
                      "w-full text-left p-3 rounded-lg border transition-all",
                      "hover:bg-muted/50 hover:border-muted-foreground/20",
                      "disabled:opacity-50 disabled:cursor-not-allowed",
                      isActive && "bg-violet-500/10 border-violet-500/30"
                    )}
                    whileHover={{ scale: 1.01 }}
                    whileTap={{ scale: 0.99 }}
                  >
                    <div className="flex items-start gap-3">
                      <div
                        className={cn(
                          "w-8 h-8 rounded-md flex items-center justify-center shrink-0",
                          isActive ? "bg-violet-500/20 text-violet-400" : "bg-muted text-muted-foreground"
                        )}
                      >
                        {isActive && workflowLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Icon className="w-4 h-4" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium flex items-center gap-2">
                          {workflow.label}
                          {!isActive && <Play className="w-3 h-3 text-muted-foreground" />}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{workflow.description}</p>
                      </div>
                    </div>
                  </motion.button>
                )
              })}
            </CardContent>
          </Card>

          {/* Workflow Result */}
          <AnimatePresence>
            {(workflowResult || workflowLoading) && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <Card className="border-violet-500/20 bg-violet-500/5">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      {workflowLoading ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400" />
                          Analyzing...
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="w-3.5 h-3.5 text-violet-400" />
                          AI Analysis
                        </>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ScrollArea className="h-[300px]">
                      <div className="prose prose-sm dark:prose-invert max-w-none pr-4">
                        <Streamdown>{workflowResult || "Thinking..."}</Streamdown>
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Refresh Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchDashboardData}
            disabled={loading}
            className="w-full"
          >
            <RefreshCw className={cn("w-4 h-4 mr-2", loading && "animate-spin")} />
            Refresh Data
          </Button>
        </div>
      </div>
    </div>
  )
}

function StatCard({
  label,
  value,
  color,
  loading,
}: {
  label: string
  value: number | string
  color?: string
  loading?: boolean
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
        {loading ? (
          <Skeleton className="h-8 w-12 mt-1" />
        ) : (
          <p className={cn("text-2xl font-bold tabular-nums mt-1", color)}>{value}</p>
        )}
      </CardContent>
    </Card>
  )
}

function IssuePanel({
  title,
  subtitle,
  icon: Icon,
  iconColor,
  issues,
  loading,
  emptyMessage,
  accentColor,
}: {
  title: string
  subtitle?: string
  icon: typeof AlertTriangle
  iconColor: string
  issues: JiraIssue[]
  loading: boolean
  emptyMessage: string
  accentColor: string
}) {
  return (
    <Card className={cn("border-l-2", accentColor)}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Icon className={cn("w-4 h-4", iconColor)} />
            {title}
            {!loading && <Badge variant="secondary" className="ml-1 text-[10px]">{issues.length}</Badge>}
          </CardTitle>
          {subtitle && <span className="text-xs text-muted-foreground">{subtitle}</span>}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3 p-2">
                <Skeleton className="h-4 w-14" />
                <Skeleton className="h-4 flex-1" />
              </div>
            ))}
          </div>
        ) : issues.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">{emptyMessage}</p>
        ) : (
          <ScrollArea className={issues.length > 5 ? "h-[200px]" : ""}>
            <div className="space-y-1">
              {issues.map((issue, index) => (
                <motion.a
                  key={issue.issue_id}
                  href={`https://alldigitalrewards.atlassian.net/browse/${issue.issue_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  initial={{ opacity: 0, x: -5 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.02 }}
                  className="flex items-center gap-3 p-2 rounded-md hover:bg-muted/50 transition-colors group"
                >
                  <Badge variant="outline" className="font-mono text-[10px] shrink-0">
                    {issue.issue_id}
                  </Badge>
                  <span className="text-sm truncate flex-1 text-muted-foreground group-hover:text-foreground">
                    {issue.summary}
                  </span>
                  <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </motion.a>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}
