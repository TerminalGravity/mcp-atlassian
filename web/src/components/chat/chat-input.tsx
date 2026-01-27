"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Send, Square, Sparkles } from "lucide-react"
import { useOutputMode } from "@/contexts/output-mode-context"
import { motion, AnimatePresence } from "framer-motion"

interface ChatInputProps {
  onSend: (message: string) => void
  onStop?: () => void
  isLoading?: boolean
  placeholder?: string
}

export function ChatInput({ onSend, onStop, isLoading, placeholder = "Ask about Jira issues..." }: ChatInputProps) {
  const [input, setInput] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { modes, selectedMode, autoDetectEnabled } = useOutputMode()

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`
    }
  }, [input])

  // Simple client-side mode preview (matches backend logic loosely)
  const previewMode = useMemo(() => {
    if (!autoDetectEnabled || !input.trim() || input.length < 3) {
      return selectedMode
    }
    const lower = input.toLowerCase()
    for (const mode of modes) {
      // Check keywords
      for (const keyword of mode.query_patterns.keywords) {
        if (lower.includes(keyword.toLowerCase())) {
          return mode
        }
      }
      // Check regex patterns
      for (const pattern of mode.query_patterns.regex) {
        try {
          if (new RegExp(pattern, "i").test(lower)) {
            return mode
          }
        } catch {
          // Invalid regex, skip
        }
      }
    }
    return selectedMode
  }, [input, modes, selectedMode, autoDetectEnabled])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && !isLoading) {
      onSend(input.trim())
      setInput("")
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative">
      <div className="relative flex items-end gap-2 rounded-2xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          rows={1}
          className={cn(
            "flex-1 resize-none bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            "min-h-[44px] max-h-[200px]"
          )}
        />
        {isLoading && onStop ? (
          <Button
            type="button"
            size="icon"
            variant="destructive"
            onClick={onStop}
            className="h-10 w-10 shrink-0 rounded-xl"
          >
            <Square className="h-4 w-4 fill-current" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            disabled={!input.trim() || isLoading}
            className="h-10 w-10 shrink-0 rounded-xl"
          >
            <Send className="h-4 w-4" />
          </Button>
        )}
      </div>
      <div className="mt-2 flex items-center justify-center gap-2">
        <AnimatePresence mode="wait">
          {input.trim().length >= 3 && previewMode && autoDetectEnabled && (
            <motion.div
              key={previewMode.id}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              className="flex items-center gap-1.5 text-[10px] text-violet-600 dark:text-violet-400"
            >
              <Sparkles className="w-3 h-3" />
              <span>Will format as: <strong>{previewMode.display_name}</strong></span>
            </motion.div>
          )}
        </AnimatePresence>
        {(!input.trim() || input.trim().length < 3 || !autoDetectEnabled) && (
          <p className="text-[10px] text-muted-foreground">
            Press Enter to send, Shift+Enter for new line
          </p>
        )}
      </div>
    </form>
  )
}
