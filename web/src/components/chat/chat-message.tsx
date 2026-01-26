"use client"

import { motion } from "framer-motion"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import type { UIMessage } from "ai"
import { Bot, User, Search, Database, GitBranch, Link2 } from "lucide-react"
import { Streamdown } from "streamdown"
import { SuggestionChips } from "./suggestion-chips"
import { Reasoning } from "./reasoning"
// AI Elements integration - using standardized components
import { ContextJiraCard } from "@/components/ai-elements/context"
import {
  ChainOfThoughtCard,
  type StepStatus,
} from "@/components/ai-elements/chain-of-thought"

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

// Tool configuration for display
const toolDisplayConfig: Record<string, { icon: typeof Search; label: string }> = {
  semantic_search: { icon: Search, label: "Semantic Search" },
  jql_search: { icon: Database, label: "JQL Query" },
  get_epic_children: { icon: GitBranch, label: "Epic Children" },
  get_linked_issues: { icon: Link2, label: "Linked Issues" },
}

// Convert tool parts to ChainOfThought steps format
function toolPartsToSteps(toolParts: Array<{
  toolName: string
  input?: { query?: string; jql?: string; epicKey?: string; issueKey?: string }
  output?: { issues?: JiraIssue[]; error?: string }
  state?: string
}>): Array<{
  id: string
  label: string
  description?: string
  status: StepStatus
  icon?: React.ReactNode
  results?: Array<{ id: string; label: string; href?: string }>
}> {
  return toolParts.map((tool, index) => {
    const config = toolDisplayConfig[tool.toolName] || { icon: Search, label: tool.toolName }
    const Icon = config.icon
    const isComplete = tool.state === "output-available"
    const hasError = !!tool.output?.error
    const issues = tool.output?.issues || []

    // Build description from input
    let description = ""
    if (tool.input?.query) {
      description = `"${tool.input.query.slice(0, 50)}${tool.input.query.length > 50 ? '...' : ''}"`
    } else if (tool.input?.jql) {
      description = tool.input.jql.slice(0, 50) + (tool.input.jql.length > 50 ? '...' : '')
    } else if (tool.input?.epicKey) {
      description = tool.input.epicKey
    } else if (tool.input?.issueKey) {
      description = tool.input.issueKey
    }

    // Determine status
    let status: StepStatus = "pending"
    if (isComplete) {
      status = "complete"
    } else if (index === 0 || toolParts[index - 1]?.state === "output-available") {
      status = "active"
    }

    // Build results for complete steps (show issue keys as badges)
    const results = isComplete && !hasError && issues.length > 0
      ? issues.slice(0, 5).map(issue => ({
          id: issue.issue_id,
          label: issue.issue_id,
          href: `https://alldigitalrewards.atlassian.net/browse/${issue.issue_id}`,
        }))
      : undefined

    return {
      id: `${tool.toolName}-${index}`,
      label: hasError ? `${config.label} (Error)` : `${config.label}${issues.length > 0 ? ` - ${issues.length} results` : ''}`,
      description: hasError ? tool.output?.error : description,
      status,
      icon: <Icon className="size-3.5" />,
      results,
    }
  })
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
        {/* Research steps using ChainOfThought ai-element */}
        {!isUser && toolParts.length > 0 && (
          <ChainOfThoughtCard
            steps={toolPartsToSteps(toolParts.map(t => ({
              toolName: t.toolName,
              input: t.input as { query?: string; jql?: string; epicKey?: string; issueKey?: string } | undefined,
              output: t.output as { issues?: JiraIssue[]; error?: string } | undefined,
              state: t.state,
            })))}
            isStreaming={toolParts.some(t => t.state !== "output-available")}
            defaultOpen={false}
          />
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

        {/* Context: Jira issues referenced - using ai-elements component */}
        {!isUser && textContent && allIssues.length > 0 && (
          <ContextJiraCard
            title="Sources referenced"
            issues={allIssues.map(i => ({
              issueKey: i.issue_id,
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
