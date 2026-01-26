"use client"

import * as React from "react"
import { memo, createContext, useContext } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"

// Context for streaming state
const PlanContext = createContext<{ isStreaming: boolean }>({ isStreaming: false })

function usePlan() {
  return useContext(PlanContext)
}

// Shimmer effect for loading states
const Shimmer = memo(function Shimmer({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block animate-pulse bg-muted-foreground/20 rounded",
        className
      )}
    />
  )
})
Shimmer.displayName = "Shimmer"

// Main Plan container with streaming state
export type PlanProps = React.ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean
}

export const Plan = memo(function Plan({
  className,
  isStreaming = false,
  defaultOpen = true,
  children,
  ...props
}: PlanProps) {
  return (
    <PlanContext.Provider value={{ isStreaming }}>
      <Collapsible
        data-slot="plan"
        defaultOpen={defaultOpen}
        className={cn(
          "rounded-lg border bg-card text-card-foreground shadow-sm",
          className
        )}
        {...props}
      >
        {children}
      </Collapsible>
    </PlanContext.Provider>
  )
})
Plan.displayName = "Plan"

// Header container
export type PlanHeaderProps = React.ComponentProps<"div">

export const PlanHeader = memo(function PlanHeader({
  className,
  children,
  ...props
}: PlanHeaderProps) {
  return (
    <div
      data-slot="plan-header"
      className={cn("flex items-start gap-3 p-4", className)}
      {...props}
    >
      {children}
    </div>
  )
})
PlanHeader.displayName = "PlanHeader"

// Title with optional shimmer during streaming
export type PlanTitleProps = React.ComponentProps<"h3">

export const PlanTitle = memo(function PlanTitle({
  className,
  children,
  ...props
}: PlanTitleProps) {
  const { isStreaming } = usePlan()

  return (
    <h3
      data-slot="plan-title"
      className={cn("text-sm font-semibold leading-tight", className)}
      {...props}
    >
      {isStreaming && !children ? (
        <Shimmer className="h-4 w-32" />
      ) : (
        children
      )}
    </h3>
  )
})
PlanTitle.displayName = "PlanTitle"

// Description with text-balance and streaming support
export type PlanDescriptionProps = React.ComponentProps<"p">

export const PlanDescription = memo(function PlanDescription({
  className,
  children,
  ...props
}: PlanDescriptionProps) {
  const { isStreaming } = usePlan()

  return (
    <p
      data-slot="plan-description"
      className={cn(
        "text-sm text-muted-foreground text-balance",
        className
      )}
      {...props}
    >
      {isStreaming && !children ? (
        <>
          <Shimmer className="h-3 w-full block mb-1" />
          <Shimmer className="h-3 w-3/4 block" />
        </>
      ) : (
        children
      )}
    </p>
  )
})
PlanDescription.displayName = "PlanDescription"

// Collapsible content area
export type PlanContentProps = React.ComponentProps<typeof CollapsibleContent>

export const PlanContent = memo(function PlanContent({
  className,
  children,
  ...props
}: PlanContentProps) {
  return (
    <CollapsibleContent
      data-slot="plan-content"
      className={cn(
        "overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        className
      )}
      {...props}
    >
      <div className="px-4 pb-4">{children}</div>
    </CollapsibleContent>
  )
})
PlanContent.displayName = "PlanContent"

// Footer container
export type PlanFooterProps = React.ComponentProps<"div">

export const PlanFooter = memo(function PlanFooter({
  className,
  children,
  ...props
}: PlanFooterProps) {
  return (
    <div
      data-slot="plan-footer"
      className={cn(
        "flex items-center gap-2 border-t px-4 py-3 bg-muted/30",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
})
PlanFooter.displayName = "PlanFooter"

// Trigger button with chevron
export type PlanTriggerProps = React.ComponentProps<typeof CollapsibleTrigger>

export const PlanTrigger = memo(function PlanTrigger({
  className,
  children,
  ...props
}: PlanTriggerProps) {
  return (
    <CollapsibleTrigger
      data-slot="plan-trigger"
      className={cn(
        "ml-auto p-1 rounded hover:bg-accent transition-colors shrink-0",
        "data-[state=open]:rotate-180 transition-transform duration-200",
        className
      )}
      {...props}
    >
      {children ?? <ChevronDown className="size-4 text-muted-foreground" />}
      <span className="sr-only">Toggle plan details</span>
    </CollapsibleTrigger>
  )
})
PlanTrigger.displayName = "PlanTrigger"

// Action slot for auxiliary content
export type PlanActionProps = React.ComponentProps<"div">

export const PlanAction = memo(function PlanAction({
  className,
  children,
  ...props
}: PlanActionProps) {
  return (
    <div
      data-slot="plan-action"
      className={cn("shrink-0", className)}
      {...props}
    >
      {children}
    </div>
  )
})
PlanAction.displayName = "PlanAction"

// Plan step item for listing planned actions
export type PlanStepProps = React.ComponentProps<"div"> & {
  icon?: React.ReactNode
  status?: "pending" | "active" | "complete"
}

export const PlanStep = memo(function PlanStep({
  className,
  icon,
  status = "pending",
  children,
  ...props
}: PlanStepProps) {
  return (
    <div
      data-slot="plan-step"
      data-status={status}
      className={cn(
        "flex items-start gap-3 py-2",
        status === "complete" && "text-muted-foreground",
        className
      )}
      {...props}
    >
      {icon && (
        <span
          className={cn(
            "mt-0.5 shrink-0",
            status === "active" && "text-primary",
            status === "complete" && "text-green-500"
          )}
        >
          {icon}
        </span>
      )}
      <div className="flex-1 text-sm">{children}</div>
    </div>
  )
})
PlanStep.displayName = "PlanStep"

// Convenience component for a complete plan card
export type PlanCardProps = {
  title: string
  description?: string
  steps?: Array<{
    id: string
    label: string
    icon?: React.ReactNode
    status?: "pending" | "active" | "complete"
  }>
  isStreaming?: boolean
  className?: string
  footer?: React.ReactNode
}

export const PlanCard = memo(function PlanCard({
  title,
  description,
  steps,
  isStreaming = false,
  className,
  footer,
}: PlanCardProps) {
  return (
    <Plan isStreaming={isStreaming} className={className}>
      <PlanHeader>
        <div className="flex-1 space-y-1">
          <PlanTitle>{title}</PlanTitle>
          {description && <PlanDescription>{description}</PlanDescription>}
        </div>
        <PlanTrigger />
      </PlanHeader>
      {steps && steps.length > 0 && (
        <PlanContent>
          <div className="space-y-1 border-l-2 border-muted pl-4">
            {steps.map((step) => (
              <PlanStep key={step.id} icon={step.icon} status={step.status}>
                {step.label}
              </PlanStep>
            ))}
          </div>
        </PlanContent>
      )}
      {footer && <PlanFooter>{footer}</PlanFooter>}
    </Plan>
  )
})
PlanCard.displayName = "PlanCard"
