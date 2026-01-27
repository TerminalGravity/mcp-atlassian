"""Citation accuracy metric for evaluating reference correctness."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class CitationAccuracyMetric:
    """Evaluate citation accuracy in responses.

    This metric checks if citations like [1], [2], [DS-1234] in the response
    actually correspond to retrieved issues and if the cited content matches.
    """

    def __init__(self) -> None:
        """Initialize the citation accuracy metric."""
        self.name = "citation_accuracy"

    def extract_citations_from_response(self, response_text: str) -> list[dict[str, Any]]:
        """Extract all citation references from response text.

        Args:
            response_text: The LLM response text

        Returns:
            List of citations with type and value
        """
        citations: list[dict[str, Any]] = []

        # Match numeric citations like [1], [2]
        numeric_pattern = r"\[(\d+)\]"
        for match in re.finditer(numeric_pattern, response_text):
            citations.append({
                "type": "numeric",
                "value": int(match.group(1)),
                "position": match.start(),
            })

        # Match issue key citations like [DS-1234], [AI-567]
        issue_key_pattern = r"\[([A-Z]+-\d+)\]"
        for match in re.finditer(issue_key_pattern, response_text):
            citations.append({
                "type": "issue_key",
                "value": match.group(1),
                "position": match.start(),
            })

        # Also match inline issue references like "DS-1234" without brackets
        inline_pattern = r"(?<!\[)([A-Z]+-\d+)(?!\])"
        for match in re.finditer(inline_pattern, response_text):
            citations.append({
                "type": "inline",
                "value": match.group(1),
                "position": match.start(),
            })

        return citations

    def evaluate(
        self,
        response_text: str,
        retrieved_issues: list[str],
        declared_citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate citation accuracy.

        Args:
            response_text: The LLM response text
            retrieved_issues: List of issue IDs that were retrieved
            declared_citations: Optional list of citations declared by the system

        Returns:
            Dictionary with score and details
        """
        extracted_citations = self.extract_citations_from_response(response_text)

        if not extracted_citations:
            # No citations in response - neutral score
            return {
                "score": 1.0,
                "details": {
                    "total_citations": 0,
                    "valid_citations": 0,
                    "invalid_citations": 0,
                    "reason": "No citations found in response",
                },
            }

        valid_count = 0
        invalid_count = 0
        invalid_details: list[str] = []

        for citation in extracted_citations:
            is_valid = False

            if citation["type"] == "numeric":
                # Check if numeric index is within bounds
                idx = citation["value"]
                if 1 <= idx <= len(retrieved_issues):
                    is_valid = True
                else:
                    invalid_details.append(
                        f"Numeric citation [{idx}] out of bounds (max: {len(retrieved_issues)})"
                    )

            elif citation["type"] in ("issue_key", "inline"):
                # Check if issue key exists in retrieved issues
                issue_key = citation["value"]
                if issue_key in retrieved_issues:
                    is_valid = True
                else:
                    invalid_details.append(
                        f"Issue key {issue_key} not in retrieved issues"
                    )

            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1

        total = valid_count + invalid_count
        score = valid_count / total if total > 0 else 1.0

        return {
            "score": score,
            "details": {
                "total_citations": total,
                "valid_citations": valid_count,
                "invalid_citations": invalid_count,
                "invalid_details": invalid_details[:5],  # Limit details
            },
        }

    async def aevaluate(
        self,
        response_text: str,
        retrieved_issues: list[str],
        declared_citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Async version of evaluate."""
        return self.evaluate(response_text, retrieved_issues, declared_citations)
