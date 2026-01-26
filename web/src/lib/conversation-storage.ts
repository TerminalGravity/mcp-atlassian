import type { UIMessage } from "@ai-sdk/react"

// Storage keys
const STORAGE_KEY = "jira-knowledge-conversations"
const OLD_STORAGE_KEY = "jira-knowledge-chat-history"

// Types
export interface Conversation {
  id: string
  title: string
  messages: UIMessage[]
  createdAt: number
  updatedAt: number
}

export interface ConversationMeta {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messageCount: number
}

type ConversationStore = { [id: string]: Conversation }

// Helpers
function isSSR(): boolean {
  return typeof window === "undefined"
}

function getStore(): ConversationStore {
  if (isSSR()) return {}
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return {}
    const parsed = JSON.parse(stored)
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return {}
    }
    return parsed as ConversationStore
  } catch {
    return {}
  }
}

function setStore(store: ConversationStore): void {
  if (isSSR()) return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch (e) {
    console.warn("Failed to save conversations:", e)
  }
}

// Public API

/**
 * Generate a unique ID for a new conversation
 */
export function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  // Fallback for older browsers
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`
}

/**
 * Generate a title from the first user message
 * Truncates to 50 characters with "..." if needed
 */
export function generateTitle(messages: UIMessage[]): string {
  const firstUserMessage = messages.find((m) => m.role === "user")
  if (!firstUserMessage) {
    return "New Conversation"
  }

  // Extract text content from message parts
  // UIMessage uses a 'parts' array with typed parts (text, tool-invocation, etc.)
  let text = ""
  const parts = firstUserMessage.parts || []
  const textParts = parts.filter(
    (p): p is { type: "text"; text: string } => p.type === "text"
  )
  text = textParts.map((p) => p.text).join(" ")

  // Clean up whitespace
  text = text.trim().replace(/\s+/g, " ")

  if (!text) {
    return "New Conversation"
  }

  if (text.length <= 50) {
    return text
  }

  return text.substring(0, 50) + "..."
}

/**
 * Get metadata for all conversations, sorted by updatedAt descending
 */
export function getAllConversationMetas(): ConversationMeta[] {
  const store = getStore()
  const metas: ConversationMeta[] = Object.values(store).map((conv) => ({
    id: conv.id,
    title: conv.title,
    createdAt: conv.createdAt,
    updatedAt: conv.updatedAt,
    messageCount: conv.messages.length,
  }))

  // Sort by updatedAt descending (most recent first)
  return metas.sort((a, b) => b.updatedAt - a.updatedAt)
}

/**
 * Get a full conversation by ID
 */
export function getConversation(id: string): Conversation | null {
  const store = getStore()
  return store[id] || null
}

/**
 * Save or update a conversation
 */
export function saveConversation(conversation: Conversation): void {
  const store = getStore()
  store[conversation.id] = {
    ...conversation,
    updatedAt: Date.now(),
  }
  setStore(store)
}

/**
 * Delete a conversation by ID
 */
export function deleteConversation(id: string): void {
  const store = getStore()
  delete store[id]
  setStore(store)
}

/**
 * Create a new empty conversation with a generated ID
 */
export function createConversation(): Conversation {
  const now = Date.now()
  return {
    id: generateId(),
    title: "New Conversation",
    messages: [],
    createdAt: now,
    updatedAt: now,
  }
}

/**
 * Migrate from old storage format (single conversation) to new format (multiple conversations)
 * Should be called on app initialization
 */
export function migrateFromOldStorage(): void {
  if (isSSR()) return

  try {
    const oldData = localStorage.getItem(OLD_STORAGE_KEY)
    if (!oldData) return

    const oldMessages = JSON.parse(oldData)
    if (!Array.isArray(oldMessages) || oldMessages.length === 0) {
      // No valid data to migrate, just remove the old key
      localStorage.removeItem(OLD_STORAGE_KEY)
      return
    }

    // Create a new conversation from the old messages
    const now = Date.now()
    const newConversation: Conversation = {
      id: generateId(),
      title: generateTitle(oldMessages as UIMessage[]),
      messages: oldMessages as UIMessage[],
      createdAt: now,
      updatedAt: now,
    }

    // Save to new storage format
    const store = getStore()
    store[newConversation.id] = newConversation
    setStore(store)

    // Remove old storage key
    localStorage.removeItem(OLD_STORAGE_KEY)

    console.log("Migrated chat history to new conversation format")
  } catch (e) {
    console.warn("Failed to migrate old chat history:", e)
    // Still try to remove the old key to prevent repeated migration attempts
    try {
      localStorage.removeItem(OLD_STORAGE_KEY)
    } catch {
      // Ignore
    }
  }
}
