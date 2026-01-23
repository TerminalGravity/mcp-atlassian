"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Check, Loader2, Search, Database, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"

interface Step {
  id: string
  label: string
  status: "pending" | "active" | "complete"
  detail?: string
}

interface SearchStepsProps {
  steps: Step[]
}

const iconMap: Record<string, React.ElementType> = {
  search: Search,
  jql: Database,
  analyze: Sparkles,
}

export function SearchSteps({ steps }: SearchStepsProps) {
  if (steps.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="flex items-center gap-2 py-3"
    >
      <AnimatePresence mode="popLayout">
        {steps.map((step, index) => {
          const Icon = iconMap[step.id] || Search

          return (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, scale: 0.8, x: -20 }}
              animate={{ opacity: 1, scale: 1, x: 0 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ delay: index * 0.1 }}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                step.status === "active" && "bg-primary/10 text-primary border border-primary/20",
                step.status === "complete" && "bg-green-500/10 text-green-500 border border-green-500/20",
                step.status === "pending" && "bg-muted text-muted-foreground"
              )}
            >
              {step.status === "active" ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : step.status === "complete" ? (
                <Check className="w-3 h-3" />
              ) : (
                <Icon className="w-3 h-3" />
              )}
              <span>{step.label}</span>
              {step.detail && (
                <span className="text-muted-foreground">
                  ({step.detail})
                </span>
              )}
            </motion.div>
          )
        })}
      </AnimatePresence>
    </motion.div>
  )
}
