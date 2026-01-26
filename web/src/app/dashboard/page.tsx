"use client"

import { useUser } from "@/contexts/user-context"
import { DashboardInsights } from "@/components/dashboard/dashboard-insights"

export default function DashboardPage() {
  const { currentUser } = useUser()

  return (
    <main className="min-h-[calc(100vh-57px)] bg-background">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground text-sm">
            AI-generated insights for {currentUser.name}
          </p>
        </div>
        <DashboardInsights currentUser={currentUser.id} />
      </div>
    </main>
  )
}
