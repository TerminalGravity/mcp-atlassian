"use client"

import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
import { useRef, useEffect, useState, useMemo } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ScrollArea } from "@/components/ui/scroll-area"
import { ChatMessage } from "./chat-message"
import { ChatInput } from "./chat-input"
import { StarterPrompts } from "./starter-prompts"
import { Loader2, ChevronDown } from "lucide-react"
import { useUser } from "@/contexts/user-context"

const MODELS = [
  { id: "gpt-5.2", label: "GPT-5.2", description: "Latest & strongest" },
  { id: "gpt-4.1", label: "GPT-4.1", description: "Fast & reliable" },
] as const

type ModelId = typeof MODELS[number]["id"]

export function ChatContainer() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showStarters, setShowStarters] = useState(true)
  const [selectedModel, setSelectedModel] = useState<ModelId>("gpt-5.2")
  const [showModelMenu, setShowModelMenu] = useState(false)
  const { currentUser } = useUser()

  // Create transport - memoized to avoid recreating on every render
  const transport = useMemo(() => new DefaultChatTransport({
    api: "/api/chat",
  }), [])

  const { messages, status, sendMessage } = useChat({
    transport,
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

  // Close menus when clicking outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('[data-dropdown]')) return
      setShowModelMenu(false)
    }
    if (showModelMenu) {
      const timer = setTimeout(() => {
        document.addEventListener("click", handleClick)
      }, 0)
      return () => {
        clearTimeout(timer)
        document.removeEventListener("click", handleClick)
      }
    }
  }, [showModelMenu])

  const onSend = (content: string) => {
    setShowStarters(false)
    sendMessage({ text: content }, { body: { model: selectedModel, currentUser: currentUser.id } })
  }

  const handleStarterSelect = (prompt: string) => {
    setShowStarters(false)
    sendMessage({ text: prompt }, { body: { model: selectedModel, currentUser: currentUser.id } })
  }

  return (
    <div className="flex flex-col h-[calc(100vh-57px)] max-w-4xl mx-auto">
      {/* Model Selector Header */}
      <div className="flex items-center justify-end px-6 py-2 border-b bg-background/50">
        <div className="relative" data-dropdown>
          <button
            onClick={() => setShowModelMenu(!showModelMenu)}
            className="flex items-center gap-2 px-2.5 py-1.5 text-xs font-medium rounded-lg border bg-background hover:bg-muted transition-colors"
          >
            <span className="text-muted-foreground hidden sm:inline">Model:</span>
            <span>{MODELS.find(m => m.id === selectedModel)?.label}</span>
            <ChevronDown className={`w-3 h-3 text-muted-foreground transition-transform ${showModelMenu ? "rotate-180" : ""}`} />
          </button>
          <AnimatePresence>
            {showModelMenu && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.1 }}
                className="absolute right-0 top-full mt-2 w-48 rounded-lg border bg-popover shadow-xl z-[9999]"
              >
                {MODELS.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => {
                      setSelectedModel(model.id)
                      setShowModelMenu(false)
                    }}
                    className={`w-full px-3 py-2.5 text-left text-sm hover:bg-accent transition-colors first:rounded-t-lg last:rounded-b-lg ${
                      selectedModel === model.id ? "bg-accent" : ""
                    }`}
                  >
                    <div className="font-medium">{model.label}</div>
                    <div className="text-xs text-muted-foreground">{model.description}</div>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

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
            <ChatMessage key={message.id} message={message} onSendMessage={onSend} />
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
