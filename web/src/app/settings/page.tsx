"use client"

import { SettingsPage } from "@/components/settings/settings-page"

export default function SettingsPageRoute() {
  return (
    <main className="min-h-[calc(100vh-57px)] bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-muted-foreground text-sm">
            System health, sync management, and configuration
          </p>
        </div>
        <SettingsPage />
      </div>
    </main>
  )
}
