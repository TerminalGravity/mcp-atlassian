"use client"

import * as React from "react"
import { memo, createContext, useContext, useState } from "react"
import { ExternalLink, ChevronLeft, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"

// Types for Jira issue citations
export interface CitationSource {
  id: string
  issueKey: string
  summary: string
  status?: string
  url?: string
  quote?: string
  description?: string
}

// Context for carousel state
const CarouselContext = createContext<{
  current: number
  total: number
  prev: () => void
  next: () => void
} | null>(null)

function useCarousel() {
  const context = useContext(CarouselContext)
  if (!context) {
    throw new Error("useCarousel must be used within InlineCitationCarousel")
  }
  return context
}

// Main container that groups citation with hover effects
export type InlineCitationProps = React.ComponentProps<"span">

export const InlineCitation = memo(function InlineCitation({
  className,
  children,
  ...props
}: InlineCitationProps) {
  return (
    <span
      data-slot="inline-citation"
      className={cn("group/citation inline", className)}
      {...props}
    >
      {children}
    </span>
  )
})
InlineCitation.displayName = "InlineCitation"

// Text span that highlights on hover
export type InlineCitationTextProps = React.ComponentProps<"span">

export const InlineCitationText = memo(function InlineCitationText({
  className,
  children,
  ...props
}: InlineCitationTextProps) {
  return (
    <span
      data-slot="inline-citation-text"
      className={cn(
        "rounded px-0.5 transition-colors group-hover/citation:bg-accent",
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
})
InlineCitationText.displayName = "InlineCitationText"

// HoverCard wrapper for the citation
export type InlineCitationCardProps = React.ComponentProps<typeof HoverCard>

export const InlineCitationCard = memo(function InlineCitationCard({
  children,
  ...props
}: InlineCitationCardProps) {
  return (
    <HoverCard openDelay={200} closeDelay={100} {...props}>
      {children}
    </HoverCard>
  )
})
InlineCitationCard.displayName = "InlineCitationCard"

// Badge trigger showing citation number and source info
export type InlineCitationCardTriggerProps = React.ComponentProps<
  typeof HoverCardTrigger
> & {
  index: number
  sources: CitationSource[]
}

export const InlineCitationCardTrigger = memo(
  function InlineCitationCardTrigger({
    className,
    index,
    sources,
    ...props
  }: InlineCitationCardTriggerProps) {
    const additionalCount = sources.length - 1
    const primarySource = sources[0]

    // Extract domain from URL if available
    const getDomain = (url?: string) => {
      if (!url) return null
      try {
        return new URL(url).hostname.replace("www.", "")
      } catch {
        return null
      }
    }

    return (
      <HoverCardTrigger asChild {...props}>
        <button
          className={cn(
            "inline-flex items-center gap-0.5 text-xs font-medium text-blue-600 dark:text-blue-400",
            "hover:text-blue-700 dark:hover:text-blue-300 transition-colors cursor-pointer",
            className
          )}
        >
          <Badge
            variant="secondary"
            className="text-[10px] px-1 py-0 h-4 font-mono bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-900/50"
          >
            {index}
          </Badge>
          {getDomain(primarySource?.url) && (
            <span className="text-[10px] text-muted-foreground truncate max-w-[100px]">
              {getDomain(primarySource.url)}
            </span>
          )}
          {additionalCount > 0 && (
            <span className="text-[10px] text-muted-foreground">
              +{additionalCount}
            </span>
          )}
        </button>
      </HoverCardTrigger>
    )
  }
)
InlineCitationCardTrigger.displayName = "InlineCitationCardTrigger"

// Body container for carousel and citation details
export type InlineCitationCardBodyProps = React.ComponentProps<
  typeof HoverCardContent
>

export const InlineCitationCardBody = memo(function InlineCitationCardBody({
  className,
  children,
  ...props
}: InlineCitationCardBodyProps) {
  return (
    <HoverCardContent
      align="start"
      className={cn("w-80 p-0", className)}
      {...props}
    >
      {children}
    </HoverCardContent>
  )
})
InlineCitationCardBody.displayName = "InlineCitationCardBody"

// Carousel wrapper managing state
export type InlineCitationCarouselProps = React.ComponentProps<"div"> & {
  sources: CitationSource[]
}

export const InlineCitationCarousel = memo(function InlineCitationCarousel({
  className,
  sources,
  children,
  ...props
}: InlineCitationCarouselProps) {
  const [current, setCurrent] = useState(0)
  const total = sources.length

  const prev = () => setCurrent((c) => (c === 0 ? total - 1 : c - 1))
  const next = () => setCurrent((c) => (c === total - 1 ? 0 : c + 1))

  return (
    <CarouselContext.Provider value={{ current, total, prev, next }}>
      <div data-slot="citation-carousel" className={cn(className)} {...props}>
        {children}
      </div>
    </CarouselContext.Provider>
  )
})
InlineCitationCarousel.displayName = "InlineCitationCarousel"

// Carousel content container
export type InlineCitationCarouselContentProps = React.ComponentProps<"div"> & {
  sources: CitationSource[]
}

export const InlineCitationCarouselContent = memo(
  function InlineCitationCarouselContent({
    className,
    sources,
    ...props
  }: InlineCitationCarouselContentProps) {
    const { current } = useCarousel()

    return (
      <div
        data-slot="citation-carousel-content"
        className={cn("overflow-hidden", className)}
        {...props}
      >
        <div
          className="flex transition-transform duration-200 ease-in-out"
          style={{ transform: `translateX(-${current * 100}%)` }}
        >
          {sources.map((source, index) => (
            <InlineCitationCarouselItem key={source.id || index}>
              <InlineCitationSource source={source} />
              {source.quote && (
                <InlineCitationQuote>{source.quote}</InlineCitationQuote>
              )}
            </InlineCitationCarouselItem>
          ))}
        </div>
      </div>
    )
  }
)
InlineCitationCarouselContent.displayName = "InlineCitationCarouselContent"

// Individual carousel item
export type InlineCitationCarouselItemProps = React.ComponentProps<"div">

export const InlineCitationCarouselItem = memo(
  function InlineCitationCarouselItem({
    className,
    children,
    ...props
  }: InlineCitationCarouselItemProps) {
    return (
      <div
        data-slot="citation-carousel-item"
        className={cn("w-full flex-none space-y-2 p-4", className)}
        {...props}
      >
        {children}
      </div>
    )
  }
)
InlineCitationCarouselItem.displayName = "InlineCitationCarouselItem"

// Header with navigation controls
export type InlineCitationCarouselHeaderProps = React.ComponentProps<"div">

export const InlineCitationCarouselHeader = memo(
  function InlineCitationCarouselHeader({
    className,
    children,
    ...props
  }: InlineCitationCarouselHeaderProps) {
    return (
      <div
        data-slot="citation-carousel-header"
        className={cn(
          "flex items-center justify-between bg-secondary/50 px-4 py-2",
          className
        )}
        {...props}
      >
        {children}
      </div>
    )
  }
)
InlineCitationCarouselHeader.displayName = "InlineCitationCarouselHeader"

// Index display (e.g., "1/3")
export const InlineCitationCarouselIndex = memo(
  function InlineCitationCarouselIndex({
    className,
    ...props
  }: React.ComponentProps<"span">) {
    const { current, total } = useCarousel()

    if (total <= 1) return null

    return (
      <span
        data-slot="citation-carousel-index"
        className={cn("text-xs text-muted-foreground", className)}
        {...props}
      >
        {current + 1}/{total}
      </span>
    )
  }
)
InlineCitationCarouselIndex.displayName = "InlineCitationCarouselIndex"

// Previous button
export const InlineCitationCarouselPrev = memo(
  function InlineCitationCarouselPrev({
    className,
    ...props
  }: React.ComponentProps<"button">) {
    const { prev, total } = useCarousel()

    if (total <= 1) return null

    return (
      <button
        data-slot="citation-carousel-prev"
        onClick={prev}
        className={cn(
          "p-1 rounded hover:bg-accent transition-colors",
          className
        )}
        {...props}
      >
        <ChevronLeft className="size-4" />
        <span className="sr-only">Previous citation</span>
      </button>
    )
  }
)
InlineCitationCarouselPrev.displayName = "InlineCitationCarouselPrev"

// Next button
export const InlineCitationCarouselNext = memo(
  function InlineCitationCarouselNext({
    className,
    ...props
  }: React.ComponentProps<"button">) {
    const { next, total } = useCarousel()

    if (total <= 1) return null

    return (
      <button
        data-slot="citation-carousel-next"
        onClick={next}
        className={cn(
          "p-1 rounded hover:bg-accent transition-colors",
          className
        )}
        {...props}
      >
        <ChevronRight className="size-4" />
        <span className="sr-only">Next citation</span>
      </button>
    )
  }
)
InlineCitationCarouselNext.displayName = "InlineCitationCarouselNext"

// Source display component
export type InlineCitationSourceProps = React.ComponentProps<"div"> & {
  source: CitationSource
}

export const InlineCitationSource = memo(function InlineCitationSource({
  className,
  source,
  ...props
}: InlineCitationSourceProps) {
  const url =
    source.url ||
    `https://alldigitalrewards.atlassian.net/browse/${source.issueKey}`

  return (
    <div
      data-slot="citation-source"
      className={cn("space-y-1", className)}
      {...props}
    >
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="group/link flex items-start gap-2"
      >
        <Badge variant="outline" className="text-[10px] font-mono shrink-0">
          {source.issueKey}
        </Badge>
        <span className="text-sm font-medium leading-tight group-hover/link:text-primary transition-colors flex-1">
          {source.summary}
        </span>
        <ExternalLink className="size-3 text-muted-foreground shrink-0 mt-0.5 opacity-0 group-hover/link:opacity-100 transition-opacity" />
      </a>
      {source.status && (
        <Badge
          variant="secondary"
          className={cn(
            "text-[10px]",
            source.status === "Done" && "bg-green-500/10 text-green-600",
            source.status === "Closed" && "bg-green-500/10 text-green-600",
            source.status === "In Progress" &&
              "bg-yellow-500/10 text-yellow-600",
            source.status === "Development in Progress" &&
              "bg-yellow-500/10 text-yellow-600"
          )}
        >
          {source.status}
        </Badge>
      )}
      {source.description && (
        <p className="text-xs text-muted-foreground line-clamp-2">
          {source.description}
        </p>
      )}
    </div>
  )
})
InlineCitationSource.displayName = "InlineCitationSource"

// Quote blockquote styling
export type InlineCitationQuoteProps = React.ComponentProps<"blockquote">

export const InlineCitationQuote = memo(function InlineCitationQuote({
  className,
  children,
  ...props
}: InlineCitationQuoteProps) {
  return (
    <blockquote
      data-slot="citation-quote"
      className={cn(
        "border-l-2 border-muted-foreground/30 pl-3 text-xs text-muted-foreground italic",
        className
      )}
      {...props}
    >
      {children}
    </blockquote>
  )
})
InlineCitationQuote.displayName = "InlineCitationQuote"

// Convenience component for a complete inline citation with hover card
export type CitationBadgeProps = {
  index: number
  sources: CitationSource[]
  text?: string
  className?: string
}

export const CitationBadge = memo(function CitationBadge({
  index,
  sources,
  text,
  className,
}: CitationBadgeProps) {
  return (
    <InlineCitation className={className}>
      {text && <InlineCitationText>{text}</InlineCitationText>}
      <InlineCitationCard>
        <InlineCitationCardTrigger index={index} sources={sources} />
        <InlineCitationCardBody>
          <InlineCitationCarousel sources={sources}>
            <InlineCitationCarouselHeader>
              <span className="text-xs font-medium">Sources</span>
              <div className="flex items-center gap-1">
                <InlineCitationCarouselPrev />
                <InlineCitationCarouselIndex />
                <InlineCitationCarouselNext />
              </div>
            </InlineCitationCarouselHeader>
            <InlineCitationCarouselContent sources={sources} />
          </InlineCitationCarousel>
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  )
})
CitationBadge.displayName = "CitationBadge"
