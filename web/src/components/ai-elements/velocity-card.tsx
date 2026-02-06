"use client"

import * as React from "react"
import { memo } from "react"
import { motion } from "framer-motion"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  ChevronDown,
  ChevronRight,
  Gauge,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react"

// Types matching backend response
export interface WeeklyMetric {
  week: number
  week_ending: string
  created: number
  resolved: number
  net: number
}

export interface VelocityMetrics {
  project_key: string
  weeks_analyzed: number
  weekly_metrics: WeeklyMetric[]
  averages: {
    avg_created_per_week: number
    avg_resolved_per_week: number
    avg_net_change: number
  }
  backlog_trend: "growing" | "shrinking"
  error?: string
}

interface VelocityCardProps {
  velocity: VelocityMetrics
  className?: string
  defaultOpen?: boolean
}

export const VelocityCard = memo(function VelocityCard({
  velocity,
  className,
  defaultOpen = true,
}: VelocityCardProps) {
  const [isOpen, setIsOpen] = React.useState(defaultOpen)

  if (!velocity || velocity.error) return null

  const { averages, backlog_trend, weekly_metrics } = velocity
  const isGrowing = backlog_trend === "growing"

  // Format data for chart
  const chartData = weekly_metrics.map((m) => ({
    week: `W${m.week}`,
    weekEnding: m.week_ending,
    created: m.created,
    resolved: m.resolved,
    net: m.net,
  })).reverse() // Show oldest first

  // Calculate health indicator
  const getHealthStatus = () => {
    if (averages.avg_net_change > 5) return { label: "Backlog Growing", color: "text-red-500", icon: TrendingUp }
    if (averages.avg_net_change < -5) return { label: "Backlog Shrinking", color: "text-green-500", icon: TrendingDown }
    return { label: "Stable", color: "text-yellow-500", icon: Minus }
  }

  const health = getHealthStatus()
  const HealthIcon = health.icon

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
            <Gauge className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">
              Velocity Metrics
            </span>
            <Badge variant="secondary" className="text-[10px]">
              {velocity.project_key}
            </Badge>
            <Badge
              variant="outline"
              className={cn("text-[10px]", health.color)}
            >
              <HealthIcon className="size-3 mr-1" />
              {health.label}
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
            {/* Key metrics */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="text-center p-2 rounded-lg bg-blue-500/10">
                <div className="text-2xl font-semibold text-blue-500">
                  {averages.avg_created_per_week.toFixed(1)}
                </div>
                <div className="text-xs text-muted-foreground">
                  Avg Created/Week
                </div>
              </div>
              <div className="text-center p-2 rounded-lg bg-green-500/10">
                <div className="text-2xl font-semibold text-green-500">
                  {averages.avg_resolved_per_week.toFixed(1)}
                </div>
                <div className="text-xs text-muted-foreground">
                  Avg Resolved/Week
                </div>
              </div>
              <div
                className={cn(
                  "text-center p-2 rounded-lg",
                  isGrowing ? "bg-red-500/10" : "bg-green-500/10"
                )}
              >
                <div
                  className={cn(
                    "text-2xl font-semibold",
                    isGrowing ? "text-red-500" : "text-green-500"
                  )}
                >
                  {averages.avg_net_change > 0 ? "+" : ""}
                  {averages.avg_net_change.toFixed(1)}
                </div>
                <div className="text-xs text-muted-foreground">
                  Avg Net/Week
                </div>
              </div>
            </div>

            {/* Area chart */}
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={chartData}
                  margin={{ top: 5, right: 5, left: -20, bottom: 5 }}
                >
                  <defs>
                    <linearGradient id="colorCreated" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorResolved" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="week"
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
                      const data = payload[0].payload
                      return (
                        <div className="bg-popover border rounded px-2 py-1 text-xs shadow-lg">
                          <div className="font-medium mb-1">
                            Week ending {data.weekEnding}
                          </div>
                          <div className="text-blue-500">
                            Created: {data.created}
                          </div>
                          <div className="text-green-500">
                            Resolved: {data.resolved}
                          </div>
                          <div
                            className={
                              data.net > 0 ? "text-red-500" : "text-green-500"
                            }
                          >
                            Net: {data.net > 0 ? "+" : ""}
                            {data.net}
                          </div>
                        </div>
                      )
                    }}
                  />
                  <ReferenceLine
                    y={averages.avg_created_per_week}
                    stroke="#3b82f6"
                    strokeDasharray="3 3"
                    strokeOpacity={0.5}
                  />
                  <Area
                    type="monotone"
                    dataKey="created"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    fill="url(#colorCreated)"
                  />
                  <Area
                    type="monotone"
                    dataKey="resolved"
                    stroke="#22c55e"
                    strokeWidth={2}
                    fill="url(#colorResolved)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Weekly breakdown */}
            <div className="mt-3 pt-3 border-t">
              <h4 className="text-xs font-medium text-muted-foreground mb-2">
                {velocity.weeks_analyzed} Week Breakdown
              </h4>
              <div className="grid grid-cols-4 gap-2">
                {weekly_metrics.map((m) => (
                  <div
                    key={m.week}
                    className="text-center p-1.5 rounded bg-muted/30"
                  >
                    <div className="text-xs font-medium">
                      Week ending {m.week_ending}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span className="text-blue-500">+{m.created}</span>
                      {" / "}
                      <span className="text-green-500">-{m.resolved}</span>
                      {" = "}
                      <span
                        className={m.net > 0 ? "text-red-500" : "text-green-500"}
                      >
                        {m.net > 0 ? "+" : ""}
                        {m.net}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </Card>
    </motion.div>
  )
})

VelocityCard.displayName = "VelocityCard"
