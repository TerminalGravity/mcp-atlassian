"use client"

import { motion } from "framer-motion"
import { Sparkles } from "lucide-react"

interface SuggestionChipsProps {
  prompts: string[]
  onSelect?: (prompt: string) => void
}

export function SuggestionChips({ prompts, onSelect }: SuggestionChipsProps) {
  if (!prompts?.length || !onSelect) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.3 }}
      className="mt-4 pt-4 border-t border-border/50"
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-2">
        <Sparkles className="w-3 h-3" />
        <span>Continue exploring</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {prompts.map((prompt, i) => (
          <motion.button
            key={prompt}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.4 + i * 0.1, duration: 0.2 }}
            onClick={() => onSelect(prompt)}
            className="px-3 py-1.5 text-sm rounded-full border border-border/60
                       bg-background hover:bg-accent hover:border-accent-foreground/20
                       transition-all duration-200 hover:shadow-sm"
          >
            {prompt}
          </motion.button>
        ))}
      </div>
    </motion.div>
  )
}
