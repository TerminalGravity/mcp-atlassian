import { NextResponse } from "next/server"

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000"

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const user = searchParams.get("user")

  if (!user) {
    return NextResponse.json({ error: "User parameter required" }, { status: 400 })
  }

  try {
    // Build JQL to fetch user's issues
    const jql = `assignee = "${user}" AND resolution = Unresolved ORDER BY status ASC, updated DESC`

    const response = await fetch(`${BACKEND_URL}/api/jql-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jql, limit: 100 }),
    })

    if (!response.ok) {
      // Fallback: Try vector search if JQL fails
      console.log(`JQL search failed (${response.status}), trying vector search fallback`)

      const vectorResponse = await fetch(`${BACKEND_URL}/api/vector-search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: `issues assigned to ${user}`,
          limit: 50
        }),
      })

      if (!vectorResponse.ok) {
        return NextResponse.json(
          { error: "Failed to fetch issues from both JQL and vector search" },
          { status: 500 }
        )
      }

      const vectorData = await vectorResponse.json()
      // Filter to just this user's issues if possible
      const filteredIssues = vectorData.issues?.filter(
        (i: { assignee?: string }) => i.assignee === user
      ) || vectorData.issues || []

      return NextResponse.json({
        issues: filteredIssues,
        count: filteredIssues.length,
        note: "Results from vector search (JQL unavailable)"
      })
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error fetching user issues:", error)
    return NextResponse.json(
      { error: `Failed to fetch issues: ${error}` },
      { status: 500 }
    )
  }
}
