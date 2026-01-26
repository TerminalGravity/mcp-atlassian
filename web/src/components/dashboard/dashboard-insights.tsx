"use client"

import { useEffect, useState, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Loader2, RefreshCw, AlertCircle, Check, Search, Database, Clock, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Streamdown } from "streamdown"
import { cn } from "@/lib/utils"

interface ResearchStep {
  id: string
  label: string
  icon: typeof Search
  status: "pending" | "running" | "complete" | "error"
  resultCount?: number
}

interface DashboardInsightsProps {
  currentUser: string
}

export function DashboardInsights({ currentUser }: DashboardInsightsProps) {
  const [status, setStatus] = useState<"idle" | "researching" | "complete" | "error">("idle")
  const [insights, setInsights] = useState<string>("")
  const [error, setError] = useState<string | null>(null)
  const [steps, setSteps] = useState<ResearchStep[]>([])
  const abortControllerRef = useRef<AbortController | null>(null)

  const runResearch = async () => {
    // Cancel any existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    abortControllerRef.current = new AbortController()

    setStatus("researching")
    setInsights("")
    setError(null)
    setSteps([
      { id: "blockers", label: "Checking blockers", icon: AlertTriangle, status: "pending" },
      { id: "stale", label: "Finding stale issues", icon: Clock, status: "pending" },
      { id: "sprint", label: "Reviewing sprint", icon: Database, status: "pending" },
    ])

    try {
      const response = await fetch("/api/dashboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currentUser }),
        signal: abortControllerRef.current.signal,
      })

      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error("No response body")
      }

      const decoder = new TextDecoder()
      let buffer = ""
      let stepIndex = 0

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Process complete lines
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (!line.trim() || !line.startsWith("data: ")) continue

          const data = line.slice(6)
          if (data === "[DONE]") continue

          try {
            const parsed = JSON.parse(data)

            // Handle different message types
            if (parsed.type === "tool-invocation" || parsed.type?.startsWith("tool-")) {
              // Update step status
              if (stepIndex < steps.length) {
                setSteps(prev => prev.map((s, i) =>
                  i === stepIndex ? { ...s, status: "running" } : s
                ))
              }
            } else if (parsed.type === "tool-result") {
              // Mark step complete
              const resultCount = parsed.output?.issues?.length || parsed.output?.count || 0
              setSteps(prev => prev.map((s, i) =>
                i === stepIndex ? { ...s, status: "complete", resultCount } : s
              ))
              stepIndex++
            } else if (parsed.type === "text" || parsed.type === "text-delta") {
              // Append text content
              const text = parsed.text || parsed.textDelta || ""
              if (text) {
                setInsights(prev => prev + text)
              }
            }
          } catch {
            // Not JSON, might be raw text
          }
        }
      }

      // Mark all remaining steps as complete
      setSteps(prev => prev.map(s =>
        s.status === "pending" || s.status === "running"
          ? { ...s, status: "complete" }
          : s
      ))
      setStatus("complete")
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return // Request was cancelled
      }
      setError(err instanceof Error ? err.message : "Unknown error")
      setStatus("error")
    }
  }

  // Run research on mount and when user changes
  useEffect(() => {
    runResearch()
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [currentUser])

  return (
    <div className="space-y-6">
      {/* Research Steps */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              {status === "researching" ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analyzing Jira...
                </>
              ) : status === "complete" ? (
                <>
                  <Check className="w-4 h-4 text-green-500" />
                  Analysis Complete
                </>
              ) : status === "error" ? (
                <>
                  <AlertCircle className="w-4 h-4 text-destructive" />
                  Analysis Failed
                </>
              ) : (
                "Ready to analyze"
              )}
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={runResearch}
              disabled={status === "researching"}
            >
              <RefreshCw className={cn("w-4 h-4", status === "researching" && "animate-spin")} />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {steps.map((step) => {
              const Icon = step.icon
              return (
                <motion.div
                  key={step.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 rounded-lg text-sm",
                    step.status === "running" && "bg-muted/50",
                    step.status === "complete" && "text-muted-foreground"
                  )}
                >
                  <div className={cn(
                    "w-6 h-6 rounded-md flex items-center justify-center",
                    step.status === "pending" && "bg-muted text-muted-foreground",
                    step.status === "running" && "bg-primary/10 text-primary",
                    step.status === "complete" && "bg-green-500/10 text-green-500",
                    step.status === "error" && "bg-destructive/10 text-destructive"
                  )}>
                    {step.status === "running" ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : step.status === "complete" ? (
                      <Check className="w-3.5 h-3.5" />
                    ) : (
                      <Icon className="w-3.5 h-3.5" />
                    )}
                  </div>
                  <span className="flex-1">{step.label}</span>
                  {step.status === "complete" && step.resultCount !== undefined && (
                    <Badge variant="secondary" className="text-[10px]">
                      {step.resultCount} found
                    </Badge>
                  )}
                </motion.div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Error State */}
      <AnimatePresence>
        {status === "error" && error && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <Card className="border-destructive">
              <CardContent className="pt-6">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-destructive shrink-0" />
                  <div>
                    <p className="font-medium text-destructive">Analysis failed</p>
                    <p className="text-sm text-muted-foreground mt-1">{error}</p>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={runResearch}
                      className="mt-3"
                    >
                      Try again
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Insights */}
      <AnimatePresence>
        {insights && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <Card>
              <CardHeader>
                <CardTitle className="text-base">What Needs Attention</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <Streamdown>{insights}</Streamdown>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
