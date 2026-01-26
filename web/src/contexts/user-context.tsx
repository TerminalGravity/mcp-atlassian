"use client"

import { createContext, useContext, useState, useEffect, type ReactNode } from "react"

export interface TeamMember {
  id: string
  name: string
  initials: string
}

export const TEAM_MEMBERS: TeamMember[] = [
  { id: "Josh Houghtelin", name: "Josh Houghtelin", initials: "JH" },
  { id: "Kim Robinson", name: "Kim Robinson", initials: "KR" },
  { id: "Joe Muto", name: "Joe Muto", initials: "JM" },
  { id: "Jack Felke", name: "Jack Felke", initials: "JF" },
  { id: "Suhrob Ulmasov (Stan)", name: "Stan Ulmasov", initials: "SU" },
  { id: "Zechariah Walden", name: "Zech Walden", initials: "ZW" },
  { id: "Niranjan Singh", name: "Niranjan Singh", initials: "NS" },
]

interface UserContextType {
  currentUser: TeamMember
  setCurrentUser: (user: TeamMember) => void
  teamMembers: TeamMember[]
}

const UserContext = createContext<UserContextType | undefined>(undefined)

const STORAGE_KEY = "jira-knowledge-user"

export function UserProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUserState] = useState<TeamMember>(TEAM_MEMBERS[0])
  const [isHydrated, setIsHydrated] = useState(false)

  // Load from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const found = TEAM_MEMBERS.find(u => u.id === saved)
      if (found) {
        setCurrentUserState(found)
      }
    }
    setIsHydrated(true)
  }, [])

  // Save to localStorage on change
  const setCurrentUser = (user: TeamMember) => {
    setCurrentUserState(user)
    localStorage.setItem(STORAGE_KEY, user.id)
  }

  // Prevent hydration mismatch by not rendering children until hydrated
  if (!isHydrated) {
    return null
  }

  return (
    <UserContext.Provider value={{ currentUser, setCurrentUser, teamMembers: TEAM_MEMBERS }}>
      {children}
    </UserContext.Provider>
  )
}

export function useUser() {
  const context = useContext(UserContext)
  if (context === undefined) {
    throw new Error("useUser must be used within a UserProvider")
  }
  return context
}
