"use client"

import * as React from "react"
import { memo, createContext, useContext } from "react"
import { AlertTriangle, Check, X, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

// Approval state types matching AI SDK ToolUIPart
export type ApprovalState =
  | "approval-requested"
  | "approval-accepted"
  | "approval-rejected"
  | "input-available"
  | "input-streaming"
  | "output-available"
  | "output-streaming"

export type ToolUIPartApproval =
  | undefined
  | { approved: boolean; reason?: string }

// Context for confirmation state
interface ConfirmationContextValue {
  state: ApprovalState
  approval?: ToolUIPartApproval
  onApprove?: (reason?: string) => void
  onReject?: (reason?: string) => void
}

const ConfirmationContext = createContext<ConfirmationContextValue>({
  state: "approval-requested",
})

function useConfirmation() {
  return useContext(ConfirmationContext)
}

// Main Confirmation container
export type ConfirmationProps = React.ComponentProps<"div"> & {
  state: ApprovalState
  approval?: ToolUIPartApproval
  onApprove?: (reason?: string) => void
  onReject?: (reason?: string) => void
}

export const Confirmation = memo(function Confirmation({
  className,
  state,
  approval,
  onApprove,
  onReject,
  children,
  ...props
}: ConfirmationProps) {
  // Don't render if input is streaming or available
  if (state === "input-streaming" || state === "input-available") {
    return null
  }

  // Don't render if no approval provided and not requesting
  if (!approval && state !== "approval-requested") {
    return null
  }

  return (
    <ConfirmationContext.Provider value={{ state, approval, onApprove, onReject }}>
      <div
        data-slot="confirmation"
        data-state={state}
        className={cn(
          "rounded-lg border p-4 my-3",
          state === "approval-requested" && "border-yellow-500/50 bg-yellow-500/5",
          state === "approval-accepted" && "border-green-500/50 bg-green-500/5",
          state === "approval-rejected" && "border-red-500/50 bg-red-500/5",
          className
        )}
        {...props}
      >
        {children}
      </div>
    </ConfirmationContext.Provider>
  )
})
Confirmation.displayName = "Confirmation"

// Confirmation header with icon
export type ConfirmationHeaderProps = React.ComponentProps<"div"> & {
  icon?: React.ReactNode
}

export const ConfirmationHeader = memo(function ConfirmationHeader({
  className,
  icon,
  children,
  ...props
}: ConfirmationHeaderProps) {
  const { state } = useConfirmation()

  const defaultIcon = () => {
    switch (state) {
      case "approval-accepted":
        return <Check className="size-5 text-green-500" />
      case "approval-rejected":
        return <X className="size-5 text-red-500" />
      default:
        return <AlertTriangle className="size-5 text-yellow-500" />
    }
  }

  return (
    <div
      data-slot="confirmation-header"
      className={cn("flex items-start gap-3", className)}
      {...props}
    >
      <span className="shrink-0 mt-0.5">{icon ?? defaultIcon()}</span>
      <div className="flex-1">{children}</div>
    </div>
  )
})
ConfirmationHeader.displayName = "ConfirmationHeader"

// Confirmation title
export type ConfirmationTitleProps = React.ComponentProps<"h4">

export const ConfirmationTitle = memo(function ConfirmationTitle({
  className,
  children,
  ...props
}: ConfirmationTitleProps) {
  return (
    <h4
      data-slot="confirmation-title"
      className={cn("text-sm font-semibold", className)}
      {...props}
    >
      {children}
    </h4>
  )
})
ConfirmationTitle.displayName = "ConfirmationTitle"

// Confirmation description
export type ConfirmationDescriptionProps = React.ComponentProps<"p">

export const ConfirmationDescription = memo(function ConfirmationDescription({
  className,
  children,
  ...props
}: ConfirmationDescriptionProps) {
  return (
    <p
      data-slot="confirmation-description"
      className={cn("text-sm text-muted-foreground mt-1", className)}
      {...props}
    >
      {children}
    </p>
  )
})
ConfirmationDescription.displayName = "ConfirmationDescription"

// Content only shown during approval-requested state
export type ConfirmationRequestProps = React.ComponentProps<"div">

export const ConfirmationRequest = memo(function ConfirmationRequest({
  className,
  children,
  ...props
}: ConfirmationRequestProps) {
  const { state } = useConfirmation()

  if (state !== "approval-requested") return null

  return (
    <div
      data-slot="confirmation-request"
      className={cn(className)}
      {...props}
    >
      {children}
    </div>
  )
})
ConfirmationRequest.displayName = "ConfirmationRequest"

// Content only shown when approval is accepted
export type ConfirmationAcceptedProps = React.ComponentProps<"div">

export const ConfirmationAccepted = memo(function ConfirmationAccepted({
  className,
  children,
  ...props
}: ConfirmationAcceptedProps) {
  const { state, approval } = useConfirmation()

  if (state !== "approval-accepted" && state !== "output-available" && state !== "output-streaming") {
    return null
  }
  if (!approval?.approved) return null

  return (
    <div
      data-slot="confirmation-accepted"
      className={cn(className)}
      {...props}
    >
      {children}
    </div>
  )
})
ConfirmationAccepted.displayName = "ConfirmationAccepted"

// Content only shown when approval is rejected
export type ConfirmationRejectedProps = React.ComponentProps<"div">

export const ConfirmationRejected = memo(function ConfirmationRejected({
  className,
  children,
  ...props
}: ConfirmationRejectedProps) {
  const { state, approval } = useConfirmation()

  if (state !== "approval-rejected" && state !== "output-available" && state !== "output-streaming") {
    return null
  }
  if (approval?.approved !== false) return null

  return (
    <div
      data-slot="confirmation-rejected"
      className={cn(className)}
      {...props}
    >
      {children}
    </div>
  )
})
ConfirmationRejected.displayName = "ConfirmationRejected"

// Actions container (visible during approval request)
export type ConfirmationActionsProps = React.ComponentProps<"div">

export const ConfirmationActions = memo(function ConfirmationActions({
  className,
  children,
  ...props
}: ConfirmationActionsProps) {
  const { state } = useConfirmation()

  if (state !== "approval-requested") return null

  return (
    <div
      data-slot="confirmation-actions"
      className={cn("flex items-center gap-2 mt-4", className)}
      {...props}
    >
      {children}
    </div>
  )
})
ConfirmationActions.displayName = "ConfirmationActions"

// Individual action button
export type ConfirmationActionProps = React.ComponentProps<typeof Button> & {
  action?: "approve" | "reject"
}

export const ConfirmationAction = memo(function ConfirmationAction({
  className,
  action,
  children,
  variant,
  onClick,
  ...props
}: ConfirmationActionProps) {
  const { onApprove, onReject } = useConfirmation()

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    onClick?.(e)
    if (action === "approve") {
      onApprove?.()
    } else if (action === "reject") {
      onReject?.()
    }
  }

  const defaultVariant = action === "approve" ? "default" : action === "reject" ? "outline" : variant

  return (
    <Button
      data-slot="confirmation-action"
      data-action={action}
      variant={defaultVariant}
      size="sm"
      onClick={handleClick}
      className={cn(className)}
      {...props}
    >
      {children}
    </Button>
  )
})
ConfirmationAction.displayName = "ConfirmationAction"

// Reason display for accepted/rejected states
export type ConfirmationReasonProps = React.ComponentProps<"p">

export const ConfirmationReason = memo(function ConfirmationReason({
  className,
  children,
  ...props
}: ConfirmationReasonProps) {
  const { approval } = useConfirmation()
  const reason = children ?? approval?.reason

  if (!reason) return null

  return (
    <p
      data-slot="confirmation-reason"
      className={cn("text-xs text-muted-foreground mt-2 italic", className)}
      {...props}
    >
      {reason}
    </p>
  )
})
ConfirmationReason.displayName = "ConfirmationReason"

// Convenience component for a complete confirmation dialog
export type ConfirmationDialogProps = {
  title: string
  description?: string
  state: ApprovalState
  approval?: ToolUIPartApproval
  onApprove?: (reason?: string) => void
  onReject?: (reason?: string) => void
  approveLabel?: string
  rejectLabel?: string
  className?: string
}

export const ConfirmationDialog = memo(function ConfirmationDialog({
  title,
  description,
  state,
  approval,
  onApprove,
  onReject,
  approveLabel = "Approve",
  rejectLabel = "Cancel",
  className,
}: ConfirmationDialogProps) {
  return (
    <Confirmation
      state={state}
      approval={approval}
      onApprove={onApprove}
      onReject={onReject}
      className={className}
    >
      <ConfirmationHeader>
        <ConfirmationTitle>{title}</ConfirmationTitle>
        {description && (
          <ConfirmationDescription>{description}</ConfirmationDescription>
        )}
      </ConfirmationHeader>

      <ConfirmationRequest>
        <ConfirmationActions>
          <ConfirmationAction action="approve">
            <Check className="size-4 mr-1" />
            {approveLabel}
          </ConfirmationAction>
          <ConfirmationAction action="reject">
            <X className="size-4 mr-1" />
            {rejectLabel}
          </ConfirmationAction>
        </ConfirmationActions>
      </ConfirmationRequest>

      <ConfirmationAccepted>
        <div className="mt-3 flex items-center gap-2 text-sm text-green-600">
          <Check className="size-4" />
          <span>Approved</span>
        </div>
        <ConfirmationReason />
      </ConfirmationAccepted>

      <ConfirmationRejected>
        <div className="mt-3 flex items-center gap-2 text-sm text-red-600">
          <X className="size-4" />
          <span>Rejected</span>
        </div>
        <ConfirmationReason />
      </ConfirmationRejected>
    </Confirmation>
  )
})
ConfirmationDialog.displayName = "ConfirmationDialog"

// Info confirmation variant for non-destructive actions
export type ConfirmationInfoProps = Omit<ConfirmationDialogProps, "approveLabel"> & {
  continueLabel?: string
}

export const ConfirmationInfo = memo(function ConfirmationInfo({
  continueLabel = "Continue",
  ...props
}: ConfirmationInfoProps) {
  return (
    <Confirmation {...props}>
      <ConfirmationHeader icon={<Info className="size-5 text-blue-500" />}>
        <ConfirmationTitle>{props.title}</ConfirmationTitle>
        {props.description && (
          <ConfirmationDescription>{props.description}</ConfirmationDescription>
        )}
      </ConfirmationHeader>

      <ConfirmationRequest>
        <ConfirmationActions>
          <ConfirmationAction action="approve">
            {continueLabel}
          </ConfirmationAction>
          <ConfirmationAction action="reject" variant="ghost">
            Skip
          </ConfirmationAction>
        </ConfirmationActions>
      </ConfirmationRequest>
    </Confirmation>
  )
})
ConfirmationInfo.displayName = "ConfirmationInfo"
