"use client"

import * as React from "react"
import { memo } from "react"
import { motion } from "framer-motion"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { ChevronDown, ChevronRight, TrendingUp, TrendingDown } from "lucide-react"

// Types matching backend response
export interface TrendPeriod {
  period_start: string
  period_end: string
  total_created: number
  total_resolved: number
  net_change: number
  by_type?: Record<string, number>
  by_priority?: Record<string, number>
  trending_labels?: Array<{ label: string; count: number }>
}

export interface TrendData {
  project_key: string | null
  days_analyzed: number
  period_days: number
  periods: TrendPeriod[]
}

interface TrendChartProps {
  trendData: TrendData
  className?: string
  defaultOpen?: boolean
}

export const TrendChart = memo(function TrendChart({
  trendData,
  className,
  defaultOpen = true,
}: TrendChartProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen)

  if (!trendData?.periods || trendData.periods.length === 0) return null

  // Format data for chart
  const chartData = trendData.periods.map((p) => {
    const startDate = new Date(p.period_start)
    return {
      date: startDate.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      created: p.total_created,
      resolved: p.total_resolved,
      net: p.net_change,
    }
  })

  // Calculate totals and trends
  const totalCreated = trendData.periods.reduce(
    (sum, p) => sum + p.total_created,
    0
  )
  const totalResolved = trendData.periods.reduce(
    (sum, p) => sum + p.total_resolved,
    0
  )
  const netChange = totalCreated - totalResolved
  const isGrowing = netChange > 0

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
            {isGrowing ? (
              <TrendingUp className="size-4 text-red-500" />
            ) : (
              <TrendingDown className="size-4 text-green-500" />
            )}
            <span className="text-sm font-medium">
              Issue Trends ({trendData.days_analyzed} days)
            </span>
            {trendData.project_key && (
              <Badge variant="secondary" className="text-[10px]">
                {trendData.project_key}
              </Badge>
            )}
            <Badge
              variant="outline"
              className={cn(
                "text-[10px]",
                isGrowing ? "text-red-500" : "text-green-500"
              )}
            >
              {isGrowing ? "+" : ""}
              {netChange} net
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
            {/* Summary stats */}
            <div className="flex gap-4 mb-4">
              <div className="text-center">
                <div className="text-2xl font-semibold text-blue-500">
                  {totalCreated}
                </div>
                <div className="text-xs text-muted-foreground">Created</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-semibold text-green-500">
                  {totalResolved}
                </div>
                <div className="text-xs text-muted-foreground">Resolved</div>
              </div>
              <div className="text-center">
                <div
                  className={cn(
                    "text-2xl font-semibold",
                    isGrowing ? "text-red-500" : "text-green-500"
                  )}
                >
                  {isGrowing ? "+" : ""}
                  {netChange}
                </div>
                <div className="text-xs text-muted-foreground">Net Change</div>
              </div>
            </div>

            {/* Chart */}
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={chartData}
                  margin={{ top: 5, right: 5, left: -20, bottom: 5 }}
                >
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    content={({ payload, label }) => {
                      if (!payload?.[0]) return null
                      return (
                        <div className="bg-popover border rounded px-2 py-1 text-xs shadow-lg">
                          <div className="font-medium mb-1">{label}</div>
                          {payload.map((p, i) => (
                            <div key={i} className="flex justify-between gap-3">
                              <span style={{ color: p.color }}>{p.name}:</span>
                              <span className="font-medium">{p.value}</span>
                            </div>
                          ))}
                        </div>
                      )
                    }}
                  />
                  <Legend
                    verticalAlign="top"
                    height={24}
                    formatter={(value) => (
                      <span className="text-xs text-muted-foreground">
                        {value}
                      </span>
                    )}
                  />
                  <ReferenceLine y={0} stroke="#666" strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey="created"
                    name="Created"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="resolved"
                    name="Resolved"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="net"
                    name="Net"
                    stroke={isGrowing ? "#ef4444" : "#22c55e"}
                    strokeWidth={1}
                    strokeDasharray="4 4"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Period breakdown */}
            <div className="mt-3 pt-3 border-t">
              <h4 className="text-xs font-medium text-muted-foreground mb-2">
                Weekly Breakdown
              </h4>
              <div className="flex flex-wrap gap-2">
                {trendData.periods.map((p, i) => {
                  const start = new Date(p.period_start).toLocaleDateString(
                    "en-US",
                    { month: "short", day: "numeric" }
                  )
                  return (
                    <Badge
                      key={i}
                      variant="outline"
                      className={cn(
                        "text-[10px]",
                        p.net_change > 0
                          ? "border-red-500/30"
                          : "border-green-500/30"
                      )}
                    >
                      {start}: +{p.total_created}/-{p.total_resolved}
                    </Badge>
                  )
                })}
              </div>
            </div>
          </motion.div>
        )}
      </Card>
    </motion.div>
  )
})

TrendChart.displayName = "TrendChart"
