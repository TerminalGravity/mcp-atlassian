"use client"

import { memo } from "react"
import { motion } from "framer-motion"
import {
  Filter,
  Folder,
  Calendar,
  Tag,
  AlertCircle,
  CircleDot,
} from "lucide-react"
import { cn } from "@/lib/utils"

// Refinement filter structure for search narrowing
export interface RefinementFilter {
  field: string // e.g., "project_key"
  value: string // e.g., "DS"
  operator: string // e.g., "$eq"
}

// Individual refinement option
export interface Refinement {
  id: string
  label: string // e.g., "DS only (23)"
  category: "project" | "time" | "type" | "priority" | "status"
  filter: RefinementFilter
  count?: number // Result count for this filter
}

export interface RefinementChipsProps {
  refinements: Refinement[]
  onSelect?: (refinement: Refinement) => void
  className?: string
}

// Category-specific styling and icons
const categoryConfig: Record<
  Refinement["category"],
  {
    icon: typeof Filter
    bgColor: string
    hoverBgColor: string
    borderColor: string
    textColor: string
  }
> = {
  project: {
    icon: Folder,
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    hoverBgColor: "hover:bg-blue-100 dark:hover:bg-blue-900/40",
    borderColor: "border-blue-200 dark:border-blue-800",
    textColor: "text-blue-700 dark:text-blue-300",
  },
  time: {
    icon: Calendar,
    bgColor: "bg-purple-50 dark:bg-purple-950/30",
    hoverBgColor: "hover:bg-purple-100 dark:hover:bg-purple-900/40",
    borderColor: "border-purple-200 dark:border-purple-800",
    textColor: "text-purple-700 dark:text-purple-300",
  },
  type: {
    icon: Tag,
    bgColor: "bg-emerald-50 dark:bg-emerald-950/30",
    hoverBgColor: "hover:bg-emerald-100 dark:hover:bg-emerald-900/40",
    borderColor: "border-emerald-200 dark:border-emerald-800",
    textColor: "text-emerald-700 dark:text-emerald-300",
  },
  priority: {
    icon: AlertCircle,
    bgColor: "bg-amber-50 dark:bg-amber-950/30",
    hoverBgColor: "hover:bg-amber-100 dark:hover:bg-amber-900/40",
    borderColor: "border-amber-200 dark:border-amber-800",
    textColor: "text-amber-700 dark:text-amber-300",
  },
  status: {
    icon: CircleDot,
    bgColor: "bg-slate-50 dark:bg-slate-950/30",
    hoverBgColor: "hover:bg-slate-100 dark:hover:bg-slate-900/40",
    borderColor: "border-slate-200 dark:border-slate-700",
    textColor: "text-slate-700 dark:text-slate-300",
  },
}

// Individual chip component
const RefinementChip = memo(function RefinementChip({
  refinement,
  index,
  onSelect,
}: {
  refinement: Refinement
  index: number
  onSelect?: (refinement: Refinement) => void
}) {
  const config = categoryConfig[refinement.category]
  const Icon = config.icon

  return (
    <motion.button
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.4 + index * 0.08, duration: 0.2 }}
      onClick={() => onSelect?.(refinement)}
      className={cn(
        "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full",
        "border transition-all duration-200 hover:shadow-sm",
        config.bgColor,
        config.hoverBgColor,
        config.borderColor,
        config.textColor
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      <span>{refinement.label}</span>
      {refinement.count !== undefined && (
        <span className="text-xs opacity-70">({refinement.count})</span>
      )}
    </motion.button>
  )
})
RefinementChip.displayName = "RefinementChip"

// Main refinement chips container
export const RefinementChips = memo(function RefinementChips({
  refinements,
  onSelect,
  className,
}: RefinementChipsProps) {
  if (!refinements?.length) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.3 }}
      className={cn("mt-4 pt-4 border-t border-border/50", className)}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
        <Filter className="w-3 h-3" />
        <span>Narrow results</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {refinements.map((refinement, i) => (
          <RefinementChip
            key={refinement.id}
            refinement={refinement}
            index={i}
            onSelect={onSelect}
          />
        ))}
      </div>
    </motion.div>
  )
})
RefinementChips.displayName = "RefinementChips"
