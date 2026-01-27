"""Pydantic models for evaluation data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolCallData(BaseModel):
    """Data captured for a single tool call."""

    tool_name: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    latency_ms: int = 0
    error: str | None = None


class CitationData(BaseModel):
    """Citation reference in a response."""

    index: int
    issue_id: str


class EvaluationScores(BaseModel):
    """Evaluation scores for a single turn."""

    tool_selection_accuracy: float | None = None
    retrieval_precision: float | None = None
    retrieval_recall: float | None = None
    faithfulness: float | None = None
    citation_accuracy: float | None = None


class EvaluationDocument(BaseModel):
    """Document stored in MongoDB for each conversation turn."""

    conversation_id: str
    turn_index: int
    query: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Captured data
    tool_calls: list[ToolCallData] = Field(default_factory=list)
    retrieved_issues: list[str] = Field(default_factory=list)
    response_text: str = ""
    citations: list[CitationData] = Field(default_factory=list)

    # Scores (filled by offline evaluation)
    scores: EvaluationScores = Field(default_factory=EvaluationScores)

    # Metadata
    model_id: str = ""
    output_mode_id: str | None = None
    evaluated_at: datetime | None = None

    class Config:
        """Pydantic config."""

        json_encoders = {datetime: lambda v: v.isoformat()}


class EvaluationRunRequest(BaseModel):
    """Request to start an evaluation run."""

    sample_size: int = 10
    conversation_ids: list[str] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class EvaluationRunResult(BaseModel):
    """Result of an evaluation run."""

    run_id: str
    status: str = "pending"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    total_evaluations: int = 0
    completed_evaluations: int = 0
    average_scores: EvaluationScores = Field(default_factory=EvaluationScores)
    errors: list[str] = Field(default_factory=list)


class MetricsSummary(BaseModel):
    """Aggregated metrics for dashboard display."""

    total_evaluations: int = 0
    evaluations_with_scores: int = 0
    average_scores: EvaluationScores = Field(default_factory=EvaluationScores)
    score_trends: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    date_range: dict[str, datetime | None] = Field(
        default_factory=lambda: {"start": None, "end": None}
    )
