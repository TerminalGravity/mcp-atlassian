"use client"

import { useRef, useEffect, useState, useMemo } from "react"
import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
import { motion, AnimatePresence } from "framer-motion"
import { MessageSquare, Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { ChatMessage } from "@/components/chat/chat-message"
import { ChatInput } from "@/components/chat/chat-input"

interface MyWorkChatProps {
  currentUser: string
}

const STARTER_PROMPTS = [
  "What's blocking me?",
  "Summarize my sprint",
  "What should I work on next?",
  "Show my stale issues",
]

export function MyWorkChat({ currentUser }: MyWorkChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showStarters, setShowStarters] = useState(true)

  const transport = useMemo(() => new DefaultChatTransport({
    api: "/api/chat",
  }), [])

  const { messages, status, sendMessage } = useChat({
    transport,
  })

  const isLoading = status === "streaming" || status === "submitted"

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    if (messages.some(m => m.role === "user")) {
      setShowStarters(false)
    }
  }, [messages])

  const onSend = (content: string) => {
    setShowStarters(false)
    sendMessage(
      { text: content },
      { body: { currentUser, scope: "my-work" } }
    )
  }

  return (
    <Card className="sticky top-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <MessageSquare className="w-4 h-4" />
          Ask about your work
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Starter prompts */}
        <AnimatePresence>
          {showStarters && messages.length === 0 && (
            <motion.div
              initial={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-2"
            >
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => onSend(prompt)}
                  className="w-full text-left text-sm px-3 py-2 rounded-lg border hover:bg-muted transition-colors"
                >
                  {prompt}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Messages */}
        {messages.length > 0 && (
          <ScrollArea className="h-[400px]" ref={scrollRef}>
            <div className="space-y-2 pr-4">
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} onSendMessage={onSend} />
              ))}

              {/* Loading indicator */}
              <AnimatePresence>
                {isLoading && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex items-center gap-2 py-2 text-sm text-muted-foreground"
                  >
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Searching...
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </ScrollArea>
        )}

        {/* Input */}
        <ChatInput onSend={onSend} isLoading={isLoading} placeholder="Ask about your work..." />
      </CardContent>
    </Card>
  )
}
