"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { FileText, ChevronDown, ChevronUp, ExternalLink } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

interface Source {
  issue_id: string
  summary: string
  status: string
  url?: string
}

interface SourcesProps {
  sources: Source[]
  maxVisible?: number
}

export function Sources({ sources, maxVisible = 3 }: SourcesProps) {
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  const visibleSources = expanded ? sources : sources.slice(0, maxVisible)
  const hasMore = sources.length > maxVisible

  return (
    <div className="my-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors",
          "text-muted-foreground hover:text-foreground hover:bg-muted/50",
          expanded && "bg-muted/30"
        )}
      >
        <FileText className="w-3.5 h-3.5 text-blue-500" />
        <span className="font-medium">Sources</span>
        <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
          {sources.length}
        </Badge>
        {hasMore && (
          expanded ? (
            <ChevronUp className="w-3 h-3 ml-1" />
          ) : (
            <ChevronDown className="w-3 h-3 ml-1" />
          )
        )}
      </button>

      <AnimatePresence>
        {(expanded || sources.length <= maxVisible) && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1">
              {visibleSources.map((source, i) => (
                <motion.a
                  key={source.issue_id}
                  href={source.url || `https://alldigitalrewards.atlassian.net/browse/${source.issue_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 text-xs rounded-lg",
                    "bg-muted/30 hover:bg-muted/50 transition-colors group"
                  )}
                >
                  <Badge variant="outline" className="text-[10px] font-mono shrink-0">
                    {source.issue_id}
                  </Badge>
                  <span className="truncate flex-1 text-muted-foreground group-hover:text-foreground">
                    {source.summary}
                  </span>
                  <Badge
                    variant="secondary"
                    className={cn(
                      "text-[9px] shrink-0",
                      source.status === "Done" && "bg-green-500/10 text-green-500",
                      source.status === "Closed" && "bg-green-500/10 text-green-500",
                      source.status === "In Progress" && "bg-yellow-500/10 text-yellow-500",
                      source.status === "Development in Progress" && "bg-yellow-500/10 text-yellow-500"
                    )}
                  >
                    {source.status}
                  </Badge>
                  <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </motion.a>
              ))}
              {hasMore && !expanded && (
                <button
                  onClick={() => setExpanded(true)}
                  className="w-full text-center text-xs text-muted-foreground hover:text-foreground py-1"
                >
                  +{sources.length - maxVisible} more
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
