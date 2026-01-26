"use client"

import { motion, AnimatePresence } from "framer-motion"
import { Plus, ChevronLeft, ChevronRight, Trash2, MessageSquare } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"

export interface ConversationMeta {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messageCount: number
}

export interface ConversationSidebarProps {
  conversations: ConversationMeta[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  isOpen: boolean
  onToggle: () => void
}

/**
 * Format a timestamp into a human-readable relative time string
 */
function formatRelativeTime(timestamp: number): string {
  const now = Date.now()
  const diff = now - timestamp

  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (seconds < 60) {
    return "Just now"
  }

  if (minutes < 60) {
    return `${minutes}m ago`
  }

  if (hours < 24) {
    return `${hours}h ago`
  }

  if (days === 1) {
    return "Yesterday"
  }

  if (days < 7) {
    return `${days}d ago`
  }

  // Format as date for older items
  const date = new Date(timestamp)
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

/**
 * Group conversations by time period
 */
function groupConversationsByTime(conversations: ConversationMeta[]): {
  today: ConversationMeta[]
  yesterday: ConversationMeta[]
  previousWeek: ConversationMeta[]
  older: ConversationMeta[]
} {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000)
  const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000)

  const groups = {
    today: [] as ConversationMeta[],
    yesterday: [] as ConversationMeta[],
    previousWeek: [] as ConversationMeta[],
    older: [] as ConversationMeta[],
  }

  // Sort by updatedAt descending
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)

  for (const conv of sorted) {
    const date = new Date(conv.updatedAt)

    if (date >= today) {
      groups.today.push(conv)
    } else if (date >= yesterday) {
      groups.yesterday.push(conv)
    } else if (date >= weekAgo) {
      groups.previousWeek.push(conv)
    } else {
      groups.older.push(conv)
    }
  }

  return groups
}

interface ConversationGroupProps {
  title: string
  conversations: ConversationMeta[]
  activeId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}

function ConversationGroup({
  title,
  conversations,
  activeId,
  onSelect,
  onDelete,
}: ConversationGroupProps) {
  if (conversations.length === 0) return null

  return (
    <div className="mb-4">
      <h3 className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-0.5">
        {conversations.map((conv) => (
          <ConversationItem
            key={conv.id}
            conversation={conv}
            isActive={activeId === conv.id}
            onSelect={onSelect}
            onDelete={onDelete}
          />
        ))}
      </div>
    </div>
  )
}

interface ConversationItemProps {
  conversation: ConversationMeta
  isActive: boolean
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}

function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: ConversationItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className="group relative"
    >
      <button
        onClick={() => onSelect(conversation.id)}
        className={cn(
          "w-full text-left px-3 py-2 rounded-md transition-colors",
          "hover:bg-muted/50",
          isActive && "bg-muted"
        )}
      >
        <div className="flex items-start gap-2">
          <MessageSquare className="w-4 h-4 mt-0.5 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <p className="text-sm truncate pr-6">{conversation.title}</p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              {formatRelativeTime(conversation.updatedAt)}
            </p>
          </div>
        </div>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          onDelete(conversation.id)
        }}
        className={cn(
          "absolute right-2 top-1/2 -translate-y-1/2",
          "p-1 rounded-md transition-all",
          "opacity-0 group-hover:opacity-100",
          "hover:bg-destructive/10 hover:text-destructive",
          "text-muted-foreground"
        )}
        aria-label="Delete conversation"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </motion.div>
  )
}

export function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  isOpen,
  onToggle,
}: ConversationSidebarProps) {
  const groups = groupConversationsByTime(conversations)

  return (
    <>
      {/* Sidebar */}
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 256, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="h-full border-r bg-background/50 overflow-hidden shrink-0"
          >
            <div className="flex flex-col h-full w-64">
              {/* Header */}
              <div className="flex items-center justify-between px-3 py-3 border-b">
                <h2 className="text-sm font-medium">Conversations</h2>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={onToggle}
                  aria-label="Collapse sidebar"
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
              </div>

              {/* New Chat Button */}
              <div className="p-3 border-b">
                <Button
                  onClick={onNew}
                  className="w-full justify-start gap-2"
                  variant="outline"
                >
                  <Plus className="w-4 h-4" />
                  New Chat
                </Button>
              </div>

              {/* Conversation List */}
              <ScrollArea className="flex-1">
                <div className="py-2">
                  <ConversationGroup
                    title="Today"
                    conversations={groups.today}
                    activeId={activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                  <ConversationGroup
                    title="Yesterday"
                    conversations={groups.yesterday}
                    activeId={activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                  <ConversationGroup
                    title="Previous 7 Days"
                    conversations={groups.previousWeek}
                    activeId={activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                  <ConversationGroup
                    title="Older"
                    conversations={groups.older}
                    activeId={activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />

                  {/* Empty State */}
                  {conversations.length === 0 && (
                    <div className="px-3 py-8 text-center">
                      <MessageSquare className="w-8 h-8 mx-auto text-muted-foreground/50 mb-2" />
                      <p className="text-sm text-muted-foreground">No conversations yet</p>
                      <p className="text-xs text-muted-foreground/70 mt-1">
                        Start a new chat to begin
                      </p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Toggle Button (visible when closed) */}
      <AnimatePresence>
        {!isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute left-0 top-3 z-10"
          >
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onToggle}
              className="rounded-l-none border border-l-0"
              aria-label="Expand sidebar"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
