"use client"

import * as React from "react"
import { memo } from "react"
import { ChevronDown, Search, Check, Loader2, Circle } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"

// Task status types
export type TaskStatus = "pending" | "active" | "complete" | "error"

// Main Task container (collapsible)
export type TaskProps = React.ComponentProps<typeof Collapsible>

export const Task = memo(function Task({
  defaultOpen = true,
  className,
  ...props
}: TaskProps) {
  return (
    <Collapsible
      data-slot="task"
      defaultOpen={defaultOpen}
      className={cn(className)}
      {...props}
    />
  )
})
Task.displayName = "Task"

// Task trigger with title and icon
export type TaskTriggerProps = React.ComponentProps<typeof CollapsibleTrigger> & {
  title: string
  icon?: React.ReactNode
  status?: TaskStatus
}

// Helper to render status icon
function renderStatusIcon(status: TaskStatus, icon?: React.ReactNode) {
  switch (status) {
    case "active":
      return <Loader2 className="size-4 animate-spin text-primary" />
    case "complete":
      return <Check className="size-4 text-green-500" />
    case "error":
      return <Circle className="size-4 text-destructive" />
    default:
      return icon ?? <Search className="size-4" />
  }
}

export const TaskTrigger = memo(function TaskTrigger({
  children,
  className,
  title,
  icon,
  status = "pending",
  ...props
}: TaskTriggerProps) {
  return (
    <CollapsibleTrigger
      asChild
      className={cn("group", className)}
      {...props}
    >
      {children ?? (
        <div className="flex w-full cursor-pointer items-center gap-2 text-muted-foreground text-sm transition-colors hover:text-foreground">
          {renderStatusIcon(status, icon)}
          <p className="text-sm flex-1">{title}</p>
          <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
        </div>
      )}
    </CollapsibleTrigger>
  )
})
TaskTrigger.displayName = "TaskTrigger"

// Task content area with animations
export type TaskContentProps = React.ComponentProps<typeof CollapsibleContent>

export const TaskContent = memo(function TaskContent({
  children,
  className,
  ...props
}: TaskContentProps) {
  return (
    <CollapsibleContent
      data-slot="task-content"
      className={cn(
        "data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
        "text-popover-foreground outline-none overflow-hidden",
        className
      )}
      {...props}
    >
      <div className="mt-3 space-y-2 border-muted border-l-2 pl-4">
        {children}
      </div>
    </CollapsibleContent>
  )
})
TaskContent.displayName = "TaskContent"

// Individual task item
export type TaskItemProps = React.ComponentProps<"div">

export const TaskItem = memo(function TaskItem({
  children,
  className,
  ...props
}: TaskItemProps) {
  return (
    <div
      data-slot="task-item"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    >
      {children}
    </div>
  )
})
TaskItem.displayName = "TaskItem"

// File reference badge
export type TaskItemFileProps = React.ComponentProps<"div">

export const TaskItemFile = memo(function TaskItemFile({
  children,
  className,
  ...props
}: TaskItemFileProps) {
  return (
    <div
      data-slot="task-item-file"
      className={cn(
        "inline-flex items-center gap-1 rounded-md border bg-secondary px-1.5 py-0.5 text-foreground text-xs",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
})
TaskItemFile.displayName = "TaskItemFile"

// Task group for organizing multiple related tasks
export type TaskGroupProps = React.ComponentProps<"div"> & {
  label?: string
}

export const TaskGroup = memo(function TaskGroup({
  className,
  label,
  children,
  ...props
}: TaskGroupProps) {
  return (
    <div
      data-slot="task-group"
      className={cn("space-y-3", className)}
      {...props}
    >
      {label && (
        <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </h4>
      )}
      {children}
    </div>
  )
})
TaskGroup.displayName = "TaskGroup"

// Task progress indicator
export type TaskProgressProps = React.ComponentProps<"div"> & {
  completed: number
  total: number
}

export const TaskProgress = memo(function TaskProgress({
  className,
  completed,
  total,
  ...props
}: TaskProgressProps) {
  const percentage = total > 0 ? (completed / total) * 100 : 0

  return (
    <div
      data-slot="task-progress"
      className={cn("space-y-1", className)}
      {...props}
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Progress</span>
        <span>
          {completed}/{total}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  )
})
TaskProgress.displayName = "TaskProgress"

// Convenience component for a complete task card
export type TaskCardProps = {
  title: string
  status?: TaskStatus
  icon?: React.ReactNode
  items?: Array<{
    id: string
    content: React.ReactNode
    files?: string[]
  }>
  defaultOpen?: boolean
  className?: string
}

export const TaskCard = memo(function TaskCard({
  title,
  status = "pending",
  icon,
  items,
  defaultOpen = true,
  className,
}: TaskCardProps) {
  return (
    <Task defaultOpen={defaultOpen} className={className}>
      <TaskTrigger title={title} status={status} icon={icon} />
      {items && items.length > 0 && (
        <TaskContent>
          {items.map((item) => (
            <TaskItem key={item.id}>
              {item.content}
              {item.files && item.files.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {item.files.map((file) => (
                    <TaskItemFile key={file}>{file}</TaskItemFile>
                  ))}
                </div>
              )}
            </TaskItem>
          ))}
        </TaskContent>
      )}
    </Task>
  )
})
TaskCard.displayName = "TaskCard"

// Multi-task list with progress
export type TaskListProps = {
  tasks: Array<{
    id: string
    title: string
    status: TaskStatus
    items?: Array<{
      id: string
      content: React.ReactNode
      files?: string[]
    }>
  }>
  showProgress?: boolean
  className?: string
}

export const TaskList = memo(function TaskList({
  tasks,
  showProgress = true,
  className,
}: TaskListProps) {
  const completed = tasks.filter((t) => t.status === "complete").length

  return (
    <div className={cn("space-y-4", className)}>
      {showProgress && tasks.length > 1 && (
        <TaskProgress completed={completed} total={tasks.length} />
      )}
      <div className="space-y-3">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            title={task.title}
            status={task.status}
            items={task.items}
            defaultOpen={task.status === "active"}
          />
        ))}
      </div>
    </div>
  )
})
TaskList.displayName = "TaskList"
