"use client"

import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import type { UIMessage } from "ai"
import { Bot, User, Search, Database, ChevronDown, ChevronUp, AlertCircle, GitBranch, Link2, Check, Loader2 } from "lucide-react"
import { useState } from "react"
import { IssueStats } from "./issue-stats"
import { Streamdown } from "streamdown"
import { SuggestionChips } from "./suggestion-chips"
import { Reasoning } from "./reasoning"
import { Sources } from "./sources"

interface ChatMessageProps {
  message: UIMessage
  onSendMessage?: (text: string) => void
}

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
}

// Compact tool invocation - collapsed by default, shows summary
function ToolInvocation({ toolName, input, output, state, index, defaultExpanded = false }: {
  toolName: string
  input?: { query?: string; jql?: string; limit?: number; epicKey?: string; issueKey?: string; epicSummary?: string }
  output?: { issues?: JiraIssue[]; count?: number; error?: string; suggestion?: string; note?: string }
  state?: string
  index: number
  defaultExpanded?: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const isComplete = state === "output-available" && output !== undefined
  const isLoading = !isComplete
  const issues = output?.issues || []
  const hasError = !!output?.error

  // Extract query/jql from input
  const queryText = input?.query
  const jqlText = input?.jql
  const epicKey = input?.epicKey
  const issueKey = input?.issueKey

  // Tool display configuration
  const toolConfig: Record<string, { icon: typeof Search; label: string; color: string; bgColor: string }> = {
    semantic_search: {
      icon: Search,
      label: "Semantic Search",
      color: "text-blue-500",
      bgColor: "bg-blue-500/10",
    },
    jql_search: {
      icon: Database,
      label: "JQL Query",
      color: "text-purple-500",
      bgColor: "bg-purple-500/10",
    },
    get_epic_children: {
      icon: GitBranch,
      label: "Epic Children",
      color: "text-green-500",
      bgColor: "bg-green-500/10",
    },
    get_linked_issues: {
      icon: Link2,
      label: "Linked Issues",
      color: "text-orange-500",
      bgColor: "bg-orange-500/10",
    },
  }

  const config = toolConfig[toolName] || {
    icon: Search,
    label: toolName,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  }
  const Icon = config.icon

  // Generate short description
  const getShortDescription = () => {
    if (queryText) return `"${queryText.slice(0, 30)}${queryText.length > 30 ? '...' : ''}"`
    if (jqlText) return jqlText.slice(0, 40) + (jqlText.length > 40 ? '...' : '')
    if (epicKey) return epicKey
    if (issueKey) return issueKey
    return ''
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="group"
    >
      {/* Compact header - always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        disabled={isLoading && !hasError}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 text-xs rounded-lg transition-all",
          "border border-transparent",
          isLoading ? "bg-muted/50" : "bg-muted/30 hover:bg-muted/50 hover:border-border/50",
          expanded && "bg-muted/50 border-border/50"
        )}
      >
        {/* Icon with status indicator */}
        <div className={cn("w-6 h-6 rounded-md flex items-center justify-center shrink-0", config.bgColor)}>
          {isLoading ? (
            <Loader2 className={cn("w-3.5 h-3.5 animate-spin", config.color)} />
          ) : hasError ? (
            <AlertCircle className="w-3.5 h-3.5 text-destructive" />
          ) : (
            <Icon className={cn("w-3.5 h-3.5", config.color)} />
          )}
        </div>

        {/* Label and description */}
        <span className="font-medium text-foreground">{config.label}</span>
        <span className="text-muted-foreground truncate flex-1 text-left">
          {getShortDescription()}
        </span>

        {/* Result badge */}
        {isComplete && !hasError && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
            {issues.length} {issues.length === 1 ? 'result' : 'results'}
          </Badge>
        )}
        {hasError && (
          <Badge variant="destructive" className="text-[10px] px-1.5 py-0 shrink-0">
            Error
          </Badge>
        )}

        {/* Expand indicator */}
        {isComplete && (
          <div className="shrink-0">
            {expanded ? (
              <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
            )}
          </div>
        )}
      </button>

      {/* Expanded content */}
      <AnimatePresence>
        {isComplete && expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-1 ml-8 p-3 rounded-lg bg-muted/20 border border-border/30">
              {/* Error state */}
              {hasError && (
                <div className="flex items-start gap-2 text-destructive">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-medium">{output?.error}</p>
                    {output?.suggestion && (
                      <p className="text-xs text-muted-foreground mt-1">{output.suggestion}</p>
                    )}
                  </div>
                </div>
              )}

              {/* Note (e.g., "Found via keyword search") */}
              {output?.note && !hasError && (
                <p className="text-xs text-muted-foreground mb-2 italic">{output.note}</p>
              )}

              {/* Stats visualization - only for larger result sets */}
              {!hasError && issues.length >= 5 && (
                <div className="mb-3">
                  <IssueStats issues={issues} />
                </div>
              )}

              {/* Issue list - compact format */}
              {!hasError && issues.length > 0 && (
                <div className="space-y-1">
                  {issues.slice(0, 8).map((issue, i) => (
                    <a
                      key={issue.issue_id}
                      href={`https://alldigitalrewards.atlassian.net/browse/${issue.issue_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 px-2 py-1.5 rounded text-xs hover:bg-muted/50 transition-colors group/item"
                    >
                      <Badge variant="outline" className="text-[10px] font-mono shrink-0 py-0">
                        {issue.issue_id}
                      </Badge>
                      <span className="truncate flex-1 text-muted-foreground group-hover/item:text-foreground">
                        {issue.summary}
                      </span>
                      <Badge
                        variant="secondary"
                        className={cn(
                          "text-[9px] shrink-0 py-0",
                          (issue.status === "Done" || issue.status === "Closed") && "bg-green-500/10 text-green-500",
                          (issue.status === "In Progress" || issue.status === "Development in Progress") && "bg-yellow-500/10 text-yellow-500",
                          issue.status === "Backlog" && "bg-gray-500/10 text-gray-500"
                        )}
                      >
                        {issue.status}
                      </Badge>
                    </a>
                  ))}
                  {issues.length > 8 && (
                    <p className="text-[10px] text-muted-foreground text-center pt-1">
                      +{issues.length - 8} more results
                    </p>
                  )}
                </div>
              )}

              {/* Empty state */}
              {!hasError && issues.length === 0 && (
                <p className="text-xs text-muted-foreground">No results found</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// Research steps summary - shows all tools in a compact list
function ResearchSteps({ toolParts }: { toolParts: Array<{ toolName: string; input?: unknown; output?: unknown; state?: string }> }) {
  const [allExpanded, setAllExpanded] = useState(false)
  const completedCount = toolParts.filter(t => (t as { state?: string }).state === "output-available").length
  const totalCount = toolParts.length

  if (toolParts.length === 0) return null

  return (
    <div className="space-y-1.5">
      {/* Summary header */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          {completedCount === totalCount ? (
            <Check className="w-3.5 h-3.5 text-green-500" />
          ) : (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          )}
          <span>
            {completedCount === totalCount
              ? `Completed ${totalCount} research ${totalCount === 1 ? 'step' : 'steps'}`
              : `Running research (${completedCount}/${totalCount})`
            }
          </span>
        </div>
        {completedCount === totalCount && totalCount > 1 && (
          <button
            onClick={() => setAllExpanded(!allExpanded)}
            className="text-[10px] text-muted-foreground hover:text-foreground underline"
          >
            {allExpanded ? 'Collapse all' : 'Expand all'}
          </button>
        )}
      </div>

      {/* Tool invocations */}
      {toolParts.map((tool, index) => (
        <ToolInvocation
          key={`${tool.toolName}-${index}`}
          toolName={tool.toolName}
          input={tool.input as { query?: string; jql?: string; limit?: number; epicKey?: string; issueKey?: string }}
          output={tool.output as { issues?: JiraIssue[]; count?: number; error?: string; suggestion?: string }}
          state={(tool as { state?: string }).state}
          index={index}
          defaultExpanded={allExpanded}
        />
      ))}
    </div>
  )
}

export function ChatMessage({ message, onSendMessage }: ChatMessageProps) {
  const isUser = message.role === "user"
  const parts = message.parts || []

  // Extract different part types
  const toolParts = parts.filter((p) => p.type.startsWith('tool-')).map(p => ({
    ...p,
    toolName: p.type.replace('tool-', ''),
    input: (p as { input?: unknown }).input,
    output: (p as { output?: unknown }).output,
    state: (p as { state?: string }).state,
  }))
  const textParts = parts.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
  const textContent = textParts.map(p => p.text).join('')

  // Extract custom data parts
  const suggestionParts = parts.filter((p): p is { type: 'data-suggestions'; data: { prompts: string[] } } =>
    p.type === 'data-suggestions'
  )
  const reasoningParts = parts.filter((p): p is { type: 'data-reasoning'; data: { content: string; duration?: number } } =>
    p.type === 'data-reasoning'
  )

  // Collect all issues from tool outputs for the Sources component
  const allIssues = toolParts
    .flatMap(t => (t.output as { issues?: JiraIssue[] })?.issues || [])
    .filter((issue, index, self) => self.findIndex(i => i.issue_id === issue.issue_id) === index)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("flex gap-3 py-4", isUser && "flex-row-reverse")}
    >
      <Avatar className={cn(
        "h-8 w-8 flex-shrink-0",
        isUser ? "bg-primary" : "bg-muted"
      )}>
        <div className="flex items-center justify-center w-full h-full">
          {isUser ? (
            <User className="h-4 w-4 text-primary-foreground" />
          ) : (
            <Bot className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
      </Avatar>

      <div className={cn("flex-1 space-y-3 min-w-0", isUser && "text-right")}>
        {/* Research steps (tool invocations) - collapsed by default */}
        {!isUser && toolParts.length > 0 && (
          <ResearchSteps toolParts={toolParts} />
        )}

        {/* Reasoning (if available) */}
        {!isUser && reasoningParts.length > 0 && reasoningParts.map((part, i) => (
          <Reasoning
            key={`reasoning-${i}`}
            content={part.data.content}
            duration={part.data.duration}
            isComplete={true}
          />
        ))}

        {/* Message content */}
        {textContent && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
            className={cn(
              "prose prose-sm dark:prose-invert max-w-none",
              isUser && "text-right"
            )}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap leading-relaxed">{textContent}</p>
            ) : (
              <Streamdown>{textContent}</Streamdown>
            )}
          </motion.div>
        )}

        {/* Sources summary (collapsible) - only if we have issues and text content */}
        {!isUser && textContent && allIssues.length > 0 && (
          <Sources
            sources={allIssues.map(i => ({
              issue_id: i.issue_id,
              summary: i.summary,
              status: i.status,
            }))}
            maxVisible={5}
          />
        )}

        {/* Follow-up suggestions */}
        {!isUser && suggestionParts.length > 0 && suggestionParts.map((part, i) => (
          <SuggestionChips
            key={`suggestions-${i}`}
            prompts={part.data.prompts}
            onSelect={onSendMessage}
          />
        ))}
      </div>
    </motion.div>
  )
}
