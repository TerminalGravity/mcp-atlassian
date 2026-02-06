"use client"

import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
import { useRef, useEffect, useState, useMemo, useCallback, createContext } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { ChatMessage } from "./chat-message"
import { ChatInput } from "./chat-input"
import { StarterPrompts } from "./starter-prompts"
import { ConversationSidebar } from "./conversation-sidebar"
import { OutputModeSelector } from "./output-mode-selector"
import { OutputModeEditor } from "@/components/settings/output-mode-editor"
import { Loader2, ChevronDown, PanelLeft, AlertCircle, X, Sparkles } from "lucide-react"
import { useUser } from "@/contexts/user-context"
import { useOutputMode } from "@/contexts/output-mode-context"
import type { OutputMode } from "@/lib/api"
import {
  getAllConversationMetas,
  getConversation,
  saveConversation,
  deleteConversation,
  createConversation,
  migrateFromOldStorage,
  generateTitle,
  type Conversation,
  type ConversationMeta,
} from "@/lib/conversation-storage"

const MODELS = [
  { id: "gpt-5.2", label: "GPT-5.2", description: "Latest & strongest" },
  { id: "gpt-4.1", label: "GPT-4.1", description: "Fast & reliable" },
] as const

type ModelId = typeof MODELS[number]["id"]

// Context placeholder - research data comes through message parts (data-research-phase, etc.)
// This context is kept for backwards compatibility but is not used
export const ResearchDataContext = createContext<{
  research: null
  refinements: null
  suggestions: null
}>({ research: null, refinements: null, suggestions: null })

export function ChatContainer() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showStarters, setShowStarters] = useState(true)
  const [selectedModel, setSelectedModel] = useState<ModelId>("gpt-5.2")
  const [showModelMenu, setShowModelMenu] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const { currentUser } = useUser()
  const { selectedMode, autoDetectEnabled, detectModeForQuery } = useOutputMode()
  const [showModeEditor, setShowModeEditor] = useState(false)
  const [activeQueryMode, setActiveQueryMode] = useState<OutputMode | null>(null)
  const [modeToast, setModeToast] = useState<{ mode: string; isAuto: boolean } | null>(null)

  // Conversation management
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [hasInitialized, setHasInitialized] = useState(false)

  // Create transport - memoized to avoid recreating on every render
  const transport = useMemo(() => new DefaultChatTransport({
    api: "/api/chat",
  }), [])

  const { messages, status, sendMessage, setMessages, stop, error } = useChat({
    transport,
  })

  // Research data comes through message parts (data-research-phase, data-refinements, data-suggestions)
  // The ChatMessage component reads these from the message.parts array directly

  // Track dismissed errors to avoid re-showing them
  const [dismissedErrorId, setDismissedErrorId] = useState<string | null>(null)

  // Compute display error - show error unless it's been dismissed
  const errorId = error ? `${error.name}-${error.message}` : null
  const chatError = error && errorId !== dismissedErrorId
    ? (error.message || "Failed to get response. Please try again.")
    : null

  // Log errors when they occur
  if (error && errorId !== dismissedErrorId) {
    console.error("[chat] Error:", error)
  }

  // Initialize: migrate old storage and load conversations
  useEffect(() => {
    if (hasInitialized) return

    // Migrate from old single-conversation storage
    migrateFromOldStorage()

    // Load all conversations
    const allConversations = getAllConversationMetas()
    setConversations(allConversations)

    // If we have conversations, load the most recent one
    if (allConversations.length > 0) {
      const mostRecent = allConversations[0]
      setActiveConversationId(mostRecent.id)
      const fullConversation = getConversation(mostRecent.id)
      if (fullConversation && fullConversation.messages.length > 0) {
        setMessages(fullConversation.messages)
        setShowStarters(false)
      }
    } else {
      // No conversations, create a new one
      const newConv = createConversation()
      saveConversation(newConv)
      setActiveConversationId(newConv.id)
      setConversations([{
        id: newConv.id,
        title: newConv.title,
        createdAt: newConv.createdAt,
        updatedAt: newConv.updatedAt,
        messageCount: 0,
      }])
    }

    setHasInitialized(true)
  }, [hasInitialized, setMessages])

  // Save messages to current conversation when they change
  useEffect(() => {
    if (!hasInitialized || !activeConversationId) return
    if (messages.length === 0) return

    const currentConv = getConversation(activeConversationId)
    if (!currentConv) return

    // Update conversation with new messages and title
    const updatedConv: Conversation = {
      ...currentConv,
      messages,
      title: generateTitle(messages),
      updatedAt: Date.now(),
    }
    saveConversation(updatedConv)

    // Update conversations list
    setConversations(getAllConversationMetas())
  }, [messages, hasInitialized, activeConversationId])

  // Handle selecting a conversation
  const handleSelectConversation = useCallback((id: string) => {
    if (id === activeConversationId) return

    const conv = getConversation(id)
    if (conv) {
      setActiveConversationId(id)
      setMessages(conv.messages)
      setShowStarters(conv.messages.length === 0)
    }
  }, [activeConversationId, setMessages])

  // Handle creating a new conversation
  const handleNewConversation = useCallback(() => {
    const newConv = createConversation()
    saveConversation(newConv)
    setActiveConversationId(newConv.id)
    setMessages([])
    setShowStarters(true)
    setConversations(getAllConversationMetas())
  }, [setMessages])

  // Handle deleting a conversation
  const handleDeleteConversation = useCallback((id: string) => {
    deleteConversation(id)
    const remaining = getAllConversationMetas()
    setConversations(remaining)

    // If we deleted the active conversation, switch to another or create new
    if (id === activeConversationId) {
      if (remaining.length > 0) {
        const next = remaining[0]
        setActiveConversationId(next.id)
        const conv = getConversation(next.id)
        if (conv) {
          setMessages(conv.messages)
          setShowStarters(conv.messages.length === 0)
        }
      } else {
        // No conversations left, create a new one
        const newConv = createConversation()
        saveConversation(newConv)
        setActiveConversationId(newConv.id)
        setMessages([])
        setShowStarters(true)
        setConversations([{
          id: newConv.id,
          title: newConv.title,
          createdAt: newConv.createdAt,
          updatedAt: newConv.updatedAt,
          messageCount: 0,
        }])
      }
    }
  }, [activeConversationId, setMessages])

  const isLoading = status === "streaming" || status === "submitted"

  // Debug logging
  useEffect(() => {
    console.log("Chat status:", status, "Messages:", messages.length, "Active:", activeConversationId)
  }, [status, messages, activeConversationId])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  // Hide starters if we have messages
  useEffect(() => {
    if (messages.length > 0) {
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

  const onSend = async (content: string) => {
    setShowStarters(false)
    setDismissedErrorId(null) // Reset to show any new errors
    setModeToast(null)

    // Detect mode if auto-detect is enabled
    const modeForQuery = autoDetectEnabled
      ? await detectModeForQuery(content)
      : selectedMode

    // Track the active mode and show toast if auto-detected
    setActiveQueryMode(modeForQuery)
    if (autoDetectEnabled && modeForQuery && modeForQuery.id !== selectedMode?.id) {
      setModeToast({ mode: modeForQuery.display_name, isAuto: true })
      // Auto-hide toast after 3 seconds
      setTimeout(() => setModeToast(null), 3000)
    }

    sendMessage(
      { text: content },
      {
        body: {
          model: selectedModel,
          currentUser: currentUser.id,
          outputModeId: modeForQuery?.id || null,
        },
      }
    )
  }

  const handleStarterSelect = async (prompt: string) => {
    setShowStarters(false)
    setDismissedErrorId(null) // Reset to show any new errors
    setModeToast(null)

    const modeForQuery = autoDetectEnabled
      ? await detectModeForQuery(prompt)
      : selectedMode

    setActiveQueryMode(modeForQuery)
    if (autoDetectEnabled && modeForQuery && modeForQuery.id !== selectedMode?.id) {
      setModeToast({ mode: modeForQuery.display_name, isAuto: true })
      setTimeout(() => setModeToast(null), 3000)
    }

    sendMessage(
      { text: prompt },
      {
        body: {
          model: selectedModel,
          currentUser: currentUser.id,
          outputModeId: modeForQuery?.id || null,
        },
      }
    )
  }

  return (
    <div className="flex h-[calc(100vh-57px)] relative">
      {/* Conversation Sidebar */}
      <ConversationSidebar
        conversations={conversations}
        activeId={activeConversationId}
        onSelect={handleSelectConversation}
        onNew={handleNewConversation}
        onDelete={handleDeleteConversation}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      {/* Main Chat Area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Header - sticky at top */}
        <div className="sticky top-0 z-20 flex items-center justify-between gap-2 px-4 py-2 border-b bg-background/95 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            {!sidebarOpen && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSidebarOpen(true)}
                className="h-8 w-8 p-0"
              >
                <PanelLeft className="w-4 h-4" />
              </Button>
            )}
          </div>

          {/* Output Mode Selector */}
          <OutputModeSelector onManageModes={() => setShowModeEditor(true)} />

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

        {/* Messages - scrollable area */}
        <ScrollArea className="flex-1 overflow-y-auto px-6" ref={scrollRef}>
          <div className="py-4 space-y-1 max-w-4xl mx-auto">
            {/* Starter Prompts */}
            <AnimatePresence>
              {showStarters && messages.length === 0 && (
                <motion.div
                  initial={{ opacity: 1 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.3 }}
                >
                  <StarterPrompts onSelect={handleStarterSelect} isLoading={isLoading} />
                </motion.div>
              )}
            </AnimatePresence>

            {/* Chat Messages */}
            <ResearchDataContext.Provider value={{ research: null, refinements: null, suggestions: null }}>
              {messages.map((message, index) => (
                <ChatMessage key={`${message.id}-${index}`} message={message} onSendMessage={onSend} />
              ))}
            </ResearchDataContext.Provider>

            {/* Loading indicator with active mode */}
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
                  <div className="flex flex-col gap-1">
                    <motion.div
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 1.5, repeat: Infinity }}
                      className="text-sm text-muted-foreground"
                    >
                      Searching Jira knowledge base...
                    </motion.div>
                    {activeQueryMode && (
                      <div className="flex items-center gap-1.5 text-[10px] text-violet-500">
                        <Sparkles className="w-3 h-3" />
                        <span>Formatting as {activeQueryMode.display_name}</span>
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Mode auto-detect toast */}
            <AnimatePresence>
              {modeToast && (
                <motion.div
                  initial={{ opacity: 0, y: -10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -10, scale: 0.95 }}
                  className="fixed top-20 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2 rounded-full bg-violet-500/10 border border-violet-500/20 shadow-lg backdrop-blur-sm"
                >
                  <Sparkles className="w-4 h-4 text-violet-500" />
                  <span className="text-sm font-medium text-violet-700 dark:text-violet-300">
                    Auto-detected: {modeToast.mode}
                  </span>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Error display */}
            <AnimatePresence>
              {chatError && !isLoading && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex items-start gap-3 py-4 px-4 rounded-lg bg-destructive/10 border border-destructive/20"
                >
                  <AlertCircle className="w-5 h-5 text-destructive shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-destructive font-medium">Something went wrong</p>
                    <p className="text-xs text-destructive/80 mt-1">{chatError}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDismissedErrorId(errorId)}
                    className="h-6 w-6 p-0 text-destructive/60 hover:text-destructive"
                  >
                    <X className="w-4 h-4" />
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </ScrollArea>

        {/* Input - sticky at bottom */}
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="sticky bottom-0 z-20 px-6 py-4 border-t bg-background/95 backdrop-blur-sm"
        >
          <div className="max-w-4xl mx-auto">
            <ChatInput onSend={onSend} onStop={stop} isLoading={isLoading} />
            <p className="text-[10px] text-center text-muted-foreground mt-2">
              Searches use vector embeddings + JQL for comprehensive results
            </p>
          </div>
        </motion.div>
      </div>

      {/* Output Mode Editor Modal */}
      <OutputModeEditor
        isOpen={showModeEditor}
        onClose={() => setShowModeEditor(false)}
      />
    </div>
  )
}
