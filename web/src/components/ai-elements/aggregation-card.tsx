"use client"

import * as React from "react"
import { memo } from "react"
import { motion } from "framer-motion"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { ChevronDown, ChevronRight, BarChart3 } from "lucide-react"

// Type colors matching issue-stats.tsx
const TYPE_COLORS: Record<string, string> = {
  Bug: "#ef4444",
  Story: "#22c55e",
  Task: "#3b82f6",
  Epic: "#8b5cf6",
  "Sub-task": "#6b7280",
  "New Feature": "#10b981",
  Improvement: "#f59e0b",
}

const STATUS_COLORS: Record<string, string> = {
  Done: "#22c55e",
  Closed: "#22c55e",
  "In Progress": "#eab308",
  "In Review": "#3b82f6",
  Backlog: "#6b7280",
  "To Do": "#8b5cf6",
  Open: "#ef4444",
}

const PRIORITY_COLORS: Record<string, string> = {
  Highest: "#ef4444",
  High: "#f97316",
  Medium: "#eab308",
  Low: "#22c55e",
  Lowest: "#6b7280",
}

const FALLBACK_COLORS = [
  "#6366f1",
  "#8b5cf6",
  "#a855f7",
  "#d946ef",
  "#ec4899",
  "#f43f5e",
]

function getColor(
  colorMap: Record<string, string>,
  key: string,
  index: number
): string {
  return colorMap[key] || FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

// Types matching backend response
export interface ProjectAggregations {
  project_key: string
  total_issues: number
  by_type: Record<string, number>
  by_status_category: Record<string, number>
  by_priority: Record<string, number>
  top_assignees: Record<string, number>
  top_labels: Record<string, number>
  top_components: Record<string, number>
  error?: string
}

interface DistributionChartProps {
  title: string
  data: Array<{ name: string; value: number }>
  colorMap: Record<string, string>
  maxBars?: number
}

const DistributionChart = memo(function DistributionChart({
  title,
  data,
  colorMap,
  maxBars = 8,
}: DistributionChartProps) {
  const sortedData = data.slice(0, maxBars)

  if (sortedData.length === 0) return null

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={sortedData}
            layout="vertical"
            margin={{ top: 0, right: 40, left: 0, bottom: 0 }}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={80}
              tick={{ fontSize: 10 }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              content={({ payload }) => {
                if (!payload?.[0]) return null
                const d = payload[0].payload
                return (
                  <div className="bg-popover border rounded px-2 py-1 text-xs shadow-lg">
                    <span className="font-medium">{d.name}</span>: {d.value}
                  </div>
                )
              }}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {sortedData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={getColor(colorMap, entry.name, index)}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
})

interface AggregationCardProps {
  aggregations: ProjectAggregations[]
  className?: string
  defaultOpen?: boolean
}

export const AggregationCard = memo(function AggregationCard({
  aggregations,
  className,
  defaultOpen = true,
}: AggregationCardProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen)

  if (!aggregations || aggregations.length === 0) return null

  // For multiple projects, show combined stats
  const totalIssues = aggregations.reduce((sum, a) => sum + a.total_issues, 0)

  // Combine distributions for display
  const combineRecords = (
    key: keyof ProjectAggregations
  ): Array<{ name: string; value: number }> => {
    const combined: Record<string, number> = {}
    for (const agg of aggregations) {
      const record = agg[key] as Record<string, number> | undefined
      if (record) {
        for (const [k, v] of Object.entries(record)) {
          combined[k] = (combined[k] || 0) + v
        }
      }
    }
    return Object.entries(combined)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }

  const byType = combineRecords("by_type")
  const byStatus = combineRecords("by_status_category")
  const byPriority = combineRecords("by_priority")
  const topAssignees = combineRecords("top_assignees")

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("my-3", className)}
    >
      <Card className="overflow-hidden">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <BarChart3 className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">
              Project Statistics
            </span>
            {aggregations.length > 1 && (
              <Badge variant="secondary" className="text-[10px]">
                {aggregations.length} projects
              </Badge>
            )}
            <Badge variant="outline" className="text-[10px]">
              {totalIssues.toLocaleString()} issues
            </Badge>
          </div>
          {isOpen ? (
            <ChevronDown className="size-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-4 text-muted-foreground" />
          )}
        </button>

        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            className="px-3 pb-3"
          >
            <div className="grid grid-cols-2 gap-4">
              <DistributionChart
                title="By Type"
                data={byType}
                colorMap={TYPE_COLORS}
              />
              <DistributionChart
                title="By Status"
                data={byStatus}
                colorMap={STATUS_COLORS}
              />
              <DistributionChart
                title="By Priority"
                data={byPriority}
                colorMap={PRIORITY_COLORS}
              />
              <DistributionChart
                title="Top Assignees"
                data={topAssignees}
                colorMap={{}}
              />
            </div>

            {/* Project breakdown for multi-project */}
            {aggregations.length > 1 && (
              <div className="mt-4 pt-3 border-t">
                <h4 className="text-xs font-medium text-muted-foreground mb-2">
                  By Project
                </h4>
                <div className="flex flex-wrap gap-2">
                  {aggregations.map((agg) => (
                    <Badge
                      key={agg.project_key}
                      variant="secondary"
                      className="text-xs"
                    >
                      {agg.project_key}: {agg.total_issues.toLocaleString()}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        )}
      </Card>
    </motion.div>
  )
})

AggregationCard.displayName = "AggregationCard"
