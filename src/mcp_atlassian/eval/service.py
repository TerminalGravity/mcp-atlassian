"""Evaluation service orchestrating all metrics."""

from __future__ import annotations

import logging
from typing import Any

from mcp_atlassian.eval.metrics.citation import CitationAccuracyMetric
from mcp_atlassian.eval.metrics.faithfulness import FaithfulnessMetric
from mcp_atlassian.eval.metrics.retrieval import (
    RetrievalMetrics,
    SimplifiedRetrievalMetrics,
)
from mcp_atlassian.eval.metrics.tool_accuracy import ToolAccuracyMetric
from mcp_atlassian.eval.schemas import EvaluationScores
from mcp_atlassian.eval.store import EvaluationStore

logger = logging.getLogger(__name__)


class EvaluationService:
    """Service for running evaluations on logged chat turns."""

    def __init__(
        self,
        store: EvaluationStore | None = None,
        use_deepeval: bool = True,
        use_ragas: bool = True,
    ) -> None:
        """Initialize the evaluation service.

        Args:
            store: Optional evaluation store instance
            use_deepeval: Whether to use DeepEval metrics (requires install)
            use_ragas: Whether to use RAGAS metrics (requires install)
        """
        self.store = store or EvaluationStore()
        self.use_deepeval = use_deepeval
        self.use_ragas = use_ragas

        # Initialize metrics
        self.citation_metric = CitationAccuracyMetric()
        self.faithfulness_metric = FaithfulnessMetric() if use_deepeval else None
        self.tool_metric = ToolAccuracyMetric()

        # Use RAGAS if available, otherwise simplified metrics
        if use_ragas:
            self.retrieval_metric: RetrievalMetrics | SimplifiedRetrievalMetrics = RetrievalMetrics()
        else:
            self.retrieval_metric = SimplifiedRetrievalMetrics()

    def run_single(
        self,
        doc_id: str,
        issue_data: list[dict[str, Any]] | None = None,
    ) -> EvaluationScores:
        """Run evaluation on a single logged turn.

        Args:
            doc_id: Document ID in MongoDB
            issue_data: Optional full issue data for faithfulness check

        Returns:
            EvaluationScores with all metrics
        """
        # Fetch the document
        turns = self.store.get_by_conversation(doc_id)
        if not turns:
            doc = self.store.collection.find_one({"_id": doc_id})
            if doc:
                doc["id"] = str(doc.pop("_id"))
                turns = [doc]

        if not turns:
            logger.warning(f"Document {doc_id} not found")
            return EvaluationScores()

        doc = turns[0] if isinstance(turns, list) else turns

        return self._run_metrics(doc, issue_data)

    def _run_metrics(
        self,
        doc: dict[str, Any],
        issue_data: list[dict[str, Any]] | None = None,
    ) -> EvaluationScores:
        """Run all metrics on a document.

        Args:
            doc: Evaluation document
            issue_data: Optional full issue data

        Returns:
            EvaluationScores
        """
        scores = EvaluationScores()

        query = doc.get("query", "")
        response_text = doc.get("response_text", "")
        tool_calls = doc.get("tool_calls", [])
        retrieved_issues = doc.get("retrieved_issues", [])

        # 1. Citation accuracy (always runs)
        try:
            citation_result = self.citation_metric.evaluate(
                response_text=response_text,
                retrieved_issues=retrieved_issues,
            )
            scores.citation_accuracy = citation_result.get("score")
        except Exception as e:
            logger.error(f"Citation metric failed: {e}")

        # 2. Tool selection accuracy (always runs)
        try:
            tool_result = self.tool_metric.run_assessment(
                query=query,
                tool_calls=tool_calls,
            )
            scores.tool_selection_accuracy = tool_result.get("score")
        except Exception as e:
            logger.error(f"Tool accuracy metric failed: {e}")

        # 3. Faithfulness (requires DeepEval and issue data)
        if self.faithfulness_metric and issue_data:
            try:
                faith_result = self.faithfulness_metric.evaluate(
                    query=query,
                    response_text=response_text,
                    retrieved_issues=issue_data,
                )
                scores.faithfulness = faith_result.get("score")
            except Exception as e:
                logger.error(f"Faithfulness metric failed: {e}")

        # 4. Retrieval quality
        if issue_data:
            try:
                retrieval_result = self.retrieval_metric.evaluate(
                    query=query,
                    response_text=response_text,
                    retrieved_issues=issue_data,
                )
                scores.retrieval_precision = retrieval_result.get("precision")
                scores.retrieval_recall = retrieval_result.get("recall")
            except Exception as e:
                logger.error(f"Retrieval metric failed: {e}")

        return scores

    async def run_batch(
        self,
        sample_size: int = 10,
        fetch_issue_data: bool = False,
    ) -> dict[str, Any]:
        """Run evaluation on a batch of unevaluated turns.

        Args:
            sample_size: Number of turns to evaluate
            fetch_issue_data: Whether to fetch full issue data for faithfulness

        Returns:
            Summary of evaluation results
        """
        # Get unevaluated documents
        docs = self.store.get_unevaluated(limit=sample_size)

        if not docs:
            return {
                "evaluated": 0,
                "message": "No unevaluated documents found",
            }

        # Create evaluation run
        run_id = self.store.create_run(len(docs))

        results: list[EvaluationScores] = []
        errors: list[str] = []

        for i, doc in enumerate(docs):
            try:
                doc_id = doc.get("id", "")

                # Optionally fetch full issue data
                issue_data = None
                if fetch_issue_data:
                    issue_data = await self._fetch_issue_data(
                        doc.get("retrieved_issues", [])
                    )

                # Run metrics
                scores = self._run_metrics(doc, issue_data)
                results.append(scores)

                # Update document with scores
                if doc_id:
                    self.store.update_scores(doc_id, scores)

                # Update run progress
                self.store.update_run(
                    run_id,
                    completed_evaluations=i + 1,
                )

            except Exception as e:
                error_msg = f"Failed to evaluate doc {doc.get('id')}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                self.store.update_run(run_id, error=error_msg)

        # Calculate averages
        avg_scores = self._calculate_averages(results)

        # Finalize run
        self.store.update_run(
            run_id,
            status="completed",
            average_scores=avg_scores,
        )

        return {
            "run_id": run_id,
            "evaluated": len(results),
            "errors": len(errors),
            "average_scores": avg_scores.model_dump(),
        }

    async def _fetch_issue_data(
        self,
        issue_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch full issue data from vector store.

        Args:
            issue_ids: List of issue IDs to fetch

        Returns:
            List of issue data dictionaries
        """
        # This would integrate with the vector store to get full issue data
        # For now, return empty - can be implemented when needed
        logger.info(f"Would fetch data for {len(issue_ids)} issues")
        return []

    def _calculate_averages(
        self,
        results: list[EvaluationScores],
    ) -> EvaluationScores:
        """Calculate average scores from results.

        Args:
            results: List of score results

        Returns:
            EvaluationScores with averages
        """
        if not results:
            return EvaluationScores()

        def avg(values: list[float | None]) -> float | None:
            valid = [v for v in values if v is not None]
            return sum(valid) / len(valid) if valid else None

        return EvaluationScores(
            tool_selection_accuracy=avg([r.tool_selection_accuracy for r in results]),
            retrieval_precision=avg([r.retrieval_precision for r in results]),
            retrieval_recall=avg([r.retrieval_recall for r in results]),
            faithfulness=avg([r.faithfulness for r in results]),
            citation_accuracy=avg([r.citation_accuracy for r in results]),
        )

    def get_metrics_summary(self, days: int = 30) -> dict[str, Any]:
        """Get metrics summary for dashboard.

        Args:
            days: Number of days to include

        Returns:
            Summary data for dashboard
        """
        summary = self.store.get_metrics_summary(days)
        return summary.model_dump()
