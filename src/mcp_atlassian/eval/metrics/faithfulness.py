"""Faithfulness metric using DeepEval for hallucination detection."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FaithfulnessMetric:
    """Evaluate response faithfulness to retrieved context.

    Uses DeepEval's FaithfulnessMetric to detect hallucinations -
    claims in the response not supported by the retrieved issues.
    """

    def __init__(self, threshold: float = 0.7, model: str = "gpt-4o-mini") -> None:
        """Initialize the faithfulness metric.

        Args:
            threshold: Minimum score to pass (0-1)
            model: Model to use for evaluation
        """
        self.threshold = threshold
        self.model = model
        self.name = "faithfulness"
        self._metric: Any = None

    def _get_metric(self) -> Any:
        """Lazy load DeepEval metric."""
        if self._metric is None:
            try:
                from deepeval.metrics import FaithfulnessMetric as DeepEvalFaithfulness

                self._metric = DeepEvalFaithfulness(
                    threshold=self.threshold,
                    model=self.model,
                    include_reason=True,
                )
            except ImportError:
                logger.warning(
                    "DeepEval not installed. Install with: uv pip install deepeval"
                )
                self._metric = None
        return self._metric

    def _build_context(self, issues: list[dict[str, Any]]) -> list[str]:
        """Build context strings from issue data.

        Args:
            issues: List of issue dictionaries with id, summary, description, etc.

        Returns:
            List of context strings for evaluation
        """
        contexts = []
        for issue in issues:
            parts = []
            issue_id = issue.get("issue_id", issue.get("id", "Unknown"))
            parts.append(f"Issue: {issue_id}")

            if issue.get("summary"):
                parts.append(f"Summary: {issue['summary']}")

            if issue.get("status"):
                parts.append(f"Status: {issue['status']}")

            if issue.get("assignee"):
                parts.append(f"Assignee: {issue['assignee']}")

            if issue.get("description_preview") or issue.get("description"):
                desc = issue.get("description_preview") or issue.get("description", "")
                parts.append(f"Description: {desc[:500]}")

            contexts.append("\n".join(parts))

        return contexts

    def evaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate faithfulness of response to context.

        Args:
            query: The user's question
            response_text: The LLM response
            retrieved_issues: List of retrieved issue data

        Returns:
            Dictionary with score and details
        """
        metric = self._get_metric()

        if metric is None:
            return {
                "score": None,
                "details": {
                    "error": "DeepEval not available",
                    "reason": "Install with: uv pip install 'mcp-atlassian[eval]'",
                },
            }

        if not retrieved_issues:
            return {
                "score": 1.0,
                "details": {
                    "reason": "No context provided - skipping faithfulness check",
                },
            }

        try:
            from deepeval.test_case import LLMTestCase

            contexts = self._build_context(retrieved_issues)

            test_case = LLMTestCase(
                input=query,
                actual_output=response_text,
                retrieval_context=contexts,
            )

            metric.measure(test_case)

            return {
                "score": metric.score,
                "details": {
                    "passed": metric.score >= self.threshold,
                    "threshold": self.threshold,
                    "reason": getattr(metric, "reason", None),
                },
            }
        except Exception as e:
            logger.error(f"Faithfulness evaluation failed: {e}")
            return {
                "score": None,
                "details": {
                    "error": str(e),
                },
            }

    async def aevaluate(
        self,
        query: str,
        response_text: str,
        retrieved_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Async version of evaluate.

        DeepEval's async support varies, so we run sync version.
        """
        return self.evaluate(query, response_text, retrieved_issues)
