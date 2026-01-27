"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  X,
  Plus,
  Trash2,
  Copy,
  Edit2,
  Save,
  AlertCircle,
  Sparkles,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  type OutputMode,
  type OutputModeCreate,
  type OutputModeUpdate,
  createOutputMode,
  updateOutputMode,
  deleteOutputMode,
  cloneOutputMode,
  classifyQuery,
} from "@/lib/api"
import { useOutputMode } from "@/contexts/output-mode-context"
import { useUser } from "@/contexts/user-context"

interface OutputModeEditorProps {
  isOpen: boolean
  onClose: () => void
}

type EditorMode = "list" | "create" | "edit"

const DEFAULT_NEW_MODE: OutputModeCreate = {
  name: "",
  display_name: "",
  description: "",
  query_patterns: {
    keywords: [],
    regex: [],
    priority: 10,
  },
  system_prompt_sections: {
    formatting: "",
    behavior: null,
    constraints: null,
  },
  is_default: false,
}

export function OutputModeEditor({ isOpen, onClose }: OutputModeEditorProps) {
  const { modes, refreshModes } = useOutputMode()
  const { currentUser } = useUser()
  const [editorMode, setEditorMode] = useState<EditorMode>("list")
  const [editingMode, setEditingMode] = useState<OutputMode | null>(null)
  const [formData, setFormData] = useState<OutputModeCreate>(DEFAULT_NEW_MODE)
  const [keywordsText, setKeywordsText] = useState("")
  const [regexText, setRegexText] = useState("")
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testQuery, setTestQuery] = useState("")
  const [testResult, setTestResult] = useState<{
    mode_name: string | null
    confidence: number
    matched_pattern: string | null
  } | null>(null)
  const [isTesting, setIsTesting] = useState(false)

  // Reset form when opening
  useEffect(() => {
    if (isOpen) {
      setEditorMode("list")
      setEditingMode(null)
      setFormData(DEFAULT_NEW_MODE)
      setKeywordsText("")
      setRegexText("")
      setError(null)
    }
  }, [isOpen])

  // Sync keywords/regex text to form data
  useEffect(() => {
    setFormData((prev) => ({
      ...prev,
      query_patterns: {
        ...prev.query_patterns,
        keywords: keywordsText
          .split(",")
          .map((k) => k.trim())
          .filter(Boolean),
        regex: regexText
          .split("\n")
          .map((r) => r.trim())
          .filter(Boolean),
      },
    }))
  }, [keywordsText, regexText])

  const handleCreateNew = () => {
    setEditorMode("create")
    setEditingMode(null)
    setFormData(DEFAULT_NEW_MODE)
    setKeywordsText("")
    setRegexText("")
    setError(null)
  }

  const handleEdit = (mode: OutputMode) => {
    setEditorMode("edit")
    setEditingMode(mode)
    setFormData({
      name: mode.name,
      display_name: mode.display_name,
      description: mode.description,
      query_patterns: mode.query_patterns,
      system_prompt_sections: mode.system_prompt_sections,
      is_default: mode.is_default,
    })
    setKeywordsText(mode.query_patterns.keywords.join(", "))
    setRegexText(mode.query_patterns.regex.join("\n"))
    setError(null)
  }

  const handleClone = async (mode: OutputMode) => {
    try {
      setIsSaving(true)
      setError(null)
      await cloneOutputMode(mode.id, currentUser.id)
      await refreshModes()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clone mode")
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async (mode: OutputMode) => {
    if (!confirm(`Delete "${mode.display_name}"? This cannot be undone.`)) {
      return
    }

    try {
      setIsSaving(true)
      setError(null)
      await deleteOutputMode(mode.id, currentUser.id)
      await refreshModes()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete mode")
    } finally {
      setIsSaving(false)
    }
  }

  const handleSave = async () => {
    // Validate required fields
    if (!formData.name.trim()) {
      setError("Name is required")
      return
    }
    if (!formData.display_name.trim()) {
      setError("Display name is required")
      return
    }
    if (!formData.system_prompt_sections.formatting.trim()) {
      setError("Formatting instructions are required")
      return
    }

    try {
      setIsSaving(true)
      setError(null)

      if (editorMode === "create") {
        await createOutputMode(formData, currentUser.id)
      } else if (editorMode === "edit" && editingMode) {
        const update: OutputModeUpdate = {
          name: formData.name,
          display_name: formData.display_name,
          description: formData.description,
          query_patterns: formData.query_patterns,
          system_prompt_sections: formData.system_prompt_sections,
          is_default: formData.is_default,
        }
        await updateOutputMode(editingMode.id, update, currentUser.id)
      }

      await refreshModes()
      setEditorMode("list")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save mode")
    } finally {
      setIsSaving(false)
    }
  }

  const handleCancel = () => {
    setEditorMode("list")
    setEditingMode(null)
    setError(null)
  }

  const handleTestPattern = async () => {
    if (!testQuery.trim()) return
    setIsTesting(true)
    try {
      const result = await classifyQuery(testQuery)
      setTestResult(result)
    } catch (err) {
      console.error("Pattern test failed:", err)
    } finally {
      setIsTesting(false)
    }
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          onClick={(e) => e.stopPropagation()}
          className="bg-background border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-violet-500" />
              <h2 className="text-lg font-semibold">
                {editorMode === "list"
                  ? "Output Modes"
                  : editorMode === "create"
                    ? "Create Output Mode"
                    : `Edit: ${editingMode?.display_name}`}
              </h2>
            </div>
            <Button variant="ghost" size="icon-sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* Error Banner */}
          {error && (
            <div className="px-6 py-3 bg-destructive/10 border-b border-destructive/20 flex items-center gap-2 text-destructive">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="text-sm">{error}</span>
            </div>
          )}

          {/* Content */}
          <div className="flex-1 overflow-y-auto">
            {editorMode === "list" ? (
              <div className="p-4 space-y-4">
                {/* Pattern Test */}
                <div className="p-3 rounded-lg bg-muted/50 border">
                  <label className="text-xs font-medium text-muted-foreground mb-2 block">
                    Test Pattern Detection
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={testQuery}
                      onChange={(e) => setTestQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleTestPattern()}
                      placeholder="Try a query..."
                      className="flex-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleTestPattern}
                      disabled={isTesting || !testQuery.trim()}
                    >
                      {isTesting ? "..." : "Test"}
                    </Button>
                  </div>
                  {/* Quick test queries */}
                  <div className="flex flex-wrap gap-1 mt-2">
                    {[
                      "list all bugs",
                      "what is changemaker?",
                      "who owns DS-1234?",
                      "analyze failures",
                      "sprint status",
                    ].map((q) => (
                      <button
                        key={q}
                        onClick={() => {
                          setTestQuery(q)
                          // Auto-test after setting
                          setTimeout(async () => {
                            setIsTesting(true)
                            try {
                              const result = await classifyQuery(q)
                              setTestResult(result)
                            } finally {
                              setIsTesting(false)
                            }
                          }, 0)
                        }}
                        className="text-[10px] px-2 py-1 rounded-full border hover:bg-accent transition-colors"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                  {testResult && (
                    <div className="mt-2 p-2 rounded bg-background border text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">
                          {testResult.mode_name ? (
                            <span className="text-violet-600 dark:text-violet-400">
                              {testResult.mode_name}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">No match</span>
                          )}
                        </span>
                        <span className="text-muted-foreground">
                          {(testResult.confidence * 100).toFixed(0)}% confidence
                        </span>
                      </div>
                      {testResult.matched_pattern && (
                        <div className="text-muted-foreground mt-1 font-mono">
                          Matched: {testResult.matched_pattern}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Create new button */}
                <Button
                  variant="outline"
                  onClick={handleCreateNew}
                  className="w-full justify-start gap-2 h-12"
                >
                  <Plus className="w-4 h-4" />
                  Create new output mode
                </Button>

                {/* Mode list */}
                {modes.map((mode) => {
                  // Get example triggers for this mode
                  const exampleKeywords = mode.query_patterns.keywords.slice(0, 3)
                  return (
                    <div
                      key={mode.id}
                      className="flex items-start gap-3 p-3 rounded-lg border hover:bg-muted/50 transition-colors group"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{mode.display_name}</span>
                          {mode.is_default && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
                              default
                            </span>
                          )}
                          {mode.owner_id === null && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                              system
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {mode.description}
                        </p>
                        {exampleKeywords.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {exampleKeywords.map((kw) => (
                              <span
                                key={kw}
                                className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400 font-mono"
                              >
                                {kw}
                              </span>
                            ))}
                            {mode.query_patterns.keywords.length > 3 && (
                              <span className="text-[10px] text-muted-foreground">
                                +{mode.query_patterns.keywords.length - 3} more
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          onClick={() => handleClone(mode)}
                          title="Clone"
                        >
                          <Copy className="w-3 h-3" />
                        </Button>
                        {mode.owner_id !== null && (
                          <>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => handleEdit(mode)}
                              title="Edit"
                            >
                              <Edit2 className="w-3 h-3" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => handleDelete(mode)}
                              title="Delete"
                              className="text-destructive hover:text-destructive"
                            >
                              <Trash2 className="w-3 h-3" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              /* Create/Edit Form */
              <div className="p-6 space-y-4">
                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Internal Name
                    </label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) =>
                        setFormData({ ...formData, name: e.target.value.toLowerCase().replace(/\s+/g, "_") })
                      }
                      placeholder="my_custom_mode"
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Display Name
                    </label>
                    <input
                      type="text"
                      value={formData.display_name}
                      onChange={(e) =>
                        setFormData({ ...formData, display_name: e.target.value })
                      }
                      placeholder="My Custom Mode"
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-muted-foreground">
                    Description
                  </label>
                  <input
                    type="text"
                    value={formData.description}
                    onChange={(e) =>
                      setFormData({ ...formData, description: e.target.value })
                    }
                    placeholder="Brief description of when to use this mode"
                    className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>

                {/* Query Patterns */}
                <div className="border rounded-lg p-4 space-y-3">
                  <h3 className="text-sm font-medium">Auto-Detection Patterns</h3>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Keywords (comma-separated)
                    </label>
                    <input
                      type="text"
                      value={keywordsText}
                      onChange={(e) => setKeywordsText(e.target.value)}
                      placeholder="list, show all, compare"
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Regex Patterns (one per line)
                    </label>
                    <textarea
                      value={regexText}
                      onChange={(e) => setRegexText(e.target.value)}
                      placeholder="^list\s+&#10;^show\s+(all|me)"
                      rows={3}
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring font-mono"
                    />
                  </div>
                </div>

                {/* System Prompt Sections */}
                <div className="border rounded-lg p-4 space-y-3">
                  <h3 className="text-sm font-medium">Response Formatting</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-medium text-muted-foreground">
                        Formatting Instructions *
                      </label>
                      <textarea
                        value={formData.system_prompt_sections.formatting}
                        onChange={(e) =>
                          setFormData({
                            ...formData,
                            system_prompt_sections: {
                              ...formData.system_prompt_sections,
                              formatting: e.target.value,
                            },
                          })
                        }
                        placeholder="Format your response as..."
                        rows={6}
                        className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring font-mono text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-muted-foreground">
                        Preview
                      </label>
                      <div className="mt-1 p-3 text-xs border rounded-md bg-muted/30 h-[156px] overflow-y-auto prose prose-xs dark:prose-invert max-w-none">
                        {formData.system_prompt_sections.formatting ? (
                          <pre className="whitespace-pre-wrap text-[11px] text-muted-foreground font-sans">
                            {formData.system_prompt_sections.formatting}
                          </pre>
                        ) : (
                          <span className="text-muted-foreground italic">
                            Enter formatting instructions to see preview
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Behavior (optional)
                    </label>
                    <textarea
                      value={formData.system_prompt_sections.behavior || ""}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          system_prompt_sections: {
                            ...formData.system_prompt_sections,
                            behavior: e.target.value || null,
                          },
                        })
                      }
                      placeholder="Additional behavior instructions..."
                      rows={2}
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground">
                      Constraints (optional)
                    </label>
                    <textarea
                      value={formData.system_prompt_sections.constraints || ""}
                      onChange={(e) =>
                        setFormData({
                          ...formData,
                          system_prompt_sections: {
                            ...formData.system_prompt_sections,
                            constraints: e.target.value || null,
                          },
                        })
                      }
                      placeholder="Length limits, required elements..."
                      rows={2}
                      className="w-full mt-1 px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          {editorMode !== "list" && (
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t">
              <Button variant="outline" onClick={handleCancel} disabled={isSaving}>
                Cancel
              </Button>
              <Button onClick={handleSave} disabled={isSaving}>
                {isSaving ? (
                  <>Saving...</>
                ) : (
                  <>
                    <Save className="w-4 h-4 mr-1" />
                    Save
                  </>
                )}
              </Button>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
