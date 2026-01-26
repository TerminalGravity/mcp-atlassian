"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Brain, ChevronDown, ChevronUp, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface ReasoningProps {
  content: string
  duration?: number
  isStreaming?: boolean
  isComplete?: boolean
}

export function Reasoning({ content, duration, isStreaming, isComplete = true }: ReasoningProps) {
  const [expanded, setExpanded] = useState(false)

  if (!content) return null

  return (
    <div className="my-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors",
          "text-muted-foreground hover:text-foreground hover:bg-muted/50",
          expanded && "bg-muted/30"
        )}
      >
        {isStreaming ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-purple-500" />
        ) : (
          <Brain className="w-3.5 h-3.5 text-purple-500" />
        )}
        <span className="font-medium">
          {isStreaming ? "Thinking..." : "View reasoning"}
        </span>
        {duration && isComplete && (
          <span className="text-muted-foreground/60">
            ({(duration / 1000).toFixed(1)}s)
          </span>
        )}
        {expanded ? (
          <ChevronUp className="w-3 h-3 ml-1" />
        ) : (
          <ChevronDown className="w-3 h-3 ml-1" />
        )}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 px-3 py-2 text-xs text-muted-foreground bg-muted/20 rounded-lg border border-border/50">
              <p className="whitespace-pre-wrap leading-relaxed">{content}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
