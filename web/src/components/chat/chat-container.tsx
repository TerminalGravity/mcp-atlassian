"use client"

import { useChat } from "@ai-sdk/react"
import { useRef, useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ScrollArea } from "@/components/ui/scroll-area"
import { ChatMessage } from "./chat-message"
import { ChatInput } from "./chat-input"
import { StarterPrompts } from "./starter-prompts"
import { Search, Loader2, Zap } from "lucide-react"
import { Badge } from "@/components/ui/badge"

export function ChatContainer() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showStarters, setShowStarters] = useState(true)

  const { messages, status, sendMessage } = useChat({
    api: "/api/chat",
  })

  const isLoading = status === "streaming" || status === "submitted"

  // Debug logging
  useEffect(() => {
    console.log("Chat status:", status, "Messages:", messages.length)
  }, [status, messages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // Hide starters after first user message
  useEffect(() => {
    if (messages.some(m => m.role === "user")) {
      setShowStarters(false)
    }
  }, [messages])

  const onSend = (content: string) => {
    setShowStarters(false)
    sendMessage({ text: content })
  }

  const handleStarterSelect = (prompt: string) => {
    setShowStarters(false)
    sendMessage({ text: prompt })
  }

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center gap-3">
          <motion.div
            initial={{ rotate: -10 }}
            animate={{ rotate: 0 }}
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary/80 shadow-lg"
          >
            <Search className="w-5 h-5 text-primary-foreground" />
          </motion.div>
          <div>
            <h1 className="text-lg font-semibold flex items-center gap-2">
              Jira Knowledge
              <Badge variant="secondary" className="text-[10px] font-normal">
                AI-Powered
              </Badge>
            </h1>
            <p className="text-sm text-muted-foreground">
              Semantic search across 400K+ issues
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Zap className="w-3 h-3" />
          <span>Powered by AI SDK</span>
        </div>
      </header>

      {/* Messages */}
      <ScrollArea className="flex-1 px-6" ref={scrollRef}>
        <div className="py-4 space-y-1">
          {/* Starter Prompts */}
          <AnimatePresence>
            {showStarters && messages.length === 0 && (
              <motion.div
                initial={{ opacity: 1 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.3 }}
              >
                <StarterPrompts onSelect={handleStarterSelect} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Chat Messages */}
          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}

          {/* Loading indicator */}
          <AnimatePresence>
            {isLoading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-3 py-4"
              >
                <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                </div>
                <div className="flex items-center gap-2">
                  <motion.div
                    animate={{ opacity: [0.5, 1, 0.5] }}
                    transition={{ duration: 1.5, repeat: Infinity }}
                    className="text-sm text-muted-foreground"
                  >
                    Searching Jira knowledge base...
                  </motion.div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </ScrollArea>

      {/* Input */}
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="px-6 py-4 border-t bg-background/95 backdrop-blur"
      >
        <ChatInput onSend={onSend} isLoading={isLoading} />
        <p className="text-[10px] text-center text-muted-foreground mt-2">
          Searches use vector embeddings + JQL for comprehensive results
        </p>
      </motion.div>
    </div>
  )
}
