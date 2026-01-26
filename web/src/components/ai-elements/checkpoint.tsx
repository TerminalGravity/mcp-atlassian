"use client"

import * as React from "react"
import { memo } from "react"
import { Bookmark, RotateCcw, GitBranch } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// Separator component for checkpoint display
const Separator = memo(function Separator({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("h-px flex-1 bg-border", className)}
      {...props}
    />
  )
})
Separator.displayName = "Separator"

// Main Checkpoint container
export type CheckpointProps = React.ComponentProps<"div">

export const Checkpoint = memo(function Checkpoint({
  className,
  children,
  ...props
}: CheckpointProps) {
  return (
    <div
      data-slot="checkpoint"
      className={cn(
        "flex items-center gap-2 overflow-hidden text-muted-foreground my-4",
        className
      )}
      {...props}
    >
      <Separator />
      {children}
      <Separator />
    </div>
  )
})
Checkpoint.displayName = "Checkpoint"

// Checkpoint icon
export type CheckpointIconProps = React.ComponentProps<"span">

export const CheckpointIcon = memo(function CheckpointIcon({
  className,
  children,
  ...props
}: CheckpointIconProps) {
  return (
    <span
      data-slot="checkpoint-icon"
      className={cn("shrink-0", className)}
      {...props}
    >
      {children ?? <Bookmark className="size-4" />}
    </span>
  )
})
CheckpointIcon.displayName = "CheckpointIcon"

// Checkpoint label
export type CheckpointLabelProps = React.ComponentProps<"span">

export const CheckpointLabel = memo(function CheckpointLabel({
  className,
  children,
  ...props
}: CheckpointLabelProps) {
  return (
    <span
      data-slot="checkpoint-label"
      className={cn("text-xs font-medium shrink-0", className)}
      {...props}
    >
      {children}
    </span>
  )
})
CheckpointLabel.displayName = "CheckpointLabel"

// Checkpoint trigger button with optional tooltip
export type CheckpointTriggerProps = React.ComponentProps<typeof Button> & {
  tooltip?: string
}

export const CheckpointTrigger = memo(function CheckpointTrigger({
  className,
  tooltip,
  children,
  variant = "ghost",
  size = "sm",
  ...props
}: CheckpointTriggerProps) {
  const button = (
    <Button
      data-slot="checkpoint-trigger"
      variant={variant}
      size={size}
      className={cn("h-6 px-2 text-xs", className)}
      {...props}
    >
      {children}
    </Button>
  )

  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent side="bottom" align="start">
            {tooltip}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    )
  }

  return button
})
CheckpointTrigger.displayName = "CheckpointTrigger"

// Checkpoint actions container
export type CheckpointActionsProps = React.ComponentProps<"div">

export const CheckpointActions = memo(function CheckpointActions({
  className,
  children,
  ...props
}: CheckpointActionsProps) {
  return (
    <div
      data-slot="checkpoint-actions"
      className={cn("flex items-center gap-1 shrink-0", className)}
      {...props}
    >
      {children}
    </div>
  )
})
CheckpointActions.displayName = "CheckpointActions"

// Checkpoint timestamp
export type CheckpointTimestampProps = React.ComponentProps<"time"> & {
  date: Date | string
}

export const CheckpointTimestamp = memo(function CheckpointTimestamp({
  className,
  date,
  ...props
}: CheckpointTimestampProps) {
  const dateObj = typeof date === "string" ? new Date(date) : date
  const formatted = dateObj.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })

  return (
    <time
      data-slot="checkpoint-timestamp"
      dateTime={dateObj.toISOString()}
      className={cn("text-[10px] text-muted-foreground/70 shrink-0", className)}
      {...props}
    >
      {formatted}
    </time>
  )
})
CheckpointTimestamp.displayName = "CheckpointTimestamp"

// Convenience component for a complete checkpoint marker
export type CheckpointMarkerProps = {
  label?: string
  timestamp?: Date | string
  onRestore?: () => void
  onBranch?: () => void
  className?: string
}

export const CheckpointMarker = memo(function CheckpointMarker({
  label = "Checkpoint",
  timestamp,
  onRestore,
  onBranch,
  className,
}: CheckpointMarkerProps) {
  return (
    <Checkpoint className={className}>
      <CheckpointIcon />
      <CheckpointLabel>{label}</CheckpointLabel>
      {timestamp && <CheckpointTimestamp date={timestamp} />}
      {(onRestore || onBranch) && (
        <CheckpointActions>
          {onRestore && (
            <CheckpointTrigger onClick={onRestore} tooltip="Restore to this point">
              <RotateCcw className="size-3 mr-1" />
              Restore
            </CheckpointTrigger>
          )}
          {onBranch && (
            <CheckpointTrigger onClick={onBranch} tooltip="Branch from this point">
              <GitBranch className="size-3 mr-1" />
              Branch
            </CheckpointTrigger>
          )}
        </CheckpointActions>
      )}
    </Checkpoint>
  )
})
CheckpointMarker.displayName = "CheckpointMarker"

// Auto-save checkpoint indicator
export type AutoCheckpointProps = {
  timestamp?: Date | string
  className?: string
}

export const AutoCheckpoint = memo(function AutoCheckpoint({
  timestamp,
  className,
}: AutoCheckpointProps) {
  return (
    <Checkpoint className={cn("opacity-60", className)}>
      <CheckpointIcon>
        <Bookmark className="size-3" />
      </CheckpointIcon>
      <span className="text-[10px]">Auto-saved</span>
      {timestamp && <CheckpointTimestamp date={timestamp} />}
    </Checkpoint>
  )
})
AutoCheckpoint.displayName = "AutoCheckpoint"
