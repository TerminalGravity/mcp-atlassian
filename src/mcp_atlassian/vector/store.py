"""LanceDB vector store for Jira issues."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import lancedb

from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.schemas import JiraCommentEmbedding, JiraIssueEmbedding

if TYPE_CHECKING:
    from lancedb.table import Table

logger = logging.getLogger(__name__)

# Table names
ISSUES_TABLE = "jira_issues"


def _format_sql_in_clause(values: list[str]) -> str:
    """Format a list of values for SQL IN clause.

    Handles the edge case where a single-element tuple in Python
    produces ('value',) which is invalid SQL syntax.

    Args:
        values: List of string values to format

    Returns:
        Properly formatted SQL IN clause like ('a', 'b') or ('a')
    """
    if not values:
        return "()"
    # Quote and escape values, then join with commas
    escaped = [f"'{v.replace(chr(39), chr(39)+chr(39))}'" for v in values]
    return f"({', '.join(escaped)})"
COMMENTS_TABLE = "jira_comments"


class LanceDBStore:
    """Vector store for Jira issues using LanceDB.

    Provides CRUD operations, vector search, and hybrid search capabilities
    for Jira issues and comments.
    """

    def __init__(self, config: VectorConfig | None = None) -> None:
        """Initialize the LanceDB store.

        Args:
            config: Vector configuration. Uses defaults from env if not provided.
        """
        self.config = config or VectorConfig.from_env()
        self._db: lancedb.DBConnection | None = None
        self._issues_table: Table | None = None
        self._comments_table: Table | None = None

    @property
    def db(self) -> lancedb.DBConnection:
        """Get or create database connection."""
        if self._db is None:
            db_path = self.config.ensure_db_path()
            self._db = lancedb.connect(str(db_path))
            logger.info(f"Connected to LanceDB at {db_path}")
        return self._db

    @property
    def issues_table(self) -> Table:
        """Get or create issues table."""
        if self._issues_table is None:
            self._issues_table = self._get_or_create_table(
                ISSUES_TABLE, JiraIssueEmbedding
            )
        return self._issues_table

    @property
    def comments_table(self) -> Table:
        """Get or create comments table."""
        if self._comments_table is None:
            self._comments_table = self._get_or_create_table(
                COMMENTS_TABLE, JiraCommentEmbedding
            )
        return self._comments_table

    def _get_or_create_table(
        self,
        name: str,
        schema: type[JiraIssueEmbedding] | type[JiraCommentEmbedding],
    ) -> Table:
        """Get existing table or create new one with schema.

        Args:
            name: Table name
            schema: Pydantic model defining the schema

        Returns:
            LanceDB table
        """
        if name in self.db.table_names():
            logger.debug(f"Opening existing table: {name}")
            return self.db.open_table(name)

        logger.info(f"Creating new table: {name}")
        # Create empty table with schema
        return self.db.create_table(name, schema=schema)

    def bulk_insert_issues(self, issues: list[JiraIssueEmbedding]) -> int:
        """Bulk insert issues without checking for existing records.

        Use this for initial full syncs where the table is empty or
        has been cleared. Much faster than upsert.

        Args:
            issues: List of issue embeddings to insert

        Returns:
            Number of issues inserted
        """
        if not issues:
            return 0

        records = [issue.model_dump() for issue in issues]
        self.issues_table.add(records)
        logger.info(f"Bulk inserted {len(records)} issues")
        return len(records)

    def upsert_issues(self, issues: list[JiraIssueEmbedding]) -> int:
        """Upsert multiple issues into the store.

        Args:
            issues: List of issue embeddings to upsert

        Returns:
            Number of issues upserted
        """
        if not issues:
            return 0

        # Convert to dicts for LanceDB
        records = [issue.model_dump() for issue in issues]

        # Get existing issue IDs
        existing_ids = set(self._get_existing_issue_ids([i.issue_id for i in issues]))

        # Split into updates and inserts
        updates = [r for r in records if r["issue_id"] in existing_ids]
        inserts = [r for r in records if r["issue_id"] not in existing_ids]

        # Delete existing records that will be updated
        if updates:
            update_ids = [r["issue_id"] for r in updates]
            self.issues_table.delete(f"issue_id IN {_format_sql_in_clause(update_ids)}")
            logger.debug(f"Deleted {len(updates)} existing issues for update")

        # Add all records
        all_records = updates + inserts
        if all_records:
            self.issues_table.add(all_records)
            logger.info(
                f"Upserted {len(all_records)} issues "
                f"({len(inserts)} new, {len(updates)} updated)"
            )

        return len(all_records)

    def compact(self) -> None:
        """Compact tables to reduce storage and improve performance.

        Call this after large batch operations to merge fragments.
        Requires pylance package for optimal performance.
        """
        try:
            # compact_files requires pylance - skip if not available
            if hasattr(self.issues_table, 'compact_files'):
                self.issues_table.compact_files()
                logger.info("Compacted issues table")
            else:
                logger.debug("Table compaction not available")
        except ImportError:
            logger.debug("pylance not installed, skipping compaction")
        except Exception as e:
            logger.debug(f"Skipping compaction: {e}")

        try:
            if hasattr(self.comments_table, 'compact_files'):
                self.comments_table.compact_files()
                logger.info("Compacted comments table")
        except ImportError:
            pass  # pylance not installed
        except Exception as e:
            logger.debug(f"Skipping comments compaction: {e}")

    def clear_issues(self, project_key: str | None = None) -> int:
        """Clear all issues, optionally filtered by project.

        Args:
            project_key: Optional project key to clear only that project

        Returns:
            Number of issues deleted (estimated)
        """
        try:
            if project_key:
                # Delete issues for specific project
                # Try to get count, but don't fail if unavailable
                try:
                    count = self.issues_table.count_rows()
                except Exception:
                    count = 0
                self.issues_table.delete(f"project_key = '{project_key}'")
                try:
                    new_count = self.issues_table.count_rows()
                    deleted = count - new_count
                except Exception:
                    deleted = count  # Assume all deleted
            else:
                # Delete all issues
                try:
                    count = self.issues_table.count_rows()
                except Exception:
                    count = 0
                self.issues_table.delete("true")
                deleted = count

            logger.info(f"Cleared {deleted} issues")
            return deleted
        except Exception as e:
            logger.warning(f"Failed to clear issues: {e}")
            return 0

    def upsert_comments(self, comments: list[JiraCommentEmbedding]) -> int:
        """Upsert multiple comments into the store.

        Args:
            comments: List of comment embeddings to upsert

        Returns:
            Number of comments upserted
        """
        if not comments:
            return 0

        records = [comment.model_dump() for comment in comments]

        # Get existing comment IDs
        existing_ids = set(
            self._get_existing_comment_ids([c.comment_id for c in comments])
        )

        # Split into updates and inserts
        updates = [r for r in records if r["comment_id"] in existing_ids]
        inserts = [r for r in records if r["comment_id"] not in existing_ids]

        # Delete existing records that will be updated
        if updates:
            update_ids = [r["comment_id"] for r in updates]
            self.comments_table.delete(f"comment_id IN {_format_sql_in_clause(update_ids)}")

        # Add all records
        all_records = updates + inserts
        if all_records:
            self.comments_table.add(all_records)
            logger.info(
                f"Upserted {len(all_records)} comments "
                f"({len(inserts)} new, {len(updates)} updated)"
            )

        return len(all_records)

    def _get_existing_issue_ids(self, issue_ids: list[str]) -> list[str]:
        """Get which issue IDs already exist in the store."""
        if not issue_ids:
            return []

        try:
            # Query for existing IDs
            result = (
                self.issues_table.search()
                .where(f"issue_id IN {_format_sql_in_clause(issue_ids)}", prefilter=True)
                .select(["issue_id"])
                .limit(len(issue_ids))
                .to_list()
            )
            return [r["issue_id"] for r in result]
        except Exception:
            # Table might be empty
            return []

    def _get_existing_comment_ids(self, comment_ids: list[str]) -> list[str]:
        """Get which comment IDs already exist in the store."""
        if not comment_ids:
            return []

        try:
            result = (
                self.comments_table.search()
                .where(f"comment_id IN {_format_sql_in_clause(comment_ids)}", prefilter=True)
                .select(["comment_id"])
                .limit(len(comment_ids))
                .to_list()
            )
            return [r["comment_id"] for r in result]
        except Exception:
            return []

    def get_issue_by_key(self, issue_key: str) -> JiraIssueEmbedding | None:
        """Get a single issue by its key.

        Args:
            issue_key: Jira issue key (e.g., PROJ-123)

        Returns:
            Issue embedding or None if not found
        """
        try:
            results = (
                self.issues_table.search()
                .where(f"issue_id = '{issue_key}'", prefilter=True)
                .limit(1)
                .to_list()
            )
            if results:
                return JiraIssueEmbedding(**results[0])
            return None
        except Exception as e:
            logger.warning(f"Error getting issue {issue_key}: {e}")
            return None

    def search_issues(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search issues by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum results to return
            filters: Optional metadata filters

        Returns:
            List of matching issues with scores
        """
        # Fetch extra results to handle potential duplicates
        search = self.issues_table.search(query_vector).limit(limit * 3)

        # Apply filters
        if filters:
            where_clause = self._build_where_clause(filters)
            if where_clause:
                search = search.where(where_clause, prefilter=True)

        results = search.to_list()

        # Add similarity score and deduplicate by issue_id
        seen_ids: set[str] = set()
        unique_results: list[dict[str, Any]] = []
        for r in results:
            issue_id = r.get("issue_id")
            if issue_id and issue_id not in seen_ids:
                seen_ids.add(issue_id)
                r["score"] = 1 - r.get("_distance", 0)  # Convert distance to similarity
                unique_results.append(r)
                if len(unique_results) >= limit:
                    break

        return unique_results

    def hybrid_search(
        self,
        query_vector: list[float],
        query_text: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        fts_weight: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Hybrid search combining vector and full-text search.

        Args:
            query_vector: Query embedding vector
            query_text: Query text for FTS
            limit: Maximum results to return
            filters: Optional metadata filters
            fts_weight: Weight for FTS score (0-1), vector gets 1-fts_weight

        Returns:
            List of matching issues with combined scores
        """
        # Vector search
        vector_results = self.search_issues(
            query_vector, limit=limit * 2, filters=filters
        )

        # Full-text search on summary and description
        fts_results = self._full_text_search(
            query_text, limit=limit * 2, filters=filters
        )

        # Combine results with score fusion
        combined = self._fuse_results(
            vector_results, fts_results, fts_weight=fts_weight
        )

        # Sort by combined score and limit
        combined.sort(key=lambda x: x["score"], reverse=True)
        return combined[:limit]

    def _full_text_search(
        self,
        query_text: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Perform full-text search on summary and description.

        Note: LanceDB FTS requires creating an FTS index. For now, we use
        a simple LIKE-based search as fallback.
        """
        try:
            # Try FTS if available
            search = self.issues_table.search(query_text, query_type="fts").limit(limit)

            if filters:
                where_clause = self._build_where_clause(filters)
                if where_clause:
                    search = search.where(where_clause, prefilter=True)

            results = search.to_list()
            for r in results:
                r["score"] = r.get("_score", 0.5)
            return results

        except Exception:
            # Fallback to LIKE search
            logger.debug("FTS not available, using LIKE search")
            return self._like_search(query_text, limit, filters)

    def _like_search(
        self,
        query_text: str,
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Fallback search using LIKE queries."""
        # Escape special characters
        query_escaped = query_text.replace("'", "''").lower()

        where_parts = [
            f"(lower(summary) LIKE '%{query_escaped}%' "
            f"OR lower(description_preview) LIKE '%{query_escaped}%')"
        ]

        if filters:
            filter_clause = self._build_where_clause(filters)
            if filter_clause:
                where_parts.append(filter_clause)

        where_clause = " AND ".join(where_parts)

        try:
            results = (
                self.issues_table.search()
                .where(where_clause, prefilter=True)
                .limit(limit)
                .to_list()
            )
            # Assign a base score for text matches
            for r in results:
                r["score"] = 0.5
            return results
        except Exception as e:
            logger.warning(f"LIKE search failed: {e}")
            return []

    def _fuse_results(
        self,
        vector_results: list[dict[str, Any]],
        fts_results: list[dict[str, Any]],
        fts_weight: float,
    ) -> list[dict[str, Any]]:
        """Fuse vector and FTS results using weighted combination."""
        vector_weight = 1 - fts_weight

        # Build lookup by issue_id
        combined: dict[str, dict[str, Any]] = {}

        for r in vector_results:
            issue_id = r["issue_id"]
            combined[issue_id] = r.copy()
            combined[issue_id]["vector_score"] = r.get("score", 0)
            combined[issue_id]["fts_score"] = 0

        for r in fts_results:
            issue_id = r["issue_id"]
            if issue_id in combined:
                combined[issue_id]["fts_score"] = r.get("score", 0)
            else:
                combined[issue_id] = r.copy()
                combined[issue_id]["vector_score"] = 0
                combined[issue_id]["fts_score"] = r.get("score", 0)

        # Calculate combined scores
        for r in combined.values():
            r["score"] = (
                vector_weight * r.get("vector_score", 0)
                + fts_weight * r.get("fts_score", 0)
            )

        return list(combined.values())

    def _build_where_clause(self, filters: dict[str, Any]) -> str:
        """Build SQL WHERE clause from filter dict.

        Supports:
            - Simple equality: {"status": "Open"}
            - $in operator: {"project_key": {"$in": ["PROJ", "ENG"]}}
            - $nin operator: {"status": {"$nin": ["Done", "Closed"]}}
            - $gte/$lte: {"created_at": {"$gte": "2024-01-01"}}
            - $ne: {"status": {"$ne": "Done"}}
        """
        clauses = []

        for field, value in filters.items():
            if isinstance(value, dict):
                # Operator-based filter
                for op, operand in value.items():
                    clause = self._build_operator_clause(field, op, operand)
                    if clause:
                        clauses.append(clause)
            else:
                # Simple equality
                if isinstance(value, str):
                    clauses.append(f"{field} = '{value}'")
                elif isinstance(value, bool):
                    clauses.append(f"{field} = {str(value).lower()}")
                elif isinstance(value, int | float):
                    clauses.append(f"{field} = {value}")

        return " AND ".join(clauses)

    def _build_operator_clause(
        self, field: str, op: str, operand: Any
    ) -> str | None:
        """Build WHERE clause for a single operator."""
        if op == "$in":
            if isinstance(operand, list) and operand:
                values = ", ".join(f"'{v}'" for v in operand)
                return f"{field} IN ({values})"
        elif op == "$nin":
            if isinstance(operand, list) and operand:
                values = ", ".join(f"'{v}'" for v in operand)
                return f"{field} NOT IN ({values})"
        elif op == "$ne":
            if isinstance(operand, str):
                return f"{field} != '{operand}'"
            return f"{field} != {operand}"
        elif op == "$gte":
            if isinstance(operand, str):
                return f"{field} >= '{operand}'"
            return f"{field} >= {operand}"
        elif op == "$lte":
            if isinstance(operand, str):
                return f"{field} <= '{operand}'"
            return f"{field} <= {operand}"
        elif op == "$gt":
            if isinstance(operand, str):
                return f"{field} > '{operand}'"
            return f"{field} > {operand}"
        elif op == "$lt":
            if isinstance(operand, str):
                return f"{field} < '{operand}'"
            return f"{field} < {operand}"

        return None

    def search_comments(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search comments by vector similarity.

        Args:
            query_vector: Query embedding vector
            limit: Maximum results to return
            filters: Optional metadata filters

        Returns:
            List of matching comments with scores
        """
        search = self.comments_table.search(query_vector).limit(limit)

        # Apply filters
        if filters:
            where_clause = self._build_where_clause(filters)
            if where_clause:
                search = search.where(where_clause, prefilter=True)

        results = search.to_list()

        # Add similarity score
        for r in results:
            r["score"] = 1 - r.get("_distance", 0)  # Convert distance to similarity

        return results

    def get_comments_for_issue(
        self,
        issue_key: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all indexed comments for an issue.

        Args:
            issue_key: Jira issue key
            limit: Maximum comments to return

        Returns:
            List of comment records
        """
        try:
            results = (
                self.comments_table.search()
                .where(f"issue_key = '{issue_key}'", prefilter=True)
                .limit(limit)
                .to_list()
            )
            return results
        except Exception as e:
            logger.warning(f"Error getting comments for {issue_key}: {e}")
            return []

    def get_project_aggregations(
        self,
        project_key: str,
    ) -> dict[str, Any]:
        """Get aggregated statistics for a project.

        Args:
            project_key: Project key to analyze

        Returns:
            Dictionary with aggregated stats
        """
        try:
            issues_df = self.issues_table.to_pandas()
            project_issues = issues_df[issues_df["project_key"] == project_key]

            if len(project_issues) == 0:
                return {"project_key": project_key, "total_issues": 0}

            # Basic aggregations
            type_counts = project_issues["issue_type"].value_counts().to_dict()
            status_counts = project_issues["status_category"].value_counts().to_dict()
            priority_counts = (
                project_issues["priority"].value_counts().to_dict()
                if "priority" in project_issues.columns
                else {}
            )

            # Assignee distribution (top 10)
            assignee_counts = (
                project_issues["assignee"].value_counts().head(10).to_dict()
            )

            # Label frequency
            all_labels: list[str] = []
            for labels in project_issues["labels"]:
                if isinstance(labels, list):
                    all_labels.extend(labels)
            label_counts = {}
            for label in all_labels:
                label_counts[label] = label_counts.get(label, 0) + 1
            top_labels = dict(
                sorted(label_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            )

            # Component distribution
            all_components: list[str] = []
            for components in project_issues["components"]:
                if isinstance(components, list):
                    all_components.extend(components)
            component_counts = {}
            for comp in all_components:
                component_counts[comp] = component_counts.get(comp, 0) + 1
            top_components = dict(
                sorted(component_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            )

            return {
                "project_key": project_key,
                "total_issues": len(project_issues),
                "by_type": type_counts,
                "by_status_category": status_counts,
                "by_priority": priority_counts,
                "top_assignees": assignee_counts,
                "top_labels": top_labels,
                "top_components": top_components,
            }

        except Exception as e:
            logger.error(f"Error getting aggregations for {project_key}: {e}")
            return {"project_key": project_key, "error": str(e)}

    def get_recent_issues(
        self,
        project_key: str | None = None,
        days: int = 7,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recently updated issues.

        Args:
            project_key: Optional project filter
            days: Number of days to look back
            limit: Maximum results

        Returns:
            List of recent issue records
        """
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        try:
            search = self.issues_table.search()
            where_parts = [f"updated_at >= '{cutoff_str}'"]

            if project_key:
                where_parts.append(f"project_key = '{project_key}'")

            search = search.where(" AND ".join(where_parts), prefilter=True)
            results = search.limit(limit).to_list()

            # Sort by updated_at descending
            results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return results

        except Exception as e:
            logger.warning(f"Error getting recent issues: {e}")
            return []

    def delete_issues(self, issue_ids: list[str]) -> int:
        """Delete issues by their keys.

        Args:
            issue_ids: List of issue keys to delete

        Returns:
            Number of issues deleted
        """
        if not issue_ids:
            return 0

        self.issues_table.delete(f"issue_id IN {_format_sql_in_clause(issue_ids)}")
        logger.info(f"Deleted {len(issue_ids)} issues")
        return len(issue_ids)

    def get_all_issue_ids(self, project_key: str | None = None) -> list[str]:
        """Get all indexed issue IDs, optionally filtered by project.

        Args:
            project_key: Optional project key filter

        Returns:
            List of issue IDs
        """
        try:
            search = self.issues_table.search().select(["issue_id"])

            if project_key:
                search = search.where(
                    f"project_key = '{project_key}'", prefilter=True
                )

            results = search.limit(1000000).to_list()
            return [r["issue_id"] for r in results]
        except Exception:
            return []

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the vector store.

        Returns:
            Dictionary with stats about indexed issues and comments
        """
        try:
            issue_count = len(self.issues_table.to_pandas())
        except Exception:
            issue_count = 0

        try:
            comment_count = len(self.comments_table.to_pandas())
        except Exception:
            comment_count = 0

        # Get unique projects
        try:
            issues_df = self.issues_table.to_pandas()
            if len(issues_df) > 0:
                projects = issues_df["project_key"].unique().tolist()
            else:
                projects = []
        except Exception:
            projects = []

        return {
            "total_issues": issue_count,
            "total_comments": comment_count,
            "projects": projects,
            "db_path": str(self.config.db_path),
        }

