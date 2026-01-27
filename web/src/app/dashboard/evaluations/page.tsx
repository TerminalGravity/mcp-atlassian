"use client"

import { EvalDashboard } from "@/components/dashboard/eval-dashboard"

export default function EvaluationsPage() {
  return (
    <main className="min-h-[calc(100vh-57px)] bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Chat Evaluations</h1>
          <p className="text-muted-foreground text-sm">
            Quality metrics for Jira knowledge chat responses
          </p>
        </div>
        <EvalDashboard />
      </div>
    </main>
  )
}
