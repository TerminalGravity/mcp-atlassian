"""Tool selection accuracy metric using DeepEval."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Expected tool selection rules for Jira knowledge queries
TOOL_SELECTION_RULES = {
    # Query patterns -> expected tools
    "jql_patterns": [
        "assignee =",
        "project =",
        "status =",
        "created >=",
        "updated >=",
        "ORDER BY",
        "issuetype =",
    ],
    "semantic_patterns": [
        "how do",
        "what is",
        "why did",
        "explain",
        "tell me about",
        "find issues related to",
        "search for",
    ],
    "epic_expansion_patterns": [
        "epic",
        "children",
        "subtasks",
        "breakdown",
    ],
    "link_patterns": [
        "linked",
        "related",
        "blocks",
        "blocked by",
        "depends on",
    ],
}


class ToolAccuracyMetric:
    """Assess tool selection accuracy.

    Checks if the right tools were selected for the query type:
    - JQL search for structured queries
    - Semantic search for natural language queries
    - Epic expansion for epic-related queries
    - Link fetching for relationship queries
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        """Initialize tool accuracy metric.

        Args:
            model: Model to use for DeepEval (if available)
        """
        self.model = model
        self.name = "tool_selection_accuracy"
        self._deepeval_available = False

    def _check_deepeval(self) -> bool:
        """Check if DeepEval is available."""
        try:
            from deepeval.metrics import ToolCorrectnessMetric  # noqa: F401

            self._deepeval_available = True
            return True
        except ImportError:
            self._deepeval_available = False
            return False

    def _classify_query(self, query: str) -> dict[str, bool]:
        """Classify what tools should be used for a query.

        Args:
            query: The user's question

        Returns:
            Dictionary of expected tool usage
        """
        query_lower = query.lower()

        expected = {
            "should_use_jql": False,
            "should_use_semantic": False,
            "should_expand_epics": False,
            "should_fetch_links": False,
        }

        # Check for JQL patterns
        for pattern in TOOL_SELECTION_RULES["jql_patterns"]:
            if pattern.lower() in query_lower:
                expected["should_use_jql"] = True
                break

        # Check for semantic patterns
        for pattern in TOOL_SELECTION_RULES["semantic_patterns"]:
            if pattern in query_lower:
                expected["should_use_semantic"] = True
                break

        # Check for epic patterns
        for pattern in TOOL_SELECTION_RULES["epic_expansion_patterns"]:
            if pattern in query_lower:
                expected["should_expand_epics"] = True
                break

        # Check for link patterns
        for pattern in TOOL_SELECTION_RULES["link_patterns"]:
            if pattern in query_lower:
                expected["should_fetch_links"] = True
                break

        # Default to semantic if no clear pattern
        if not any(expected.values()):
            expected["should_use_semantic"] = True

        return expected

    def _extract_tools_used(self, tool_calls: list[dict[str, Any]]) -> dict[str, bool]:
        """Extract what tools were actually used.

        Args:
            tool_calls: List of tool call records

        Returns:
            Dictionary of actual tool usage
        """
        actual = {
            "used_jql": False,
            "used_semantic": False,
            "expanded_epics": False,
            "fetched_links": False,
        }

        for call in tool_calls:
            tool_name = call.get("tool_name", "").lower()

            if "jql" in tool_name:
                actual["used_jql"] = True
            if "semantic" in tool_name or "vector" in tool_name:
                actual["used_semantic"] = True
            if "epic" in tool_name or "children" in tool_name:
                actual["expanded_epics"] = True
            if "link" in tool_name:
                actual["fetched_links"] = True

        return actual

    def run_assessment(
        self,
        query: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Assess tool selection accuracy.

        Args:
            query: The user's question
            tool_calls: List of tool calls made

        Returns:
            Dictionary with score and details
        """
        expected = self._classify_query(query)
        actual = self._extract_tools_used(tool_calls)

        # Calculate accuracy based on matching expectations
        matches = 0
        total = 0
        mismatches: list[str] = []

        # Check each expectation
        if expected["should_use_jql"]:
            total += 1
            if actual["used_jql"]:
                matches += 1
            else:
                mismatches.append("Expected JQL search but not used")

        if expected["should_use_semantic"]:
            total += 1
            if actual["used_semantic"]:
                matches += 1
            else:
                mismatches.append("Expected semantic search but not used")

        if expected["should_expand_epics"]:
            total += 1
            if actual["expanded_epics"]:
                matches += 1
            else:
                mismatches.append("Expected epic expansion but not used")

        if expected["should_fetch_links"]:
            total += 1
            if actual["fetched_links"]:
                matches += 1
            else:
                mismatches.append("Expected link fetching but not used")

        # Penalize unnecessary tool usage (optional, lower weight)
        unnecessary: list[str] = []
        if actual["used_jql"] and not expected["should_use_jql"]:
            unnecessary.append("JQL search used unnecessarily")
        if actual["expanded_epics"] and not expected["should_expand_epics"]:
            unnecessary.append("Epic expansion used unnecessarily")
        if actual["fetched_links"] and not expected["should_fetch_links"]:
            unnecessary.append("Link fetching used unnecessarily")

        # Calculate score
        if total == 0:
            score = 1.0  # No specific expectations
        else:
            # Base score from matches
            score = matches / total
            # Small penalty for unnecessary tools (max 0.1 penalty)
            if unnecessary:
                score = max(0.0, score - 0.05 * len(unnecessary))

        return {
            "score": score,
            "details": {
                "expected": expected,
                "actual": actual,
                "matches": matches,
                "total_expectations": total,
                "mismatches": mismatches,
                "unnecessary_tools": unnecessary,
                "tools_called": [c.get("tool_name") for c in tool_calls],
            },
        }

    async def arun_assessment(
        self,
        query: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Async version of run_assessment."""
        return self.run_assessment(query, tool_calls)

    def run_with_deepeval(
        self,
        query: str,
        tool_calls: list[dict[str, Any]],
        expected_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Assess using DeepEval's ToolCorrectnessMetric.

        Args:
            query: The user's question
            tool_calls: List of tool calls made
            expected_tools: Optional list of expected tool names

        Returns:
            Dictionary with score and details
        """
        if not self._check_deepeval():
            logger.info("DeepEval not available, using heuristic assessment")
            return self.run_assessment(query, tool_calls)

        try:
            from deepeval.metrics import ToolCorrectnessMetric
            from deepeval.test_case import LLMTestCase

            # Convert tool calls to DeepEval format
            tools_used = [
                {"name": c.get("tool_name"), "input": c.get("input", {})}
                for c in tool_calls
            ]

            # If no expected tools provided, use heuristic classification
            if expected_tools is None:
                expected = self._classify_query(query)
                expected_tools = []
                if expected["should_use_jql"]:
                    expected_tools.append("jql_search")
                if expected["should_use_semantic"]:
                    expected_tools.append("semantic_search")
                if expected["should_expand_epics"]:
                    expected_tools.append("get_epic_children")
                if expected["should_fetch_links"]:
                    expected_tools.append("get_linked_issues")

            metric = ToolCorrectnessMetric(
                threshold=0.7,
                model=self.model,
            )

            test_case = LLMTestCase(
                input=query,
                actual_output="",  # Not used for tool correctness
                tools_called=tools_used,
                expected_tools=expected_tools,
            )

            metric.measure(test_case)

            return {
                "score": metric.score,
                "details": {
                    "passed": metric.score >= 0.7,
                    "reason": getattr(metric, "reason", None),
                    "expected_tools": expected_tools,
                    "tools_used": [c.get("tool_name") for c in tool_calls],
                },
            }
        except Exception as e:
            logger.error(f"DeepEval tool assessment failed: {e}")
            return self.run_assessment(query, tool_calls)
