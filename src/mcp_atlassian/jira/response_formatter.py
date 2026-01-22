"""
Response compression utilities for optimizing MCP tool responses.

This module provides utilities to compress Jira API responses for reduced
context consumption in Claude Code and other LLM-based tools.
"""

from datetime import datetime, timezone
from typing import Any


class ResponseFormatter:
    """
    Compresses Jira API responses to reduce context consumption.

    Features:
    - Truncates long descriptions
    - Flattens nested objects (status, priority, assignee)
    - Converts timestamps to human-readable relative format
    - Removes verbose metadata
    """

    DEFAULT_MAX_DESCRIPTION_LENGTH = 200
    DEFAULT_MAX_SUMMARY_LENGTH = 100

    @classmethod
    def compress_search_result(
        cls,
        result: dict[str, Any],
        max_description_length: int = DEFAULT_MAX_DESCRIPTION_LENGTH,
        include_description: bool = True,
    ) -> dict[str, Any]:
        """
        Compress a JiraSearchResult dictionary.

        Args:
            result: The search result from to_simplified_dict()
            max_description_length: Maximum characters for descriptions
            include_description: Whether to include descriptions at all

        Returns:
            Compressed search result
        """
        compressed_issues = [
            cls.compress_issue(
                issue,
                max_description_length=max_description_length,
                include_description=include_description,
            )
            for issue in result.get("issues", [])
        ]

        return {
            "total": result.get("total", -1),
            "start_at": result.get("start_at", 0),
            "max_results": result.get("max_results", len(compressed_issues)),
            "issues": compressed_issues,
        }

    @classmethod
    def compress_issue(
        cls,
        issue: dict[str, Any],
        max_description_length: int = DEFAULT_MAX_DESCRIPTION_LENGTH,
        include_description: bool = True,
        include_comments: bool = False,
        include_attachments: bool = False,
    ) -> dict[str, Any]:
        """
        Compress a single JiraIssue dictionary.

        Args:
            issue: The issue from to_simplified_dict()
            max_description_length: Maximum characters for description
            include_description: Whether to include description
            include_comments: Whether to include comments
            include_attachments: Whether to include attachments

        Returns:
            Compressed issue dictionary
        """
        compressed = {
            "key": issue.get("key", ""),
            "summary": issue.get("summary", ""),
            "status": cls._flatten_named_object(issue.get("status")),
            "priority": cls._flatten_named_object(issue.get("priority")),
            "assignee": cls._flatten_user(issue.get("assignee")),
            "updated": cls._relative_timestamp(issue.get("updated")),
        }

        # Optional fields
        if include_description and issue.get("description"):
            compressed["description"] = cls._truncate(
                issue["description"], max_description_length
            )

        if issue.get("issue_type"):
            compressed["type"] = cls._flatten_named_object(issue["issue_type"])

        if issue.get("reporter"):
            compressed["reporter"] = cls._flatten_user(issue["reporter"])

        if issue.get("labels"):
            compressed["labels"] = issue["labels"]

        if issue.get("created"):
            compressed["created"] = cls._relative_timestamp(issue["created"])

        if include_comments and issue.get("comments"):
            compressed["comments_count"] = len(issue["comments"])

        if include_attachments and issue.get("attachments"):
            compressed["attachments_count"] = len(issue["attachments"])

        return compressed

    @classmethod
    def compress_issue_list(
        cls,
        issues: list[dict[str, Any]],
        max_description_length: int = DEFAULT_MAX_DESCRIPTION_LENGTH,
        include_description: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Compress a list of issues (for board/sprint queries).

        Args:
            issues: List of issue dictionaries
            max_description_length: Maximum description length
            include_description: Whether to include descriptions

        Returns:
            List of compressed issue dictionaries
        """
        return [
            cls.compress_issue(
                issue,
                max_description_length=max_description_length,
                include_description=include_description,
            )
            for issue in issues
        ]

    @classmethod
    def compress_boards(cls, boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Compress a list of JiraBoard dictionaries.

        Args:
            boards: List of board dictionaries

        Returns:
            Compressed board list
        """
        return [
            {
                "id": board.get("id"),
                "name": board.get("name"),
                "type": board.get("type"),
                "project_key": board.get("project_key"),
            }
            for board in boards
        ]

    @classmethod
    def compress_sprints(cls, sprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Compress a list of JiraSprint dictionaries.

        Args:
            sprints: List of sprint dictionaries

        Returns:
            Compressed sprint list
        """
        return [
            {
                "id": sprint.get("id"),
                "name": sprint.get("name"),
                "state": sprint.get("state"),
                "start_date": cls._relative_timestamp(sprint.get("start_date")),
                "end_date": cls._relative_timestamp(sprint.get("end_date")),
            }
            for sprint in sprints
        ]

    @classmethod
    def compress_projects(cls, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Compress a list of Jira project dictionaries.

        Args:
            projects: List of project dictionaries from Jira API

        Returns:
            Compressed project list with essential fields only
        """
        return [
            {
                "id": project.get("id"),
                "key": project.get("key"),
                "name": project.get("name"),
                "type": project.get("projectTypeKey"),
            }
            for project in projects
        ]

    @staticmethod
    def _truncate(text: str | None, max_length: int) -> str:
        """Truncate text to max_length with ellipsis."""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= max_length:
            return text
        return text[:max_length].rsplit(" ", 1)[0] + "..."

    @staticmethod
    def _flatten_named_object(obj: dict[str, Any] | None) -> str | None:
        """Extract name from a nested object like status, priority, issue_type."""
        if not obj:
            return None
        if isinstance(obj, str):
            return obj
        return obj.get("name")

    @staticmethod
    def _flatten_user(user: dict[str, Any] | None) -> str | None:
        """Extract display name from a user object."""
        if not user:
            return None
        if isinstance(user, str):
            return user
        return user.get("display_name") or user.get("name")

    @classmethod
    def _relative_timestamp(cls, timestamp: str | None) -> str | None:
        """
        Convert ISO timestamp to human-readable relative time.

        Examples: "2h ago", "3d ago", "1w ago", "2mo ago"
        """
        if not timestamp:
            return None

        try:
            # Parse ISO 8601 format
            ts = timestamp.replace("Z", "+00:00")

            # Handle timezone format without colon
            if "+" in ts and ":" not in ts[-5:]:
                tz_pos = ts.rfind("+")
                if tz_pos != -1 and len(ts) >= tz_pos + 5:
                    ts = ts[: tz_pos + 3] + ":" + ts[tz_pos + 3 :]
            elif ts.count("-") > 2 and ":" not in ts[-5:]:
                tz_pos = ts.rfind("-")
                if tz_pos > 10 and len(ts) >= tz_pos + 5:
                    ts = ts[: tz_pos + 3] + ":" + ts[tz_pos + 3 :]

            dt = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)

            # Ensure both are timezone aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            diff = now - dt
            seconds = diff.total_seconds()

            if seconds < 0:
                return "just now"
            elif seconds < 60:
                return "just now"
            elif seconds < 3600:
                mins = int(seconds / 60)
                return f"{mins}m ago"
            elif seconds < 86400:
                hours = int(seconds / 3600)
                return f"{hours}h ago"
            elif seconds < 604800:
                days = int(seconds / 86400)
                return f"{days}d ago"
            elif seconds < 2592000:
                weeks = int(seconds / 604800)
                return f"{weeks}w ago"
            else:
                months = int(seconds / 2592000)
                return f"{months}mo ago"

        except (ValueError, TypeError):
            return timestamp
