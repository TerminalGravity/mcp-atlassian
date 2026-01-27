"""FastAPI server for Jira Knowledge chat interface."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel

from mcp_atlassian.jira import JiraFacade
from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.embeddings import EmbeddingPipeline
from mcp_atlassian.vector.scheduler import SyncScheduler
from mcp_atlassian.vector.store import LanceDBStore
from mcp_atlassian.web.mongo import check_connection as check_mongo, close_connection as close_mongo
from mcp_atlassian.web.output_modes import router as output_modes_router, seed_default_templates

logger = logging.getLogger(__name__)

# Global instances
_store: LanceDBStore | None = None
_pipeline: EmbeddingPipeline | None = None
_openai: AsyncOpenAI | None = None
_jira: JiraFacade | None = None
_scheduler: SyncScheduler | None = None


def get_jira() -> JiraFacade:
    """Get or create Jira facade."""
    global _jira
    if _jira is None:
        _jira = JiraFacade()
    return _jira


def get_store() -> LanceDBStore:
    """Get or create the LanceDB store."""
    global _store
    if _store is None:
        _store = LanceDBStore()
    return _store


def get_pipeline() -> EmbeddingPipeline:
    """Get or create the embedding pipeline."""
    global _pipeline
    if _pipeline is None:
        _pipeline = EmbeddingPipeline()
    return _pipeline


def get_openai() -> AsyncOpenAI:
    """Get or create the OpenAI client."""
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI()
    return _openai


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    global _scheduler
    logger.info("Starting Jira Knowledge API server")
    # Pre-initialize connections
    get_store()
    get_pipeline()
    get_openai()

    # Initialize MongoDB and seed default templates
    if check_mongo():
        seeded = seed_default_templates()
        if seeded > 0:
            logger.info(f"Seeded {seeded} default output mode templates")
        logger.info("MongoDB connected successfully")
    else:
        logger.warning("MongoDB not available - output modes will not work")

    # Start background sync scheduler
    config = VectorConfig.from_env()
    if config.sync_interval_minutes > 0:
        try:
            jira = get_jira()
            _scheduler = SyncScheduler(jira, config=config)
            await _scheduler.start()
            logger.info(f"Background sync enabled (interval: {config.sync_interval_minutes} min)")
        except Exception as e:
            logger.warning(f"Background sync disabled - Jira not configured: {e}")
            _scheduler = None
    else:
        logger.info("Background sync disabled (VECTOR_SYNC_INTERVAL_MINUTES=0)")

    yield

    # Stop background sync scheduler
    if _scheduler:
        await _scheduler.stop()

    # Close MongoDB connection
    close_mongo()
    logger.info("Shutting down Jira Knowledge API server")


app = FastAPI(
    title="Jira Knowledge API",
    description="Semantic search API for Jira issues",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3006",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3006",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register output modes router
app.include_router(output_modes_router)


class SearchRequest(BaseModel):
    """Search request payload."""
    query: str


class JiraSource(BaseModel):
    """Jira issue source for search results."""
    issue_id: str
    summary: str
    status: str
    issue_type: str
    project_key: str
    assignee: str | None = None
    description_preview: str | None = None
    score: float


class SearchResponse(BaseModel):
    """Search response with answer and sources."""
    answer: str
    sources: list[JiraSource]


SYSTEM_PROMPT = """You are a helpful Jira knowledge assistant for All Digital Rewards (ADR).
You help users find information about Jira issues, past decisions, and project context.

Based on the search results provided, answer the user's question concisely and helpfully.
If the search results don't contain relevant information, say so honestly.

Guidelines:
- Be concise but thorough
- Reference specific issue keys when relevant (e.g., DS-1234)
- Highlight key findings, assignees, and statuses
- If multiple issues relate to the question, summarize the pattern
- Don't make up information not in the search results"""


async def generate_answer(query: str, results: list[dict[str, Any]]) -> str:
    """Generate an answer using GPT based on search results."""
    if not results:
        return "I couldn't find any relevant Jira issues matching your query. Try rephrasing or being more specific."

    # Format search results for context
    context_parts = []
    for i, r in enumerate(results[:10], 1):
        issue_id = r.get("issue_id", "Unknown")
        summary = r.get("summary", "No summary")
        status = r.get("status", "Unknown")
        assignee = r.get("assignee", "Unassigned")
        desc_preview = r.get("description_preview", "")[:500] if r.get("description_preview") else ""

        context_parts.append(
            f"{i}. [{issue_id}] {summary}\n"
            f"   Status: {status} | Assignee: {assignee}\n"
            f"   {desc_preview}"
        )

    context = "\n\n".join(context_parts)

    try:
        client = get_openai()
        response = await client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"User question: {query}\n\nRelevant Jira issues:\n\n{context}",
                },
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        return response.choices[0].message.content or "Unable to generate response."
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        # Fallback to simple summary
        issue_list = ", ".join(r.get("issue_id", "?") for r in results[:5])
        return f"Found {len(results)} relevant issues: {issue_list}. Check the sources below for details."


@app.post("/api/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Search Jira issues and generate an answer."""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    try:
        # Generate query embedding
        pipeline = get_pipeline()
        query_vector = await pipeline.embed(query)

        # Search the vector store
        store = get_store()
        results, _ = store.search_issues(query_vector, limit=10)

        # Generate answer
        answer = await generate_answer(query, results)

        # Format sources with clamped scores
        sources = [
            JiraSource(
                issue_id=r.get("issue_id", ""),
                summary=r.get("summary", ""),
                status=r.get("status", "Unknown"),
                issue_type=r.get("issue_type", "Unknown"),
                project_key=r.get("project_key", ""),
                assignee=r.get("assignee"),
                description_preview=r.get("description_preview", "")[:200] if r.get("description_preview") else None,
                score=max(0.0, min(1.0, r.get("score", 0.0))),  # Clamp to [0, 1]
            )
            for r in results
        ]

        return SearchResponse(answer=answer, sources=sources)

    except Exception as e:
        logger.exception(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    store = get_store()
    stats = store.get_stats()
    response = {
        "status": "healthy",
        "indexed_issues": stats.get("total_issues", 0),
        "projects": stats.get("projects", []),
    }
    # Include sync status if scheduler is running
    if _scheduler:
        response["sync"] = _scheduler.status
    return response


@app.get("/api/sync/status")
async def sync_status():
    """Get background sync status."""
    if not _scheduler:
        return {
            "enabled": False,
            "message": "Background sync not configured"
        }
    return {
        "enabled": True,
        **_scheduler.status
    }


@app.post("/api/sync/trigger")
async def trigger_sync():
    """Manually trigger an incremental sync."""
    if not _scheduler:
        raise HTTPException(
            status_code=503,
            detail="Background sync not configured. Set VECTOR_SYNC_INTERVAL_MINUTES > 0"
        )
    try:
        result = await _scheduler.run_once()
        return {
            "success": True,
            "issues_processed": result.issues_processed,
            "issues_embedded": result.issues_embedded,
            "duration_seconds": result.duration_seconds,
            "errors": len(result.errors),
        }
    except Exception as e:
        logger.error(f"Manual sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VectorSearchRequest(BaseModel):
    """Vector search request."""
    query: str
    limit: int = 10


class JQLSearchRequest(BaseModel):
    """JQL search request."""
    jql: str
    limit: int = 10


@app.post("/api/vector-search")
async def vector_search(request: VectorSearchRequest):
    """Search issues using semantic/vector search."""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    try:
        logger.info(f"Vector search: query='{query}', limit={request.limit}")
        pipeline = get_pipeline()
        query_vector = await pipeline.embed(query)
        logger.info(f"Generated embedding with {len(query_vector)} dimensions")

        store = get_store()
        stats = store.get_stats()
        logger.info(f"Vector store stats: {stats.get('total_issues', 0)} issues indexed")

        results, total_count = store.search_issues(query_vector, limit=request.limit)
        logger.info(f"Vector search returned {len(results)} results (total matching: {total_count})")

        # Format results
        issues = [
            {
                "issue_id": r.get("issue_id", ""),
                "summary": r.get("summary", ""),
                "status": r.get("status", "Unknown"),
                "issue_type": r.get("issue_type", "Unknown"),
                "project_key": r.get("project_key", ""),
                "assignee": r.get("assignee"),
                "description_preview": r.get("description_preview", "")[:300] if r.get("description_preview") else None,
                "labels": r.get("labels", []),
                "score": max(0.0, min(1.0, r.get("score", 0.0))),
            }
            for r in results
        ]

        return {"issues": issues, "count": len(issues)}

    except Exception as e:
        logger.exception(f"Vector search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class GenerateAnswerRequest(BaseModel):
    """Generate answer request."""
    query: str
    issues: list[dict[str, Any]]


@app.post("/api/generate-answer")
async def generate_answer_endpoint(request: GenerateAnswerRequest):
    """Generate an answer from search results using LLM."""
    try:
        answer = await generate_answer(request.query, request.issues)
        return {"answer": answer}
    except Exception as e:
        logger.exception(f"Answer generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jql-search")
async def jql_search(request: JQLSearchRequest):
    """Search issues using JQL (Jira Query Language)."""
    jql = request.jql.strip()
    if not jql:
        raise HTTPException(status_code=400, detail="JQL is required")

    # Try to get Jira client - return graceful error if not configured
    try:
        jira = get_jira()
    except Exception as e:
        logger.warning(f"Jira not configured: {e}")
        return {
            "issues": [],
            "count": 0,
            "error": "Jira connection not configured",
            "suggestion": "Use semantic search instead, or configure JIRA_URL and JIRA_API_TOKEN"
        }

    try:
        # Use the search method from JiraFacade - returns JiraSearchResult
        result = jira.search_issues(jql, limit=request.limit)

        # Format results to match vector search format
        issues = []
        for issue in result.issues:
            # Extract nested object values
            status_name = issue.status.name if issue.status else "Unknown"
            issue_type_name = issue.issue_type.name if issue.issue_type else "Unknown"
            assignee_name = issue.assignee.display_name if issue.assignee else None
            project_key = issue.project.key if issue.project else issue.key.split("-")[0]

            issues.append({
                "issue_id": issue.key,
                "summary": issue.summary,
                "status": status_name,
                "issue_type": issue_type_name,
                "project_key": project_key,
                "assignee": assignee_name,
                "description_preview": issue.description[:300] if issue.description else None,
                "labels": issue.labels or [],
                "score": 1.0,  # JQL results are exact matches
            })

        return {"issues": issues, "count": len(issues)}

    except Exception as e:
        # Return structured error instead of 500
        logger.warning(f"JQL search error: {e}")
        error_msg = str(e)
        suggestion = "Check your JQL syntax or use semantic search"
        if "401" in error_msg or "not authenticated" in error_msg.lower():
            suggestion = "Jira credentials may be invalid. Use semantic search instead."
        elif "404" in error_msg or "not found" in error_msg.lower():
            suggestion = "The specified project or field may not exist."
        return {
            "issues": [],
            "count": 0,
            "error": f"JQL search failed: {error_msg[:100]}",
            "suggestion": suggestion
        }


class LinkedIssuesRequest(BaseModel):
    """Request to get linked issues."""
    issueKey: str


@app.post("/api/linked-issues")
async def get_linked_issues(request: LinkedIssuesRequest):
    """Get issues linked to a specific issue."""
    issue_key = request.issueKey.strip()
    if not issue_key:
        raise HTTPException(status_code=400, detail="Issue key is required")

    # Try to get Jira client
    try:
        jira = get_jira()
    except Exception as e:
        logger.warning(f"Jira not configured: {e}")
        return {
            "issues": [],
            "count": 0,
            "error": "Jira connection not configured"
        }

    try:
        # Get raw issue data with links using the underlying Jira client
        raw_issue = jira.jira.get_issue(issue_key)

        # Extract linked issue keys from the raw issue data
        linked_keys: list[str] = []
        issuelinks = raw_issue.get('fields', {}).get('issuelinks', [])
        logger.info(f"Found {len(issuelinks)} issue links for {issue_key}")

        for link in issuelinks:
            # Links can be inward or outward
            if 'outwardIssue' in link:
                linked_keys.append(link['outwardIssue']['key'])
            if 'inwardIssue' in link:
                linked_keys.append(link['inwardIssue']['key'])

        if not linked_keys:
            return {"issues": [], "count": 0}

        # Fetch the linked issues
        jql = f"key in ({','.join(linked_keys)})"
        result = jira.search_issues(jql, limit=20)

        # Format results
        issues = []
        for iss in result.issues:
            status_name = iss.status.name if iss.status else "Unknown"
            issue_type_name = iss.issue_type.name if iss.issue_type else "Unknown"
            assignee_name = iss.assignee.display_name if iss.assignee else None
            project_key = iss.project.key if iss.project else iss.key.split("-")[0]

            issues.append({
                "issue_id": iss.key,
                "summary": iss.summary,
                "status": status_name,
                "issue_type": issue_type_name,
                "project_key": project_key,
                "assignee": assignee_name,
                "description_preview": iss.description[:300] if iss.description else None,
                "score": 1.0,
            })

        return {"issues": issues, "count": len(issues)}

    except Exception as e:
        logger.warning(f"Linked issues error for {issue_key}: {e}")
        return {
            "issues": [],
            "count": 0,
            "error": f"Failed to get linked issues: {str(e)[:100]}"
        }


def main():
    """Run the server."""
    import uvicorn
    uvicorn.run(
        "mcp_atlassian.web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
