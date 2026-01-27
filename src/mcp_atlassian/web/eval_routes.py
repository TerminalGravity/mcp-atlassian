"""FastAPI routes for evaluation API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from mcp_atlassian.eval.service import EvaluationService
from mcp_atlassian.eval.store import EvaluationStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval", tags=["evaluation"])

# Singleton instances
_store: EvaluationStore | None = None
_service: EvaluationService | None = None


def get_store() -> EvaluationStore:
    """Get or create evaluation store."""
    global _store
    if _store is None:
        _store = EvaluationStore()
    return _store


def get_service() -> EvaluationService:
    """Get or create evaluation service."""
    global _service
    if _service is None:
        _service = EvaluationService(store=get_store())
    return _service


# Request/Response models
class EvalLogRequest(BaseModel):
    """Request to log a chat turn for evaluation."""

    conversation_id: str
    turn_index: int
    query: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_issues: list[str] = Field(default_factory=list)
    response_text: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    model_id: str = ""
    output_mode_id: str | None = None
    timestamp: str | None = None


class EvalLogResponse(BaseModel):
    """Response from logging a chat turn."""

    id: str
    success: bool
    message: str = "Turn logged successfully"


class EvalRunRequest(BaseModel):
    """Request to start an evaluation run."""

    sample_size: int = 10
    fetch_issue_data: bool = False
    use_deepeval: bool = True
    use_ragas: bool = True


class EvalRunResponse(BaseModel):
    """Response from starting an evaluation run."""

    run_id: str
    status: str
    message: str


class EvalRunStatusResponse(BaseModel):
    """Response with evaluation run status."""

    run_id: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    total: int
    completed: int
    average_scores: dict[str, float | None] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    """Response with aggregated metrics."""

    total_evaluations: int
    evaluations_with_scores: int
    average_scores: dict[str, float | None]
    score_trends: dict[str, list[dict[str, Any]]]
    date_range: dict[str, str | None]


@router.post("/log", response_model=EvalLogResponse)
async def log_turn(request: EvalLogRequest) -> EvalLogResponse:
    """Log a chat turn for evaluation.

    This endpoint receives data from the frontend after each chat turn
    and stores it in MongoDB for later evaluation.
    """
    try:
        store = get_store()
        doc_id = store.log_turn(request.model_dump())

        return EvalLogResponse(
            id=doc_id,
            success=True,
            message="Turn logged successfully",
        )
    except Exception as e:
        logger.error(f"Failed to log turn: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/runs", response_model=EvalRunResponse)
async def start_run(
    request: EvalRunRequest,
    background_tasks: BackgroundTasks,
) -> EvalRunResponse:
    """Start a batch evaluation run.

    The evaluation runs in the background. Use GET /api/eval/runs/{id}
    to check status and results.
    """
    try:
        store = get_store()

        # Check if there are documents to evaluate
        pending = store.get_unevaluated(limit=1)
        if not pending:
            return EvalRunResponse(
                run_id="",
                status="skipped",
                message="No unevaluated documents found",
            )

        # Create run record
        run_id = store.create_run(request.sample_size)

        # Schedule background evaluation
        async def run_evaluation() -> None:
            service = EvaluationService(
                store=store,
                use_deepeval=request.use_deepeval,
                use_ragas=request.use_ragas,
            )
            await service.run_batch(
                sample_size=request.sample_size,
                fetch_issue_data=request.fetch_issue_data,
            )

        background_tasks.add_task(run_evaluation)

        return EvalRunResponse(
            run_id=run_id,
            status="started",
            message=f"Evaluation run started for {request.sample_size} turns",
        )
    except Exception as e:
        logger.error(f"Failed to start evaluation run: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/runs/{run_id}", response_model=EvalRunStatusResponse)
async def get_run_status(run_id: str) -> EvalRunStatusResponse:
    """Get status and results of an evaluation run."""
    store = get_store()
    run = store.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return EvalRunStatusResponse(
        run_id=run.run_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total=run.total_evaluations,
        completed=run.completed_evaluations,
        average_scores=run.average_scores.model_dump() if run.average_scores else {},
        errors=run.errors,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(days: int = 30) -> MetricsResponse:
    """Get aggregated metrics for dashboard display."""
    try:
        service = get_service()
        summary = service.get_metrics_summary(days)

        # Format date range for JSON
        date_range = {
            "start": summary.get("date_range", {}).get("start"),
            "end": summary.get("date_range", {}).get("end"),
        }
        if date_range["start"] and hasattr(date_range["start"], "isoformat"):
            date_range["start"] = date_range["start"].isoformat()
        if date_range["end"] and hasattr(date_range["end"], "isoformat"):
            date_range["end"] = date_range["end"].isoformat()

        return MetricsResponse(
            total_evaluations=summary.get("total_evaluations", 0),
            evaluations_with_scores=summary.get("evaluations_with_scores", 0),
            average_scores=summary.get("average_scores", {}),
            score_trends=summary.get("score_trends", {}),
            date_range=date_range,
        )
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/pending")
async def get_pending(limit: int = 20) -> dict[str, Any]:
    """Get list of pending (unevaluated) turns."""
    store = get_store()
    docs = store.get_unevaluated(limit=limit)

    return {
        "count": len(docs),
        "turns": [
            {
                "id": d.get("id"),
                "query": d.get("query", "")[:100],
                "timestamp": d.get("timestamp"),
                "tool_calls": len(d.get("tool_calls", [])),
                "issues_retrieved": len(d.get("retrieved_issues", [])),
            }
            for d in docs
        ],
    }


@router.get("/conversation/{conversation_id}")
async def get_conversation_turns(conversation_id: str) -> dict[str, Any]:
    """Get all evaluation data for a conversation."""
    store = get_store()
    turns = store.get_by_conversation(conversation_id)

    return {
        "conversation_id": conversation_id,
        "turn_count": len(turns),
        "turns": turns,
    }
