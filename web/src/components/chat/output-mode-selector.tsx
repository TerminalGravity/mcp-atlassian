"use client"

import { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ChevronDown,
  Sparkles,
  Settings2,
  Check,
  FileText,
  Table2,
  MessageSquare,
  Search,
  BarChart3,
} from "lucide-react"
import { useOutputMode } from "@/contexts/output-mode-context"
import { Button } from "@/components/ui/button"
import type { OutputMode } from "@/lib/api"

// Mode icons mapping
const MODE_ICONS: Record<string, React.ElementType> = {
  narrative: FileText,
  table: Table2,
  brief: MessageSquare,
  analysis: Search,
  status: BarChart3,
}

interface OutputModeSelectorProps {
  onManageModes?: () => void
}

export function OutputModeSelector({ onManageModes }: OutputModeSelectorProps) {
  const {
    modes,
    selectedMode,
    autoDetectEnabled,
    isLoading,
    setSelectedMode,
    setAutoDetectEnabled,
  } = useOutputMode()

  const [showMenu, setShowMenu] = useState(false)

  const handleSelectMode = useCallback((mode: OutputMode) => {
    setSelectedMode(mode)
    setShowMenu(false)
  }, [setSelectedMode])

  const handleToggleAutoDetect = useCallback(() => {
    setAutoDetectEnabled(!autoDetectEnabled)
  }, [autoDetectEnabled, setAutoDetectEnabled])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd/Ctrl + Shift + O to toggle menu
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "o") {
        e.preventDefault()
        setShowMenu((prev) => !prev)
        return
      }
      // Escape to close
      if (e.key === "Escape" && showMenu) {
        setShowMenu(false)
        return
      }
      // Number keys 1-5 to select mode when menu is open
      if (showMenu && /^[1-5]$/.test(e.key)) {
        const index = parseInt(e.key) - 1
        if (modes[index]) {
          e.preventDefault()
          handleSelectMode(modes[index])
        }
        return
      }
      // 'A' key to toggle auto-detect when menu is open
      if (showMenu && e.key.toLowerCase() === "a" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        handleToggleAutoDetect()
      }
    }
    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [showMenu, modes, handleSelectMode, handleToggleAutoDetect])

  const getModeIcon = useCallback((modeName: string) => {
    return MODE_ICONS[modeName] || Sparkles
  }, [])

  if (isLoading || modes.length === 0) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-1.5 text-xs font-medium rounded-lg border bg-background text-muted-foreground">
        <Sparkles className="w-3 h-3 animate-pulse" />
        <span>Loading...</span>
      </div>
    )
  }

  return (
    <div className="relative" data-dropdown>
      <button
        onClick={() => setShowMenu(!showMenu)}
        className="flex items-center gap-2 px-2.5 py-1.5 text-xs font-medium rounded-lg border bg-background hover:bg-muted transition-colors"
      >
        <Sparkles className="w-3 h-3 text-violet-500" />
        <span className="text-muted-foreground hidden sm:inline">Output:</span>
        <span className="max-w-[100px] truncate">
          {autoDetectEnabled ? "Auto" : selectedMode?.display_name || "Select"}
        </span>
        <ChevronDown
          className={`w-3 h-3 text-muted-foreground transition-transform ${showMenu ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence>
        {showMenu && (
          <>
            {/* Backdrop to close menu */}
            <div
              className="fixed inset-0 z-[9998]"
              onClick={() => setShowMenu(false)}
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -4 }}
              transition={{ duration: 0.15 }}
              className="absolute right-0 top-full mt-2 w-64 rounded-lg border bg-popover shadow-xl z-[9999]"
            >
              {/* Auto-detect toggle */}
              <div className="p-2 border-b">
                <button
                  onClick={handleToggleAutoDetect}
                  className="w-full flex items-center justify-between px-2 py-2 rounded-md hover:bg-accent transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-violet-500" />
                    <span className="text-sm font-medium">Auto-detect</span>
                    <kbd className="px-1.5 py-0.5 rounded bg-muted border text-[9px] font-mono text-muted-foreground">
                      A
                    </kbd>
                  </div>
                  <div
                    className={`w-8 h-4 rounded-full transition-colors ${
                      autoDetectEnabled ? "bg-violet-500" : "bg-muted"
                    }`}
                  >
                    <motion.div
                      className="w-3 h-3 rounded-full bg-white shadow-sm mt-0.5"
                      animate={{ x: autoDetectEnabled ? 17 : 3 }}
                      transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    />
                  </div>
                </button>
                <p className="text-[10px] text-muted-foreground px-2 mt-1">
                  Automatically choose format based on your query
                </p>
              </div>

              {/* Mode list */}
              <div className="max-h-[300px] overflow-y-auto py-1">
                {modes.map((mode, index) => {
                  const ModeIcon = getModeIcon(mode.name)
                  const isSelected = selectedMode?.id === mode.id && !autoDetectEnabled
                  return (
                    <button
                      key={mode.id}
                      onClick={() => handleSelectMode(mode)}
                      className={`w-full px-3 py-2.5 text-left hover:bg-accent transition-colors flex items-start gap-3 ${
                        isSelected ? "bg-accent" : ""
                      }`}
                    >
                      <div
                        className={`w-8 h-8 rounded-md flex items-center justify-center shrink-0 ${
                          isSelected
                            ? "bg-violet-500 text-white"
                            : "bg-muted text-muted-foreground"
                        }`}
                      >
                        <ModeIcon className="w-4 h-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{mode.display_name}</span>
                          {mode.is_default && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400">
                              default
                            </span>
                          )}
                          <span className="text-[10px] text-muted-foreground ml-auto">
                            {index + 1}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {mode.description}
                        </p>
                      </div>
                      {isSelected && (
                        <Check className="w-4 h-4 text-violet-500 shrink-0 mt-2" />
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Manage modes link + keyboard hint */}
              <div className="p-2 border-t">
                {onManageModes && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setShowMenu(false)
                      onManageModes()
                    }}
                    className="w-full justify-start text-xs text-muted-foreground hover:text-foreground"
                  >
                    <Settings2 className="w-3 h-3 mr-2" />
                    Manage output modes
                  </Button>
                )}
                <div className="flex items-center justify-center gap-1 mt-2 text-[10px] text-muted-foreground">
                  <kbd className="px-1.5 py-0.5 rounded bg-muted border text-[9px] font-mono">
                    {typeof navigator !== "undefined" && navigator.platform?.includes("Mac")
                      ? "⌘"
                      : "Ctrl"}
                  </kbd>
                  <span>+</span>
                  <kbd className="px-1.5 py-0.5 rounded bg-muted border text-[9px] font-mono">
                    ⇧
                  </kbd>
                  <span>+</span>
                  <kbd className="px-1.5 py-0.5 rounded bg-muted border text-[9px] font-mono">
                    O
                  </kbd>
                  <span className="ml-1">to toggle</span>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
