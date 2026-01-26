"use client"

import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { UIMessage } from "ai"
import { Bot, User, ExternalLink, Search, Database, ChevronDown, ChevronUp, AlertCircle, GitBranch, Link2 } from "lucide-react"
import { useState } from "react"
import { IssueStats } from "./issue-stats"
import { Streamdown } from "streamdown"
import { SuggestionChips } from "./suggestion-chips"

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

function SourceCard({ source, index }: { source: JiraIssue; index: number }) {
  const jiraUrl = `https://alldigitalrewards.atlassian.net/browse/${source.issue_id}`

  return (
    <motion.a
      href={jiraUrl}
      target="_blank"
      rel="noopener noreferrer"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="block"
    >
      <Card className="p-3 hover:bg-accent transition-all cursor-pointer group hover:shadow-md hover:-translate-y-0.5">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="outline" className="text-xs font-mono">
                {source.issue_id}
              </Badge>
              <Badge
                variant="secondary"
                className={cn(
                  "text-xs",
                  source.status === "Done" && "bg-green-500/10 text-green-500",
                  source.status === "Closed" && "bg-green-500/10 text-green-500",
                  source.status === "In Progress" && "bg-yellow-500/10 text-yellow-500",
                  source.status === "Backlog" && "bg-gray-500/10 text-gray-500",
                  source.status === "Open" && "bg-red-500/10 text-red-500"
                )}
              >
                {source.status}
              </Badge>
            </div>
            <p className="text-sm font-medium truncate">{source.summary}</p>
            {source.assignee && (
              <p className="text-xs text-muted-foreground mt-1">
                Assigned to {source.assignee}
              </p>
            )}
          </div>
          <ExternalLink className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
        </div>
      </Card>
    </motion.a>
  )
}

function ToolInvocation({ toolName, input, output, state, index }: {
  toolName: string
  input?: { query?: string; jql?: string; limit?: number; epicKey?: string; issueKey?: string }
  output?: { issues?: JiraIssue[]; count?: number; error?: string; suggestion?: string }
  state?: string
  index: number
}) {
  const [expanded, setExpanded] = useState(true)
  const isComplete = state === "output-available" && output !== undefined
  const issues = output?.issues || []
  const hasError = !!output?.error
  const hasMany = issues.length > 4

  // Extract query/jql from input
  const queryText = input?.query
  const jqlText = input?.jql
  const epicKey = input?.epicKey
  const issueKey = input?.issueKey

  // Tool display configuration
  const toolConfig: Record<string, { icon: typeof Search; label: string; color: string; description: string }> = {
    semantic_search: {
      icon: Search,
      label: "Semantic Search",
      color: "text-blue-500",
      description: queryText ? `"${queryText}"` : "searching...",
    },
    jql_search: {
      icon: Database,
      label: "JQL Search",
      color: "text-purple-500",
      description: jqlText || "querying...",
    },
    get_epic_children: {
      icon: GitBranch,
      label: "Epic Children",
      color: "text-green-500",
      description: epicKey ? `Fetching children of ${epicKey}` : "loading...",
    },
    get_linked_issues: {
      icon: Link2,
      label: "Linked Issues",
      color: "text-orange-500",
      description: issueKey ? `Getting links for ${issueKey}` : "loading...",
    },
  }

  const config = toolConfig[toolName] || {
    icon: Search,
    label: toolName,
    color: "text-muted-foreground",
    description: "processing...",
  }
  const Icon = config.icon

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.1 }}
      className="my-3 border rounded-xl overflow-hidden shadow-sm"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "w-full flex items-center gap-2 px-4 py-3 text-sm transition-colors",
          isComplete ? "bg-muted/30 hover:bg-muted/50" : "bg-muted animate-pulse"
        )}
      >
        <Icon className={cn("w-4 h-4", config.color)} />
        <span className="font-medium">{config.label}</span>
        <span className="text-muted-foreground truncate flex-1 text-left">
          {config.description}
        </span>
        {isComplete && (
          <>
            {hasError ? (
              <Badge variant="destructive" className="text-xs">
                Error
              </Badge>
            ) : (
              <Badge variant="secondary" className="text-xs">
                {issues.length} results
              </Badge>
            )}
            {(hasMany || hasError) && (
              expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />
            )}
          </>
        )}
      </button>

      <AnimatePresence>
        {isComplete && expanded && (hasError || issues.length > 0) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t bg-background"
          >
            {/* Error state */}
            {hasError && (
              <div className="px-4 py-3 flex items-start gap-3 bg-destructive/5">
                <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-destructive">{output?.error}</p>
                  {output?.suggestion && (
                    <p className="text-xs text-muted-foreground mt-1">{output.suggestion}</p>
                  )}
                </div>
              </div>
            )}

            {/* Stats visualization */}
            {!hasError && issues.length >= 3 && (
              <div className="px-4 pt-4">
                <IssueStats issues={issues} />
              </div>
            )}

            {/* Issue cards */}
            {!hasError && issues.length > 0 && (
              <div className="px-4 py-3">
                <div className="grid gap-2 sm:grid-cols-2">
                  {issues.slice(0, expanded ? 6 : 4).map((issue, i) => (
                    <SourceCard key={issue.issue_id} source={issue} index={i} />
                  ))}
                </div>
                {issues.length > 6 && (
                  <p className="text-xs text-muted-foreground mt-3 text-center">
                    +{issues.length - 6} more results
                  </p>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export function ChatMessage({ message, onSendMessage }: ChatMessageProps) {
  const isUser = message.role === "user"
  const parts = message.parts || []

  // Extract tool invocations (type starts with "tool-") and text parts
  const toolParts = parts.filter((p) => p.type.startsWith('tool-')).map(p => ({
    ...p,
    toolName: p.type.replace('tool-', ''),
  }))
  const textParts = parts.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
  const textContent = textParts.map(p => p.text).join('')

  // Extract data-suggestions parts
  const suggestionParts = parts.filter((p): p is { type: 'data-suggestions'; data: { prompts: string[] } } =>
    p.type === 'data-suggestions'
  )

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
        {/* Tool invocations (intermediate steps) */}
        {toolParts.length > 0 && (
          <div className="space-y-2">
            {toolParts.map((tool, index) => (
              <ToolInvocation
                key={`${tool.toolName}-${index}`}
                toolName={tool.toolName}
                input={(tool as unknown as { input?: { query?: string; jql?: string; limit?: number } }).input}
                output={(tool as unknown as { output?: { issues?: JiraIssue[]; count?: number } }).output}
                state={(tool as unknown as { state?: string }).state}
                index={index}
              />
            ))}
          </div>
        )}

        {/* Message content */}
        {textContent && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
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
