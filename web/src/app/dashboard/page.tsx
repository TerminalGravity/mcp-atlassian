"use client"

import { useUser } from "@/contexts/user-context"
import { DashboardView } from "@/components/dashboard/dashboard-view"

export default function DashboardPage() {
  const { currentUser } = useUser()

  return (
    <main className="min-h-[calc(100vh-57px)] bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground text-sm">
            Jira overview for {currentUser.name}
          </p>
        </div>
        <DashboardView currentUser={currentUser.id} />
      </div>
    </main>
  )
}
