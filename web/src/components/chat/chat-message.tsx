"use client"

import { useCallback } from "react"
import { motion } from "framer-motion"
import { cn } from "@/lib/utils"
import { Avatar } from "@/components/ui/avatar"
import type { UIMessage } from "ai"
import { Bot, User } from "lucide-react"
import { Streamdown } from "streamdown"
import { SuggestionChips } from "./suggestion-chips"
import { Reasoning } from "./reasoning"
import { ResearchSteps } from "./research-steps"
// AI Elements integration - using standardized components
import { ContextJiraCard } from "@/components/ai-elements/context"
import {
  CitationBadge,
  type CitationSource,
} from "@/components/ai-elements/inline-citation"
import {
  RefinementChips,
  type Refinement,
} from "@/components/ai-elements/refinement-chips"

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
  // Timestamps for temporal filtering
  created_at?: string
  updated_at?: string
}

// Parse text for citation references like [1], [2], [1, 2]
// Returns array of { text: string, citations?: number[] } segments
function parseTextForCitations(text: string): Array<{ text: string; citations?: number[] }> {
  const segments: Array<{ text: string; citations?: number[] }> = []
  // Match [n] or [n, m, ...] patterns
  const citationRegex = /\[(\d+(?:\s*,\s*\d+)*)\]/g
  let lastIndex = 0
  let match

  while ((match = citationRegex.exec(text)) !== null) {
    // Add text before citation
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) })
    }
    // Parse citation numbers
    const citations = match[1].split(/\s*,\s*/).map(n => parseInt(n, 10))
    segments.push({ text: '', citations })
    lastIndex = citationRegex.lastIndex
  }

  // Add remaining text
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) })
  }

  return segments
}

// Check if text contains any citation patterns
function hasCitations(text: string): boolean {
  return /\[\d+(?:\s*,\s*\d+)*\]/.test(text)
}

// Build citation sources from issues array
function buildCitationSources(issues: JiraIssue[]): Map<number, CitationSource[]> {
  const sourceMap = new Map<number, CitationSource[]>()
  issues.forEach((issue, index) => {
    const citationNumber = index + 1 // Citations are 1-indexed
    sourceMap.set(citationNumber, [{
      id: issue.issue_id,
      issueKey: issue.issue_id,
      summary: issue.summary,
      status: issue.status,
      description: issue.description_preview || undefined,
    }])
  })
  return sourceMap
}

// Component to render text with inline citations
function TextWithCitations({
  text,
  issues,
  className,
}: {
  text: string
  issues: JiraIssue[]
  className?: string
}) {
  const segments = parseTextForCitations(text)
  const sourceMap = buildCitationSources(issues)

  return (
    <span className={className}>
      {segments.map((segment, i) => {
        if (segment.citations) {
          // Render citation badges
          return segment.citations.map((citationNum, j) => {
            const sources = sourceMap.get(citationNum)
            if (!sources) return <span key={`${i}-${j}`}>[{citationNum}]</span>
            return (
              <CitationBadge
                key={`${i}-${j}`}
                index={citationNum}
                sources={sources}
              />
            )
          })
        }
        return <span key={i}>{segment.text}</span>
      })}
    </span>
  )
}


export function ChatMessage({ message, onSendMessage }: ChatMessageProps) {
  const isUser = message.role === "user"
  const parts = message.parts || []

  // Extract research phases - prefer new data-research-phase format, fall back to old tool-* format
  // Deduplicate by ID, keeping only the latest version (phases are streamed twice: running then complete)
  const researchPhaseMap = new Map<string, {
    id: string
    toolName: string
    input: Record<string, unknown>
    output?: { issues?: JiraIssue[]; count?: number; error?: string }
    state: string
  }>()

  parts.filter((p): p is {
    type: 'data-research-phase'
    id: string
    data: {
      toolName: string
      input: Record<string, unknown>
      output?: { issues?: JiraIssue[]; count?: number; error?: string }
      state: string
    }
  } => p.type === 'data-research-phase').forEach(p => {
    // Later entries (complete state) overwrite earlier ones (running state)
    researchPhaseMap.set(p.id, {
      id: p.id,
      toolName: p.data.toolName,
      input: p.data.input,
      output: p.data.output,
      state: p.data.state,
    })
  })

  const researchPhaseParts = Array.from(researchPhaseMap.values())

  // Only use old tool-* format if no new format parts exist (backwards compatibility)
  const oldToolParts = researchPhaseParts.length === 0
    ? parts.filter((p) => p.type.startsWith('tool-')).map(p => ({
        id: undefined as string | undefined,
        toolName: p.type.replace('tool-', ''),
        input: (p as { input?: unknown }).input as Record<string, unknown> | undefined,
        output: (p as { output?: unknown }).output as { issues?: JiraIssue[]; count?: number; error?: string } | undefined,
        state: (p as { state?: string }).state,
      }))
    : []

  // Use whichever format is present (they're mutually exclusive now)
  const toolParts = researchPhaseParts.length > 0 ? researchPhaseParts : oldToolParts

  const textParts = parts.filter((p): p is { type: 'text'; text: string } => p.type === 'text')
  const textContent = textParts.map(p => p.text).join('')

  // Extract custom data parts
  const suggestionParts = parts.filter((p): p is { type: 'data-suggestions'; data: { prompts: string[] } } =>
    p.type === 'data-suggestions'
  )
  const reasoningParts = parts.filter((p): p is { type: 'data-reasoning'; data: { content: string; duration?: number } } =>
    p.type === 'data-reasoning'
  )
  const refinementParts = parts.filter((p): p is {
    type: 'data-refinements'
    id: string
    data: {
      originalQuery: string
      totalResults: number
      refinements: Refinement[]
    }
  } =>
    p.type === 'data-refinements'
  )

  // Collect all issues from tool outputs for the Sources component
  const allIssues = toolParts
    .flatMap(t => (t.output as { issues?: JiraIssue[] })?.issues || [])
    .filter((issue, index, self) => self.findIndex(i => i.issue_id === issue.issue_id) === index)

  // Handler for refinement selection - constructs a filtered query
  const handleRefinementSelect = useCallback(
    (refinement: Refinement, originalQuery: string) => {
      if (!onSendMessage) return

      // Build a descriptive query that includes the filter context
      const filterDescriptions: Record<string, string> = {
        project: `in ${refinement.filter.value} project`,
        time: `from ${refinement.label.toLowerCase()}`,
        type: `of type ${refinement.filter.value}`,
        priority: `with ${refinement.filter.value} priority`,
        status: `with status ${refinement.filter.value}`,
      }

      const filterContext = filterDescriptions[refinement.category] || refinement.label
      const newQuery = `Show me results ${filterContext}: ${originalQuery}`

      onSendMessage(newQuery)
    },
    [onSendMessage]
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
        {/* Research steps - inline expandable with full issue cards */}
        {!isUser && toolParts.length > 0 && (
          <ResearchSteps
            phases={toolParts}
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
            ) : hasCitations(textContent) && allIssues.length > 0 ? (
              // Render with inline citation support
              <TextWithCitations
                text={textContent}
                issues={allIssues}
                className="whitespace-pre-wrap"
              />
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

        {/* Refinement chips for narrowing search results */}
        {!isUser && refinementParts.length > 0 && refinementParts.map((part, i) => (
          <RefinementChips
            key={`refinements-${part.id || i}`}
            refinements={part.data.refinements}
            onSelect={(refinement) => handleRefinementSelect(refinement, part.data.originalQuery)}
          />
        ))}

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
