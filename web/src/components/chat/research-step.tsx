"use client"

import { motion } from "framer-motion"
import { Check, Loader2, Search, GitBranch, Link2, AlertCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"

interface ResearchStepProps {
  type: string
  state: "partial" | "output-available"
  input: Record<string, unknown>
  output?: {
    count?: number
    issues?: unknown[]
    error?: string
  }
}

const TOOL_CONFIG: Record<string, { icon: typeof Search; getLabel: (input: Record<string, unknown>) => string }> = {
  "tool-semantic_search": {
    icon: Search,
    getLabel: (input) => `Semantic Search: "${(input?.query as string)?.slice(0, 40) || "..."}"`,
  },
  "tool-jql_search": {
    icon: Search,
    getLabel: (input) => {
      const jql = (input?.jql as string) || ""
      return `JQL: ${jql.length > 35 ? jql.slice(0, 35) + "..." : jql}`
    },
  },
  "tool-get_epic_children": {
    icon: GitBranch,
    getLabel: (input) => `Fetching children of ${input?.epicKey || "epic"}`,
  },
  "tool-get_linked_issues": {
    icon: Link2,
    getLabel: (input) => `Getting links for ${input?.issueKey || "issue"}`,
  },
}

export function ResearchStep({ type, state, input, output }: ResearchStepProps) {
  const isSearching = state !== "output-available"
  const hasError = !!output?.error

  const config = TOOL_CONFIG[type] || {
    icon: Search,
    getLabel: () => type.replace("tool-", ""),
  }

  const Icon = config.icon
  const label = config.getLabel(input || {})
  const count = output?.count ?? output?.issues?.length

  return (
    <motion.div
      initial={{ opacity: 0, height: 0, marginBottom: 0 }}
      animate={{ opacity: 1, height: "auto", marginBottom: 4 }}
      transition={{ duration: 0.2 }}
      className="flex items-center gap-2 py-1 text-sm"
    >
      {/* Status indicator */}
      <div className="w-5 h-5 flex items-center justify-center flex-shrink-0">
        {isSearching ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />
        ) : hasError ? (
          <AlertCircle className="w-3.5 h-3.5 text-destructive" />
        ) : (
          <Check className="w-3.5 h-3.5 text-green-500" />
        )}
      </div>

      {/* Tool icon */}
      <Icon className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />

      {/* Label */}
      <span className="text-muted-foreground truncate">{label}</span>

      {/* Result count badge */}
      {!isSearching && count !== undefined && !hasError && (
        <Badge variant="secondary" className="text-xs flex-shrink-0">
          {count} {count === 1 ? "result" : "results"}
        </Badge>
      )}

      {/* Error message */}
      {hasError && (
        <span className="text-xs text-destructive truncate">
          {output.error}
        </span>
      )}
    </motion.div>
  )
}
