"""Retrieval quality metrics using RAGAS."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RetrievalMetrics:
    """Evaluate retrieval quality using RAGAS metrics.

    Measures:
    - Context Precision: Are retrieved docs relevant to the query?
    - Context Recall: Did we retrieve all necessary docs?
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        """Initialize retrieval metrics.

        Args:
            model: Model to use for evaluation
        """
        self.model = model
        self.name = "retrieval"
        self._precision_metric: Any = None
        self._recall_metric: Any = None

    def _init_metrics(self) -> bool:
        """Initialize RAGAS metrics lazily."""
        if self._precision_metric is not None:
            return True

        try:
            from ragas.metrics import context_precision, context_recall

            self._precision_metric = context_precision
            self._recall_metric = context_recall
            return True
        except ImportError:
            logger.warning("RAGAS not installed. Install with: uv pip install ragas")
            return False

    def _build_contexts(self, issues: list[dict[str, Any]]) -> list[str]:
        """Build context strings from issue data."""
        contexts = []
        for issue in issues:
            parts = []
            issue_id = issue.get("issue_id", issue.get("id", "Unknown"))
            parts.append(f"[{issue_id}]")

            if issue.get("summary"):
                parts.append(issue["summary"])

            if issue.get("description_preview") or issue.get("description"):
                desc = issue.get("description_preview") or issue.get("description", "")
                parts.append(desc[:300])

            contexts.append(" - ".join(parts))

        return contexts

    def evaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
        ground_truth: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate retrieval quality.

        Args:
            query: The user's question
            response_text: The LLM response (used as answer)
            retrieved_issues: List of retrieved issue data
            ground_truth: Optional expected answer for recall calculation

        Returns:
            Dictionary with precision and recall scores
        """
        if not self._init_metrics():
            return {
                "precision": None,
                "recall": None,
                "details": {
                    "error": "RAGAS not available",
                    "reason": "Install with: uv pip install 'mcp-atlassian[eval]'",
                },
            }

        if not retrieved_issues:
            return {
                "precision": None,
                "recall": None,
                "details": {
                    "reason": "No retrieved issues to evaluate",
                },
            }

        try:
            from datasets import Dataset
            from ragas import evaluate

            contexts = self._build_contexts(retrieved_issues)

            # Build evaluation dataset
            # RAGAS expects specific column names
            data = {
                "question": [query],
                "answer": [response_text],
                "contexts": [contexts],
            }

            # Add ground truth if provided (needed for recall)
            if ground_truth:
                data["ground_truth"] = [ground_truth]
                metrics = [self._precision_metric, self._recall_metric]
            else:
                # Without ground truth, we can only measure precision
                metrics = [self._precision_metric]

            dataset = Dataset.from_dict(data)

            # Run evaluation
            result = evaluate(dataset, metrics=metrics)

            precision_score = result.get("context_precision", None)
            recall_score = result.get("context_recall", None)

            return {
                "precision": precision_score,
                "recall": recall_score,
                "details": {
                    "num_contexts": len(contexts),
                    "has_ground_truth": ground_truth is not None,
                },
            }
        except Exception as e:
            logger.error(f"Retrieval evaluation failed: {e}")
            return {
                "precision": None,
                "recall": None,
                "details": {
                    "error": str(e),
                },
            }

    async def aevaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
        ground_truth: str | None = None,
    ) -> dict[str, Any]:
        """Async version of evaluate."""
        return self.evaluate(query, response_text, retrieved_issues, ground_truth)


class SimplifiedRetrievalMetrics:
    """Simplified retrieval metrics without RAGAS dependency.

    Uses heuristics for quick evaluation:
    - Precision: % of retrieved issues mentioned in response
    - Recall: Based on query term coverage in retrieved issues
    """

    def __init__(self) -> None:
        """Initialize simplified metrics."""
        self.name = "retrieval_simple"

    def evaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate retrieval using heuristics.

        Args:
            query: The user's question
            response_text: The LLM response
            retrieved_issues: List of retrieved issue data

        Returns:
            Dictionary with precision and recall estimates
        """
        if not retrieved_issues:
            return {
                "precision": None,
                "recall": None,
                "details": {"reason": "No retrieved issues"},
            }

        # Precision: How many retrieved issues are referenced in response?
        mentioned_count = 0
        for issue in retrieved_issues:
            issue_id = issue.get("issue_id", issue.get("id", ""))
            if issue_id and issue_id in response_text:
                mentioned_count += 1

        precision = mentioned_count / len(retrieved_issues) if retrieved_issues else 0

        # Recall estimate: Do query terms appear in retrieved content?
        query_terms = set(query.lower().split())
        # Remove common words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "what", "how", "who", "when", "where", "why"}
        query_terms = query_terms - stop_words

        if not query_terms:
            recall = 1.0  # No specific terms to match
        else:
            # Check how many query terms appear in retrieved issue content
            all_content = " ".join(
                f"{i.get('summary', '')} {i.get('description_preview', '')}"
                for i in retrieved_issues
            ).lower()

            matched_terms = sum(1 for term in query_terms if term in all_content)
            recall = matched_terms / len(query_terms)

        return {
            "precision": precision,
            "recall": recall,
            "details": {
                "issues_mentioned": mentioned_count,
                "total_retrieved": len(retrieved_issues),
                "query_terms_matched": f"{int(recall * len(query_terms))}/{len(query_terms)}",
            },
        }

    async def aevaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Async version of evaluate."""
        return self.evaluate(query, response_text, retrieved_issues)
