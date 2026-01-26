"use client"

import { useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { useUser, TEAM_MEMBERS } from "@/contexts/user-context"
import { IssueList } from "@/components/my-work/issue-list"
import { MyWorkChat } from "@/components/my-work/my-work-chat"

export default function MyWorkPage() {
  const { currentUser, setCurrentUser } = useUser()
  const searchParams = useSearchParams()

  // Override user from URL param
  useEffect(() => {
    const userParam = searchParams.get("user")
    if (userParam) {
      const found = TEAM_MEMBERS.find(
        u => u.name === userParam || u.id === userParam
      )
      if (found && found.id !== currentUser.id) {
        setCurrentUser(found)
      }
    }
  }, [searchParams, currentUser.id, setCurrentUser])

  return (
    <main className="min-h-[calc(100vh-57px)] bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">My Work</h1>
          <p className="text-muted-foreground text-sm">
            Issues assigned to {currentUser.name}
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Issue List - Takes 2/3 on large screens */}
          <div className="lg:col-span-2">
            <IssueList currentUser={currentUser.id} />
          </div>

          {/* Chat Sidebar - Takes 1/3 on large screens */}
          <div className="lg:col-span-1">
            <MyWorkChat currentUser={currentUser.id} />
          </div>
        </div>
      </div>
    </main>
  )
}
