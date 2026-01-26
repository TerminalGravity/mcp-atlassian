"use client"

import * as React from "react"
import { memo, createContext, useContext } from "react"
import { Brain, ChevronDown, Check, Loader2, Circle } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"

// Step status types
export type StepStatus = "pending" | "active" | "complete"

// Context for open state management
const ChainOfThoughtContext = createContext<{
  open: boolean
  onOpenChange: (open: boolean) => void
}>({
  open: false,
  onOpenChange: () => {},
})

function useChainOfThought() {
  return useContext(ChainOfThoughtContext)
}

// Main container with collapsible state
export type ChainOfThoughtProps = React.ComponentProps<typeof Collapsible>

export const ChainOfThought = memo(function ChainOfThought({
  className,
  defaultOpen = false,
  open,
  onOpenChange,
  children,
  ...props
}: ChainOfThoughtProps) {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen)
  const isOpen = open ?? internalOpen
  const setOpen = onOpenChange ?? setInternalOpen

  return (
    <ChainOfThoughtContext.Provider value={{ open: isOpen, onOpenChange: setOpen }}>
      <Collapsible
        data-slot="chain-of-thought"
        open={isOpen}
        onOpenChange={setOpen}
        className={cn("my-2", className)}
        {...props}
      >
        {children}
      </Collapsible>
    </ChainOfThoughtContext.Provider>
  )
})
ChainOfThought.displayName = "ChainOfThought"

// Header trigger with brain icon and chevron
export type ChainOfThoughtHeaderProps = React.ComponentProps<
  typeof CollapsibleTrigger
> & {
  isStreaming?: boolean
  stepCount?: number
}

export const ChainOfThoughtHeader = memo(function ChainOfThoughtHeader({
  className,
  isStreaming,
  stepCount,
  children,
  ...props
}: ChainOfThoughtHeaderProps) {
  const { open } = useChainOfThought()

  return (
    <CollapsibleTrigger
      data-slot="chain-of-thought-header"
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors w-full",
        "text-muted-foreground hover:text-foreground hover:bg-muted/50",
        open && "bg-muted/30",
        className
      )}
      {...props}
    >
      {children ?? (
        <>
          {isStreaming ? (
            <Loader2 className="size-3.5 animate-spin text-purple-500" />
          ) : (
            <Brain className="size-3.5 text-purple-500" />
          )}
          <span className="font-medium flex-1 text-left">
            {isStreaming ? "Thinking..." : "View thinking process"}
          </span>
          {stepCount && stepCount > 0 && (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {stepCount} steps
            </Badge>
          )}
          <ChevronDown
            className={cn(
              "size-3 transition-transform duration-200",
              open && "rotate-180"
            )}
          />
        </>
      )}
    </CollapsibleTrigger>
  )
})
ChainOfThoughtHeader.displayName = "ChainOfThoughtHeader"

// Collapsible content with animation
export type ChainOfThoughtContentProps = React.ComponentProps<
  typeof CollapsibleContent
>

export const ChainOfThoughtContent = memo(function ChainOfThoughtContent({
  className,
  children,
  ...props
}: ChainOfThoughtContentProps) {
  return (
    <CollapsibleContent
      data-slot="chain-of-thought-content"
      className={cn(
        "data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        "overflow-hidden",
        className
      )}
      {...props}
    >
      <div className="mt-2 px-3 py-3 bg-muted/20 rounded-lg border border-border/50">
        {children}
      </div>
    </CollapsibleContent>
  )
})
ChainOfThoughtContent.displayName = "ChainOfThoughtContent"

// Helper to render step status icon
function renderStepStatusIcon(status: StepStatus, icon?: React.ReactNode) {
  if (icon) return <span className="shrink-0">{icon}</span>

  switch (status) {
    case "active":
      return <Loader2 className="size-3.5 animate-spin text-primary shrink-0" />
    case "complete":
      return <Check className="size-3.5 text-green-500 shrink-0" />
    default:
      return <Circle className="size-3.5 text-muted-foreground/50 shrink-0" />
  }
}

// Individual thinking step
export type ChainOfThoughtStepProps = React.ComponentProps<"div"> & {
  icon?: React.ReactNode
  label: string
  description?: string
  status?: StepStatus
}

export const ChainOfThoughtStep = memo(function ChainOfThoughtStep({
  className,
  icon,
  label,
  description,
  status = "pending",
  ...props
}: ChainOfThoughtStepProps) {
  return (
    <div
      data-slot="chain-of-thought-step"
      data-status={status}
      className={cn(
        "flex items-start gap-2 py-1.5",
        status === "pending" && "opacity-60",
        className
      )}
      {...props}
    >
      {renderStepStatusIcon(status, icon)}
      <div className="flex-1 min-w-0">
        <p
          className={cn(
            "text-xs font-medium",
            status === "complete" && "text-muted-foreground"
          )}
        >
          {label}
        </p>
        {description && (
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {description}
          </p>
        )}
      </div>
    </div>
  )
})
ChainOfThoughtStep.displayName = "ChainOfThoughtStep"

// Search results badge display
export type ChainOfThoughtSearchResultsProps = React.ComponentProps<"div">

export const ChainOfThoughtSearchResults = memo(
  function ChainOfThoughtSearchResults({
    className,
    children,
    ...props
  }: ChainOfThoughtSearchResultsProps) {
    return (
      <div
        data-slot="chain-of-thought-search-results"
        className={cn("flex flex-wrap gap-1 mt-2", className)}
        {...props}
      >
        {children}
      </div>
    )
  }
)
ChainOfThoughtSearchResults.displayName = "ChainOfThoughtSearchResults"

// Individual search result badge
export type ChainOfThoughtSearchResultProps = React.ComponentProps<"span"> & {
  href?: string
}

export const ChainOfThoughtSearchResult = memo(
  function ChainOfThoughtSearchResult({
    className,
    href,
    children,
    ...props
  }: ChainOfThoughtSearchResultProps) {
    const content = (
      <span
        className={cn(
          "inline-flex items-center rounded-md border bg-secondary px-1.5 py-0.5 text-xs",
          href && "hover:bg-secondary/80 cursor-pointer",
          className
        )}
        {...props}
      >
        {children}
      </span>
    )

    if (href) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {content}
        </a>
      )
    }

    return content
  }
)
ChainOfThoughtSearchResult.displayName = "ChainOfThoughtSearchResult"

// Image container with optional caption
export type ChainOfThoughtImageProps = React.ComponentProps<"figure"> & {
  src: string
  alt: string
  caption?: string
  width?: number
  height?: number
}

export const ChainOfThoughtImage = memo(function ChainOfThoughtImage({
  className,
  src,
  alt,
  caption,
  width = 400,
  height = 300,
  ...props
}: ChainOfThoughtImageProps) {
  return (
    <figure
      data-slot="chain-of-thought-image"
      className={cn("mt-2", className)}
      {...props}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        width={width}
        height={height}
        className="rounded-md border max-w-full h-auto"
      />
      {caption && (
        <figcaption className="text-xs text-muted-foreground mt-1 text-center">
          {caption}
        </figcaption>
      )}
    </figure>
  )
})
ChainOfThoughtImage.displayName = "ChainOfThoughtImage"

// Convenience component for a complete chain-of-thought display
export type ChainOfThoughtCardProps = {
  steps: Array<{
    id: string
    label: string
    description?: string
    status: StepStatus
    icon?: React.ReactNode
    results?: Array<{ id: string; label: string; href?: string }>
  }>
  isStreaming?: boolean
  defaultOpen?: boolean
  className?: string
}

export const ChainOfThoughtCard = memo(function ChainOfThoughtCard({
  steps,
  isStreaming = false,
  defaultOpen = false,
  className,
}: ChainOfThoughtCardProps) {
  return (
    <ChainOfThought defaultOpen={defaultOpen} className={className}>
      <ChainOfThoughtHeader isStreaming={isStreaming} stepCount={steps.length} />
      <ChainOfThoughtContent>
        <div className="space-y-1">
          {steps.map((step) => (
            <div key={step.id}>
              <ChainOfThoughtStep
                label={step.label}
                description={step.description}
                status={step.status}
                icon={step.icon}
              />
              {step.results && step.results.length > 0 && (
                <ChainOfThoughtSearchResults>
                  {step.results.map((result) => (
                    <ChainOfThoughtSearchResult key={result.id} href={result.href}>
                      {result.label}
                    </ChainOfThoughtSearchResult>
                  ))}
                </ChainOfThoughtSearchResults>
              )}
            </div>
          ))}
        </div>
      </ChainOfThoughtContent>
    </ChainOfThought>
  )
})
ChainOfThoughtCard.displayName = "ChainOfThoughtCard"
