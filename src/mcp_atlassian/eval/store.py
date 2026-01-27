"""MongoDB operations for evaluation storage."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from pymongo.database import Database

from mcp_atlassian.eval.schemas import (
    EvaluationDocument,
    EvaluationRunResult,
    EvaluationScores,
    MetricsSummary,
)
from mcp_atlassian.web.mongo import get_database

logger = logging.getLogger(__name__)

COLLECTION_NAME = "evaluations"
RUNS_COLLECTION = "evaluation_runs"


class EvaluationStore:
    """MongoDB store for evaluation data."""

    def __init__(self, db: Database[dict[str, Any]] | None = None) -> None:
        """Initialize the evaluation store."""
        self._db = db

    @property
    def db(self) -> Database[dict[str, Any]]:
        """Get the database instance."""
        if self._db is None:
            self._db = get_database()
        return self._db

    @property
    def collection(self) -> Any:
        """Get the evaluations collection."""
        return self.db[COLLECTION_NAME]

    @property
    def runs_collection(self) -> Any:
        """Get the evaluation runs collection."""
        return self.db[RUNS_COLLECTION]

    def log_turn(self, data: dict[str, Any]) -> str:
        """Log a conversation turn for evaluation.

        Args:
            data: Dictionary containing turn data matching EvaluationDocument schema

        Returns:
            The inserted document ID as string
        """
        # Ensure timestamp is present
        if "timestamp" not in data:
            data["timestamp"] = datetime.utcnow()
        elif isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(
                data["timestamp"].replace("Z", "+00:00")
            )

        # Initialize empty scores
        if "scores" not in data:
            data["scores"] = {}

        result = self.collection.insert_one(data)
        logger.info(f"Logged evaluation turn: {result.inserted_id}")
        return str(result.inserted_id)

    def get_turn(self, doc_id: str) -> EvaluationDocument | None:
        """Get a specific evaluation document by ID."""
        from bson import ObjectId

        doc = self.collection.find_one({"_id": ObjectId(doc_id)})
        if doc:
            doc["id"] = str(doc.pop("_id"))
            return EvaluationDocument(**doc)
        return None

    def get_unevaluated(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get turns that haven't been evaluated yet."""
        cursor = self.collection.find(
            {"evaluated_at": None}, limit=limit
        ).sort("timestamp", -1)

        results = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
        return results

    def get_by_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """Get all turns for a conversation."""
        cursor = self.collection.find(
            {"conversation_id": conversation_id}
        ).sort("turn_index", 1)

        results = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
        return results

    def update_scores(
        self, doc_id: str, scores: EvaluationScores
    ) -> bool:
        """Update scores for an evaluation document."""
        from bson import ObjectId

        result = self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {
                "$set": {
                    "scores": scores.model_dump(),
                    "evaluated_at": datetime.utcnow(),
                }
            },
        )
        return result.modified_count > 0

    def create_run(self, sample_size: int) -> str:
        """Create a new evaluation run."""
        run_id = str(uuid.uuid4())
        run = EvaluationRunResult(
            run_id=run_id,
            status="pending",
            total_evaluations=sample_size,
        )
        self.runs_collection.insert_one(run.model_dump())
        return run_id

    def get_run(self, run_id: str) -> EvaluationRunResult | None:
        """Get evaluation run status."""
        doc = self.runs_collection.find_one({"run_id": run_id})
        if doc:
            doc.pop("_id", None)
            return EvaluationRunResult(**doc)
        return None

    def update_run(
        self,
        run_id: str,
        status: str | None = None,
        completed_evaluations: int | None = None,
        average_scores: EvaluationScores | None = None,
        error: str | None = None,
    ) -> bool:
        """Update an evaluation run."""
        update: dict[str, Any] = {}

        if status:
            update["status"] = status
            if status == "completed":
                update["completed_at"] = datetime.utcnow()

        if completed_evaluations is not None:
            update["completed_evaluations"] = completed_evaluations

        if average_scores:
            update["average_scores"] = average_scores.model_dump()

        if error:
            update["$push"] = {"errors": error}
            result = self.runs_collection.update_one(
                {"run_id": run_id},
                {"$push": {"errors": error}, "$set": {k: v for k, v in update.items() if k != "$push"}},
            )
        else:
            result = self.runs_collection.update_one(
                {"run_id": run_id}, {"$set": update}
            )

        return result.modified_count > 0

    def get_metrics_summary(self, days: int = 30) -> MetricsSummary:
        """Get aggregated metrics for dashboard."""
        start_date = datetime.utcnow() - timedelta(days=days)

        # Count total and scored evaluations
        total = self.collection.count_documents({"timestamp": {"$gte": start_date}})
        with_scores = self.collection.count_documents(
            {"timestamp": {"$gte": start_date}, "evaluated_at": {"$ne": None}}
        )

        # Calculate average scores
        pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}, "evaluated_at": {"$ne": None}}},
            {
                "$group": {
                    "_id": None,
                    "avg_tool_selection": {"$avg": "$scores.tool_selection_accuracy"},
                    "avg_retrieval_precision": {"$avg": "$scores.retrieval_precision"},
                    "avg_retrieval_recall": {"$avg": "$scores.retrieval_recall"},
                    "avg_faithfulness": {"$avg": "$scores.faithfulness"},
                    "avg_citation_accuracy": {"$avg": "$scores.citation_accuracy"},
                }
            },
        ]
        avg_result = list(self.collection.aggregate(pipeline))

        avg_scores = EvaluationScores()
        if avg_result:
            r = avg_result[0]
            avg_scores = EvaluationScores(
                tool_selection_accuracy=r.get("avg_tool_selection"),
                retrieval_precision=r.get("avg_retrieval_precision"),
                retrieval_recall=r.get("avg_retrieval_recall"),
                faithfulness=r.get("avg_faithfulness"),
                citation_accuracy=r.get("avg_citation_accuracy"),
            )

        # Get score trends by day
        trend_pipeline = [
            {"$match": {"timestamp": {"$gte": start_date}, "evaluated_at": {"$ne": None}}},
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}
                    },
                    "avg_faithfulness": {"$avg": "$scores.faithfulness"},
                    "avg_citation_accuracy": {"$avg": "$scores.citation_accuracy"},
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        trend_result = list(self.collection.aggregate(trend_pipeline))

        score_trends: dict[str, list[dict[str, Any]]] = {
            "faithfulness": [],
            "citation_accuracy": [],
        }
        for t in trend_result:
            date = t["_id"]
            if t.get("avg_faithfulness") is not None:
                score_trends["faithfulness"].append(
                    {"date": date, "value": t["avg_faithfulness"]}
                )
            if t.get("avg_citation_accuracy") is not None:
                score_trends["citation_accuracy"].append(
                    {"date": date, "value": t["avg_citation_accuracy"]}
                )

        return MetricsSummary(
            total_evaluations=total,
            evaluations_with_scores=with_scores,
            average_scores=avg_scores,
            score_trends=score_trends,
            date_range={"start": start_date, "end": datetime.utcnow()},
        )
