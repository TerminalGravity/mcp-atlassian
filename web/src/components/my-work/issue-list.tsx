"use client"

import { useEffect, useState, useCallback } from "react"
import { motion } from "framer-motion"
import { RefreshCw, ExternalLink, AlertCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
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

interface IssueListProps {
  currentUser: string
}

const TAB_FILTERS: Record<string, string[]> = {
  "in-progress": ["In Progress", "Development in Progress", "Code Review", "QA", "UAT", "In Review"],
  "to-do": ["Backlog", "To Do", "Selected for Development", "Open", "New"],
  "done": ["Done", "Closed", "Resolved", "Complete"],
}

const STATUS_COLORS: Record<string, string> = {
  "Done": "bg-green-500/10 text-green-500",
  "Closed": "bg-green-500/10 text-green-500",
  "Resolved": "bg-green-500/10 text-green-500",
  "In Progress": "bg-yellow-500/10 text-yellow-500",
  "Development in Progress": "bg-yellow-500/10 text-yellow-500",
  "Code Review": "bg-purple-500/10 text-purple-500",
  "QA": "bg-blue-500/10 text-blue-500",
  "Backlog": "bg-gray-500/10 text-gray-500",
  "To Do": "bg-gray-500/10 text-gray-500",
}

export function IssueList({ currentUser }: IssueListProps) {
  const [issues, setIssues] = useState<JiraIssue[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState("in-progress")

  const fetchIssues = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/my-work?user=${encodeURIComponent(currentUser)}`)
      if (!res.ok) {
        throw new Error(`Failed to fetch: ${res.status}`)
      }
      const data = await res.json()
      if (data.error) {
        throw new Error(data.error)
      }
      setIssues(data.issues || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load issues")
    } finally {
      setLoading(false)
    }
  }, [currentUser])

  useEffect(() => {
    fetchIssues()
  }, [fetchIssues])

  const getFilteredIssues = (tab: string) => {
    const statuses = TAB_FILTERS[tab] || []
    return issues.filter(issue => statuses.includes(issue.status))
  }

  const getTabCount = (tab: string) => getFilteredIssues(tab).length

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium">Issues</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchIssues}
            disabled={loading}
          >
            <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="flex items-center gap-3 py-8 text-center justify-center">
            <AlertCircle className="w-5 h-5 text-destructive" />
            <div>
              <p className="text-sm font-medium text-destructive">{error}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={fetchIssues}
                className="mt-2"
              >
                Retry
              </Button>
            </div>
          </div>
        ) : (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="w-full">
              <TabsTrigger value="in-progress" className="flex-1">
                In Progress ({loading ? "..." : getTabCount("in-progress")})
              </TabsTrigger>
              <TabsTrigger value="to-do" className="flex-1">
                To Do ({loading ? "..." : getTabCount("to-do")})
              </TabsTrigger>
              <TabsTrigger value="done" className="flex-1">
                Done ({loading ? "..." : getTabCount("done")})
              </TabsTrigger>
            </TabsList>

            {Object.keys(TAB_FILTERS).map((tab) => (
              <TabsContent key={tab} value={tab}>
                {loading ? (
                  <LoadingSkeleton />
                ) : (
                  <IssueGrid issues={getFilteredIssues(tab)} />
                )}
              </TabsContent>
            ))}
          </Tabs>
        )}
      </CardContent>
    </Card>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2 pt-2">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex items-center gap-3 p-3 rounded-lg border">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-5 w-20" />
        </div>
      ))}
    </div>
  )
}

function IssueGrid({ issues }: { issues: JiraIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground text-sm">
        No issues in this category
      </div>
    )
  }

  return (
    <div className="space-y-1 pt-2">
      {issues.map((issue, index) => (
        <motion.a
          key={issue.issue_id}
          href={`https://alldigitalrewards.atlassian.net/browse/${issue.issue_id}`}
          target="_blank"
          rel="noopener noreferrer"
          initial={{ opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.03 }}
          className="flex items-center gap-3 p-3 rounded-lg border hover:bg-muted/50 transition-colors group"
        >
          <Badge variant="outline" className="font-mono text-[10px] shrink-0">
            {issue.issue_id}
          </Badge>
          <span className="text-sm truncate flex-1 text-muted-foreground group-hover:text-foreground">
            {issue.summary}
          </span>
          <Badge
            variant="secondary"
            className={cn(
              "text-[10px] shrink-0",
              STATUS_COLORS[issue.status] || "bg-muted"
            )}
          >
            {issue.status}
          </Badge>
          <ExternalLink className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
        </motion.a>
      ))}
    </div>
  )
}
