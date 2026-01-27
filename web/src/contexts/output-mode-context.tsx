"use client"

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react"
import {
  type OutputMode,
  fetchOutputModes,
  fetchUserPreferences,
  updateUserPreferences,
  classifyQuery,
} from "@/lib/api"
import { useUser } from "./user-context"

interface OutputModeContextType {
  modes: OutputMode[]
  selectedMode: OutputMode | null
  autoDetectEnabled: boolean
  isLoading: boolean
  error: string | null
  setSelectedMode: (mode: OutputMode | null) => void
  setAutoDetectEnabled: (enabled: boolean) => void
  detectModeForQuery: (query: string) => Promise<OutputMode | null>
  refreshModes: () => Promise<void>
}

const OutputModeContext = createContext<OutputModeContextType | undefined>(undefined)

export function OutputModeProvider({ children }: { children: ReactNode }) {
  const [modes, setModes] = useState<OutputMode[]>([])
  const [selectedMode, setSelectedModeState] = useState<OutputMode | null>(null)
  const [autoDetectEnabled, setAutoDetectEnabledState] = useState(true)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isHydrated, setIsHydrated] = useState(false)
  const { currentUser } = useUser()

  // Load modes and user preferences
  const loadModesAndPreferences = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)

      // Fetch modes
      const fetchedModes = await fetchOutputModes(currentUser.id)
      setModes(fetchedModes)

      // Find default mode (first with is_default=true)
      const defaultMode = fetchedModes.find((m) => m.is_default) || fetchedModes[0]

      // Fetch user preferences
      try {
        const prefs = await fetchUserPreferences(currentUser.id)
        setAutoDetectEnabledState(prefs.auto_detect_mode)

        // If user has a preferred mode, use that
        if (prefs.default_output_mode_id) {
          const preferredMode = fetchedModes.find((m) => m.id === prefs.default_output_mode_id)
          if (preferredMode) {
            setSelectedModeState(preferredMode)
          } else {
            setSelectedModeState(defaultMode)
          }
        } else {
          setSelectedModeState(defaultMode)
        }
      } catch {
        // User preferences not found, use defaults
        setSelectedModeState(defaultMode)
      }
    } catch (err) {
      console.error("[OutputModeContext] Failed to load modes:", err)
      setError(err instanceof Error ? err.message : "Failed to load output modes")
    } finally {
      setIsLoading(false)
    }
  }, [currentUser.id])

  // Initial load
  useEffect(() => {
    loadModesAndPreferences().then(() => setIsHydrated(true))
  }, [loadModesAndPreferences])

  // Set selected mode and persist preference
  const setSelectedMode = useCallback(
    async (mode: OutputMode | null) => {
      setSelectedModeState(mode)

      // Persist to user preferences
      try {
        await updateUserPreferences(currentUser.id, {
          default_output_mode_id: mode?.id || null,
        })
      } catch (err) {
        console.error("[OutputModeContext] Failed to save preference:", err)
      }
    },
    [currentUser.id]
  )

  // Set auto-detect and persist preference
  const setAutoDetectEnabled = useCallback(
    async (enabled: boolean) => {
      setAutoDetectEnabledState(enabled)

      try {
        await updateUserPreferences(currentUser.id, {
          auto_detect_mode: enabled,
        })
      } catch (err) {
        console.error("[OutputModeContext] Failed to save preference:", err)
      }
    },
    [currentUser.id]
  )

  // Detect mode for a query using backend classification
  const detectModeForQuery = useCallback(
    async (query: string): Promise<OutputMode | null> => {
      if (!autoDetectEnabled || modes.length === 0) {
        return selectedMode
      }

      try {
        const result = await classifyQuery(query)
        if (result.mode_id && result.confidence >= 0.3) {
          const detectedMode = modes.find((m) => m.id === result.mode_id)
          if (detectedMode) {
            return detectedMode
          }
        }
      } catch (err) {
        console.warn("[OutputModeContext] Query classification failed:", err)
      }

      return selectedMode
    },
    [autoDetectEnabled, modes, selectedMode]
  )

  // Refresh modes from backend
  const refreshModes = useCallback(async () => {
    await loadModesAndPreferences()
  }, [loadModesAndPreferences])

  // Don't render until hydrated to prevent SSR mismatch
  if (!isHydrated) {
    return null
  }

  return (
    <OutputModeContext.Provider
      value={{
        modes,
        selectedMode,
        autoDetectEnabled,
        isLoading,
        error,
        setSelectedMode,
        setAutoDetectEnabled,
        detectModeForQuery,
        refreshModes,
      }}
    >
      {children}
    </OutputModeContext.Provider>
  )
}

export function useOutputMode() {
  const context = useContext(OutputModeContext)
  if (context === undefined) {
    throw new Error("useOutputMode must be used within an OutputModeProvider")
  }
  return context
}
