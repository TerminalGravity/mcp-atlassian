"use client"

import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import { Sun, Moon, Monitor } from "lucide-react"
import { Button } from "@/components/ui/button"
import { motion, AnimatePresence } from "framer-motion"
import { cn } from "@/lib/utils"

const themes = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "dark", icon: Moon, label: "Dark" },
  { value: "system", icon: Monitor, label: "System" },
] as const

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  const [showMenu, setShowMenu] = useState(false)

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true)
  }, [])

  // Close menu on click outside
  useEffect(() => {
    if (!showMenu) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest("[data-theme-toggle]")) {
        setShowMenu(false)
      }
    }
    const timer = setTimeout(() => {
      document.addEventListener("click", handleClick)
    }, 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener("click", handleClick)
    }
  }, [showMenu])

  if (!mounted) {
    return (
      <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
        <Monitor className="w-4 h-4" />
      </Button>
    )
  }

  const currentTheme = themes.find((t) => t.value === theme) || themes[2]
  const CurrentIcon = currentTheme.icon

  return (
    <div className="relative" data-theme-toggle>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setShowMenu(!showMenu)}
        className="h-8 w-8 p-0"
        aria-label={`Current theme: ${currentTheme.label}`}
      >
        <CurrentIcon className="w-4 h-4" />
      </Button>

      <AnimatePresence>
        {showMenu && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.1 }}
            className="absolute right-0 top-full mt-2 rounded-lg border bg-popover shadow-xl z-50 overflow-hidden"
          >
            {themes.map((t) => {
              const Icon = t.icon
              return (
                <button
                  key={t.value}
                  onClick={() => {
                    setTheme(t.value)
                    setShowMenu(false)
                  }}
                  className={cn(
                    "flex items-center gap-2 w-full px-3 py-2 text-sm transition-colors",
                    "hover:bg-accent",
                    theme === t.value && "bg-accent"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{t.label}</span>
                </button>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
