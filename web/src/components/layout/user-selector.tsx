"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ChevronDown } from "lucide-react"
import { useUser } from "@/contexts/user-context"

export function UserSelector() {
  const { currentUser, setCurrentUser, teamMembers } = useUser()
  const [showMenu, setShowMenu] = useState(false)

  // Close menu when clicking outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest("[data-user-dropdown]")) return
      setShowMenu(false)
    }
    if (showMenu) {
      const timer = setTimeout(() => {
        document.addEventListener("click", handleClick)
      }, 0)
      return () => {
        clearTimeout(timer)
        document.removeEventListener("click", handleClick)
      }
    }
  }, [showMenu])

  return (
    <div className="relative" data-user-dropdown>
      <button
        onClick={() => setShowMenu(!showMenu)}
        className="flex items-center gap-2 px-2.5 py-1.5 text-xs font-medium rounded-lg border bg-background hover:bg-muted transition-colors"
      >
        <div className="w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center text-[10px] font-semibold text-primary">
          {currentUser.initials}
        </div>
        <span className="hidden sm:inline max-w-[80px] truncate">
          {currentUser.name.split(" ")[0]}
        </span>
        <ChevronDown
          className={`w-3 h-3 text-muted-foreground transition-transform ${showMenu ? "rotate-180" : ""}`}
        />
      </button>
      <AnimatePresence>
        {showMenu && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.1 }}
            className="absolute right-0 top-full mt-2 w-52 rounded-lg border bg-popover shadow-xl z-[9999]"
          >
            <div className="px-3 py-2 border-b">
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                Role-play as
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {teamMembers.map((user) => (
                <button
                  key={user.id}
                  onClick={() => {
                    setCurrentUser(user)
                    setShowMenu(false)
                  }}
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors flex items-center gap-2 ${
                    currentUser.id === user.id ? "bg-accent" : ""
                  }`}
                >
                  <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-[10px] font-semibold text-primary">
                    {user.initials}
                  </div>
                  <span>{user.name}</span>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
