"use client"

import { motion } from "framer-motion"
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts"
import { Card } from "@/components/ui/card"

interface JiraIssue {
  issue_id?: string
  key?: string
  summary: string
  status: string
  issue_type?: string
  project_key?: string
  assignee?: string | null
}

interface IssueStatsProps {
  issues: JiraIssue[]
}

const STATUS_COLORS: Record<string, string> = {
  "Done": "#22c55e",
  "Closed": "#22c55e",
  "In Progress": "#eab308",
  "In Review": "#3b82f6",
  "Backlog": "#6b7280",
  "To Do": "#8b5cf6",
  "Open": "#ef4444",
}

const TYPE_COLORS: Record<string, string> = {
  "Bug": "#ef4444",
  "Story": "#22c55e",
  "Task": "#3b82f6",
  "Epic": "#8b5cf6",
  "Sub-task": "#6b7280",
  "New Feature": "#10b981",
  "Improvement": "#f59e0b",
}

function getColor(map: Record<string, string>, key: string, index: number): string {
  const fallbackColors = ["#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899", "#f43f5e"]
  return map[key] || fallbackColors[index % fallbackColors.length]
}

export function IssueStats({ issues }: IssueStatsProps) {
  if (issues.length === 0) return null

  // Calculate status distribution
  const statusCounts = issues.reduce((acc, issue) => {
    const status = issue.status || "Unknown"
    acc[status] = (acc[status] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const statusData = Object.entries(statusCounts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  // Calculate type distribution
  const typeCounts = issues.reduce((acc, issue) => {
    const type = issue.issue_type || "Unknown"
    acc[type] = (acc[type] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const typeData = Object.entries(typeCounts)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  // Calculate project distribution
  const projectCounts = issues.reduce((acc, issue) => {
    const project = issue.project_key || "Unknown"
    acc[project] = (acc[project] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="grid grid-cols-3 gap-4 my-4"
    >
      {/* Status Chart */}
      <Card className="p-4">
        <h4 className="text-xs font-medium text-muted-foreground mb-2">By Status</h4>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={statusData}
                cx="50%"
                cy="50%"
                innerRadius={20}
                outerRadius={35}
                paddingAngle={2}
                dataKey="value"
              >
                {statusData.map((entry, index) => (
                  <Cell key={`status-${index}`} fill={getColor(STATUS_COLORS, entry.name, index)} />
                ))}
              </Pie>
              <Tooltip
                content={({ payload }) => {
                  if (!payload?.[0]) return null
                  const data = payload[0].payload
                  return (
                    <div className="bg-popover border rounded px-2 py-1 text-xs shadow-lg">
                      <span className="font-medium">{data.name}</span>: {data.value}
                    </div>
                  )
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {statusData.slice(0, 3).map((s, i) => (
            <span key={s.name} className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted">
              {s.name}: {s.value}
            </span>
          ))}
        </div>
      </Card>

      {/* Type Chart */}
      <Card className="p-4">
        <h4 className="text-xs font-medium text-muted-foreground mb-2">By Type</h4>
        <div className="h-24">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={typeData}
                cx="50%"
                cy="50%"
                innerRadius={20}
                outerRadius={35}
                paddingAngle={2}
                dataKey="value"
              >
                {typeData.map((entry, index) => (
                  <Cell key={`type-${index}`} fill={getColor(TYPE_COLORS, entry.name, index)} />
                ))}
              </Pie>
              <Tooltip
                content={({ payload }) => {
                  if (!payload?.[0]) return null
                  const data = payload[0].payload
                  return (
                    <div className="bg-popover border rounded px-2 py-1 text-xs shadow-lg">
                      <span className="font-medium">{data.name}</span>: {data.value}
                    </div>
                  )
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {typeData.slice(0, 3).map((t, i) => (
            <span key={t.name} className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted">
              {t.name}: {t.value}
            </span>
          ))}
        </div>
      </Card>

      {/* Project Summary */}
      <Card className="p-4">
        <h4 className="text-xs font-medium text-muted-foreground mb-2">By Project</h4>
        <div className="space-y-2">
          {Object.entries(projectCounts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 4)
            .map(([project, count]) => (
              <div key={project} className="flex items-center justify-between">
                <span className="text-sm font-medium">{project}</span>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${(count / issues.length) * 100}%` }}
                      transition={{ duration: 0.5, delay: 0.2 }}
                      className="h-full bg-primary rounded-full"
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-6 text-right">{count}</span>
                </div>
              </div>
            ))}
        </div>
      </Card>
    </motion.div>
  )
}
