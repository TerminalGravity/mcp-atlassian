"use client"

import * as React from "react"
import { memo } from "react"
import { Database, FileText, Link2, Server, ExternalLink } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

// Context source types
export type ContextSourceType = "jira" | "database" | "file" | "api" | "link"

// Main Context container
export type ContextProps = React.ComponentProps<"div">

export const Context = memo(function Context({
  className,
  children,
  ...props
}: ContextProps) {
  return (
    <div
      data-slot="context"
      className={cn(
        "rounded-lg border bg-muted/30 p-3 my-3",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
})
Context.displayName = "Context"

// Context header
export type ContextHeaderProps = React.ComponentProps<"div">

export const ContextHeader = memo(function ContextHeader({
  className,
  children,
  ...props
}: ContextHeaderProps) {
  return (
    <div
      data-slot="context-header"
      className={cn("flex items-center gap-2 mb-2", className)}
      {...props}
    >
      <Database className="size-4 text-muted-foreground" />
      <span className="text-xs font-medium text-muted-foreground">
        {children ?? "Context used"}
      </span>
    </div>
  )
})
ContextHeader.displayName = "ContextHeader"

// Context sources list
export type ContextSourcesProps = React.ComponentProps<"div">

export const ContextSources = memo(function ContextSources({
  className,
  children,
  ...props
}: ContextSourcesProps) {
  return (
    <div
      data-slot="context-sources"
      className={cn("space-y-1", className)}
      {...props}
    >
      {children}
    </div>
  )
})
ContextSources.displayName = "ContextSources"

// Individual context source item
export type ContextSourceProps = React.ComponentProps<"div"> & {
  type?: ContextSourceType
  label: string
  description?: string
  href?: string
  count?: number
}

export const ContextSource = memo(function ContextSource({
  className,
  type = "jira",
  label,
  description,
  href,
  count,
  ...props
}: ContextSourceProps) {
  const Icon = {
    jira: FileText,
    database: Database,
    file: FileText,
    api: Server,
    link: Link2,
  }[type]

  const content = (
    <div
      data-slot="context-source"
      data-type={type}
      className={cn(
        "flex items-center gap-2 px-2 py-1.5 rounded text-xs",
        href && "hover:bg-muted/50 cursor-pointer transition-colors group",
        className
      )}
      {...props}
    >
      <Icon className="size-3.5 text-muted-foreground shrink-0" />
      <span className="font-medium truncate">{label}</span>
      {description && (
        <span className="text-muted-foreground truncate flex-1">
          {description}
        </span>
      )}
      {count && count > 1 && (
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
          {count}
        </Badge>
      )}
      {href && (
        <ExternalLink className="size-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      )}
    </div>
  )

  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {content}
      </a>
    )
  }

  return content
})
ContextSource.displayName = "ContextSource"

// Context summary with count
export type ContextSummaryProps = React.ComponentProps<"div"> & {
  totalSources: number
  types?: ContextSourceType[]
}

export const ContextSummary = memo(function ContextSummary({
  className,
  totalSources,
  types = [],
  ...props
}: ContextSummaryProps) {
  const uniqueTypes = [...new Set(types)]

  return (
    <div
      data-slot="context-summary"
      className={cn(
        "flex items-center gap-2 text-xs text-muted-foreground",
        className
      )}
      {...props}
    >
      <span>
        {totalSources} source{totalSources !== 1 ? "s" : ""} used
      </span>
      {uniqueTypes.length > 0 && (
        <div className="flex items-center gap-1">
          {uniqueTypes.map((type) => {
            const Icon = {
              jira: FileText,
              database: Database,
              file: FileText,
              api: Server,
              link: Link2,
            }[type]
            return <Icon key={type} className="size-3" />
          })}
        </div>
      )}
    </div>
  )
})
ContextSummary.displayName = "ContextSummary"

// Jira-specific context source
export type ContextJiraIssueProps = React.ComponentProps<"div"> & {
  issueKey: string
  summary?: string
  status?: string
}

export const ContextJiraIssue = memo(function ContextJiraIssue({
  className,
  issueKey,
  summary,
  status,
  ...props
}: ContextJiraIssueProps) {
  const url = `https://alldigitalrewards.atlassian.net/browse/${issueKey}`

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="block"
    >
      <div
        data-slot="context-jira-issue"
        className={cn(
          "flex items-center gap-2 px-2 py-1.5 rounded text-xs",
          "hover:bg-muted/50 cursor-pointer transition-colors group",
          className
        )}
        {...props}
      >
        <Badge variant="outline" className="text-[10px] font-mono shrink-0">
          {issueKey}
        </Badge>
        {summary && (
          <span className="truncate flex-1 text-muted-foreground group-hover:text-foreground">
            {summary}
          </span>
        )}
        {status && (
          <Badge
            variant="secondary"
            className={cn(
              "text-[9px] shrink-0",
              status === "Done" && "bg-green-500/10 text-green-600",
              status === "Closed" && "bg-green-500/10 text-green-600",
              status === "In Progress" && "bg-yellow-500/10 text-yellow-600"
            )}
          >
            {status}
          </Badge>
        )}
        <ExternalLink className="size-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      </div>
    </a>
  )
})
ContextJiraIssue.displayName = "ContextJiraIssue"

// Convenience component for a complete context display
export type ContextCardProps = {
  title?: string
  sources: Array<{
    id: string
    type: ContextSourceType
    label: string
    description?: string
    href?: string
    count?: number
  }>
  maxVisible?: number
  className?: string
}

export const ContextCard = memo(function ContextCard({
  title = "Context used",
  sources,
  maxVisible = 5,
  className,
}: ContextCardProps) {
  const visibleSources = sources.slice(0, maxVisible)
  const remainingCount = sources.length - maxVisible

  return (
    <Context className={className}>
      <ContextHeader>{title}</ContextHeader>
      <ContextSources>
        {visibleSources.map((source) => (
          <ContextSource
            key={source.id}
            type={source.type}
            label={source.label}
            description={source.description}
            href={source.href}
            count={source.count}
          />
        ))}
        {remainingCount > 0 && (
          <div className="text-xs text-muted-foreground px-2 py-1">
            +{remainingCount} more source{remainingCount !== 1 ? "s" : ""}
          </div>
        )}
      </ContextSources>
    </Context>
  )
})
ContextCard.displayName = "ContextCard"

// Jira-specific context card
export type ContextJiraCardProps = {
  title?: string
  issues: Array<{
    issueKey: string
    summary?: string
    status?: string
  }>
  maxVisible?: number
  className?: string
}

export const ContextJiraCard = memo(function ContextJiraCard({
  title = "Jira issues referenced",
  issues,
  maxVisible = 5,
  className,
}: ContextJiraCardProps) {
  const visibleIssues = issues.slice(0, maxVisible)
  const remainingCount = issues.length - maxVisible

  return (
    <Context className={className}>
      <ContextHeader>{title}</ContextHeader>
      <ContextSources>
        {visibleIssues.map((issue) => (
          <ContextJiraIssue
            key={issue.issueKey}
            issueKey={issue.issueKey}
            summary={issue.summary}
            status={issue.status}
          />
        ))}
        {remainingCount > 0 && (
          <div className="text-xs text-muted-foreground px-2 py-1">
            +{remainingCount} more issue{remainingCount !== 1 ? "s" : ""}
          </div>
        )}
      </ContextSources>
    </Context>
  )
})
ContextJiraCard.displayName = "ContextJiraCard"
