"use client"

import * as React from "react"
import { memo, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  Search,
  Database,
  GitBranch,
  Link2,
  ChevronDown,
  ChevronRight,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"

// Types
interface JiraIssue {
  issue_id: string
  summary: string
  status: string
  issue_type: string
  project_key: string
  assignee?: string | null
  description_preview?: string | null
  labels?: string[]
  score: number
  // Timestamps for temporal filtering
  created_at?: string
  updated_at?: string
}

export interface ResearchPhase {
  id?: string
  toolName: string
  input?: Record<string, unknown>
  output?: {
    issues?: JiraIssue[]
    count?: number
    error?: string
  }
  state?: string
}

interface ResearchStepsProps {
  phases: ResearchPhase[]
  isStreaming: boolean
  defaultOpen?: boolean
  className?: string
}

// Tool configuration for display
const toolConfig: Record<string, {
  icon: typeof Search
  label: string
  color: string
  bgColor: string
}> = {
  semantic_search: {
    icon: Search,
    label: "Semantic Search",
    color: "text-blue-500",
    bgColor: "bg-blue-500/10"
  },
  jql_search: {
    icon: Database,
    label: "JQL Query",
    color: "text-purple-500",
    bgColor: "bg-purple-500/10"
  },
  get_epic_children: {
    icon: GitBranch,
    label: "Epic Children",
    color: "text-green-500",
    bgColor: "bg-green-500/10"
  },
  get_linked_issues: {
    icon: Link2,
    label: "Linked Issues",
    color: "text-orange-500",
    bgColor: "bg-orange-500/10"
  },
}

// Status colors for issue cards
const statusColors: Record<string, string> = {
  "Closed": "bg-gray-500/10 text-gray-500",
  "Done": "bg-green-500/10 text-green-500",
  "In Progress": "bg-blue-500/10 text-blue-500",
  "Development in Progress": "bg-blue-500/10 text-blue-500",
  "Ready for QA": "bg-purple-500/10 text-purple-500",
  "QA in Progress": "bg-purple-500/10 text-purple-500",
  "Backlog": "bg-gray-500/10 text-gray-400",
  "Selected for Development": "bg-yellow-500/10 text-yellow-500",
  "Ready for Production": "bg-emerald-500/10 text-emerald-500",
}

const typeColors: Record<string, string> = {
  "Bug": "text-red-500",
  "Task": "text-blue-500",
  "Story": "text-green-500",
  "Epic": "text-purple-500",
  "New Feature": "text-emerald-500",
  "Initiative": "text-orange-500",
  "Sub-task": "text-gray-500",
}

// Issue card component showing full details
const IssueCard = memo(function IssueCard({
  issue,
  index
}: {
  issue: JiraIssue
  index: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.02 }}
      className="group p-3 rounded-lg border border-border/50 hover:border-border hover:bg-muted/30 transition-all"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <a
              href={`https://alldigitalrewards.atlassian.net/browse/${issue.issue_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs font-medium text-primary hover:underline inline-flex items-center gap-1"
            >
              {issue.issue_id}
              <ExternalLink className="size-3 opacity-0 group-hover:opacity-100 transition-opacity" />
            </a>
            <span className={cn("text-xs font-medium", typeColors[issue.issue_type] || "text-muted-foreground")}>
              {issue.issue_type}
            </span>
          </div>
          <p className="text-sm font-medium text-foreground line-clamp-2 mb-2">
            {issue.summary}
          </p>
          {issue.description_preview && (
            <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
              {issue.description_preview}
            </p>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn(
              "px-2 py-0.5 rounded-full text-xs font-medium",
              statusColors[issue.status] || "bg-gray-500/10 text-gray-500"
            )}>
              {issue.status}
            </span>
            {issue.assignee && (
              <span className="text-xs text-muted-foreground">
                {issue.assignee}
              </span>
            )}
            {issue.score < 1 && (
              <span className="text-xs text-muted-foreground/60">
                {Math.round(issue.score * 100)}% match
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  )
})
IssueCard.displayName = "IssueCard"

// Phase section component - expandable per-phase
const PhaseSection = memo(function PhaseSection({
  phase,
  index,
}: {
  phase: ResearchPhase
  index: number
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  const config = toolConfig[phase.toolName] || {
    icon: Search,
    label: phase.toolName,
    color: "text-muted-foreground",
    bgColor: "bg-muted"
  }
  const Icon = config.icon
  const issues = phase.output?.issues || []
  const hasError = !!phase.output?.error
  const isComplete = phase.state === "output-available"

  // Format input for display
  const inputDisplay = phase.input?.query
    ? `"${String(phase.input.query).slice(0, 60)}${String(phase.input.query).length > 60 ? '...' : ''}"`
    : phase.input?.jql
    ? String(phase.input.jql).slice(0, 60) + (String(phase.input.jql).length > 60 ? '...' : '')
    : phase.input?.epicKey
    ? `Epic: ${phase.input.epicKey}`
    : phase.input?.issueKey
    ? `Issue: ${phase.input.issueKey}`
    : ""

  return (
    <div className="relative">
      {/* Phase header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 p-2 rounded-md hover:bg-muted/50 transition-colors text-left"
      >
        <div className={cn("p-1.5 rounded-md", config.bgColor)}>
          <Icon className={cn("size-3.5", config.color)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-xs">{config.label}</span>
            {hasError ? (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-red-500/10 text-red-500">
                <AlertCircle className="size-2.5" />
                Error
              </span>
            ) : isComplete ? (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-green-500/10 text-green-500">
                <CheckCircle2 className="size-2.5" />
                {issues.length} result{issues.length !== 1 ? 's' : ''}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-yellow-500/10 text-yellow-500">
                <Loader2 className="size-2.5 animate-spin" />
                Running
              </span>
            )}
          </div>
          {inputDisplay && (
            <p className="text-[10px] text-muted-foreground truncate mt-0.5">
              {inputDisplay}
            </p>
          )}
        </div>
        <ChevronRight className={cn(
          "size-3.5 text-muted-foreground transition-transform",
          isExpanded && "rotate-90"
        )} />
      </button>

      {/* Phase content */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pl-10 pr-2 pb-3 space-y-2">
              {/* Error state */}
              {hasError && (
                <div className="p-2 rounded-md bg-red-500/10 border border-red-500/20">
                  <p className="text-xs text-red-500">{phase.output?.error}</p>
                </div>
              )}

              {/* Loading state */}
              {!isComplete && !hasError && (
                <div className="flex items-center gap-2 p-2 rounded-md bg-muted/50">
                  <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">Searching...</span>
                </div>
              )}

              {/* No results */}
              {isComplete && !hasError && issues.length === 0 && (
                <div className="p-2 rounded-md bg-muted/50">
                  <p className="text-xs text-muted-foreground">No results found</p>
                </div>
              )}

              {/* Results */}
              {isComplete && !hasError && issues.length > 0 && (
                <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                  {issues.map((issue, i) => (
                    <IssueCard key={issue.issue_id} issue={issue} index={i} />
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
})
PhaseSection.displayName = "PhaseSection"

// Main ResearchSteps component
export const ResearchSteps = memo(function ResearchSteps({
  phases,
  isStreaming,
  defaultOpen = false,
  className,
}: ResearchStepsProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  // Calculate totals
  const totalResults = phases.reduce((acc, phase) => {
    return acc + (phase.output?.issues?.length || 0)
  }, 0)

  const uniqueIssueIds = new Set(
    phases.flatMap(p => p.output?.issues?.map(i => i.issue_id) || [])
  )

  const completedPhases = phases.filter(p => p.state === "output-available").length

  if (phases.length === 0) return null

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      className={cn("my-2", className)}
    >
      {/* Header trigger */}
      <CollapsibleTrigger
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors w-full",
          "text-muted-foreground hover:text-foreground hover:bg-muted/50",
          isOpen && "bg-muted/30"
        )}
      >
        {isStreaming ? (
          <Loader2 className="size-3.5 animate-spin text-blue-500" />
        ) : (
          <CheckCircle2 className="size-3.5 text-green-500" />
        )}
        <span className="font-medium flex-1 text-left">
          {isStreaming
            ? `Researching... (${completedPhases}/${phases.length})`
            : "Research complete"
          }
        </span>
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {phases.length} phase{phases.length !== 1 ? 's' : ''} {!isStreaming && `• ${uniqueIssueIds.size} results`}
        </Badge>
        <ChevronDown
          className={cn(
            "size-3 transition-transform duration-200",
            isOpen && "rotate-180"
          )}
        />
      </CollapsibleTrigger>

      {/* Content */}
      <CollapsibleContent
        className={cn(
          "data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
          "overflow-hidden"
        )}
      >
        <div className="mt-2 px-2 py-2 bg-muted/20 rounded-lg border border-border/50">
          <div className="space-y-1">
            {phases.map((phase, index) => (
              <PhaseSection
                key={phase.id || `phase-${index}`}
                phase={phase}
                index={index}
              />
            ))}
          </div>

          {/* Summary footer */}
          {!isStreaming && phases.length > 0 && (
            <div className="mt-3 pt-2 border-t border-border/50 flex items-center justify-between text-[10px] text-muted-foreground px-2">
              <span>Total gathered</span>
              <span className="font-medium">{totalResults} issues ({uniqueIssueIds.size} unique)</span>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
})
ResearchSteps.displayName = "ResearchSteps"
