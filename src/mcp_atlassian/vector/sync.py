"""Sync engine for indexing Jira issues into vector store."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.embeddings import EmbeddingPipeline
from mcp_atlassian.vector.schemas import (
    JiraCommentEmbedding,
    JiraIssueEmbedding,
    clean_jira_markup,
    compute_content_hash,
    prepare_comment_for_embedding,
    prepare_issue_for_embedding,
    truncate_at_sentence,
)
from mcp_atlassian.vector.store import LanceDBStore

if TYPE_CHECKING:
    from mcp_atlassian.jira import JiraFacade
    from mcp_atlassian.models.jira import JiraIssue

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    """Persistent state for tracking sync progress.

    Enables incremental sync by remembering the last sync timestamp
    and supports resumable syncs via checkpoints.
    """

    last_sync_at: datetime = field(default_factory=lambda: datetime.min)
    last_issue_updated: datetime = field(default_factory=lambda: datetime.min)
    projects_synced: list[str] = field(default_factory=list)
    total_issues_indexed: int = 0
    total_comments_indexed: int = 0
    embedding_model: str = "text-embedding-3-small"
    embedding_version: str = "1"

    # Checkpoint for resumable sync
    checkpoint_project: str | None = None
    checkpoint_offset: int = 0

    @classmethod
    def load(cls, path: Path) -> SyncState:
        """Load sync state from file.

        Args:
            path: Path to state file

        Returns:
            SyncState instance
        """
        if not path.exists():
            return cls()

        try:
            data = json.loads(path.read_text())
            # Convert datetime strings back to datetime objects
            if "last_sync_at" in data:
                data["last_sync_at"] = datetime.fromisoformat(data["last_sync_at"])
            if "last_issue_updated" in data:
                data["last_issue_updated"] = datetime.fromisoformat(
                    data["last_issue_updated"]
                )
            return cls(**data)
        except Exception as e:
            logger.warning(f"Failed to load sync state: {e}")
            return cls()

    def save(self, path: Path) -> None:
        """Save sync state to file.

        Args:
            path: Path to state file
        """
        data = {
            "last_sync_at": self.last_sync_at.isoformat(),
            "last_issue_updated": self.last_issue_updated.isoformat(),
            "projects_synced": self.projects_synced,
            "total_issues_indexed": self.total_issues_indexed,
            "total_comments_indexed": self.total_comments_indexed,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "checkpoint_project": self.checkpoint_project,
            "checkpoint_offset": self.checkpoint_offset,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


@dataclass
class SyncResult:
    """Result of a sync operation."""

    issues_processed: int = 0
    issues_embedded: int = 0
    issues_skipped: int = 0
    issues_deleted: int = 0  # Stale issues removed from index
    comments_processed: int = 0
    comments_embedded: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class VectorSyncEngine:
    """Engine for syncing Jira issues to the vector store.

    Supports both full bootstrap sync and incremental sync based on
    last updated timestamp.
    """

    def __init__(
        self,
        jira_facade: JiraFacade,
        config: VectorConfig | None = None,
    ) -> None:
        """Initialize the sync engine.

        Args:
            jira_facade: Jira client facade for API access
            config: Vector configuration
        """
        self.jira = jira_facade
        self.config = config or VectorConfig.from_env()
        self.store = LanceDBStore(config=self.config)
        self.embedder = EmbeddingPipeline(config=self.config)
        self._state_path = self.config.db_path / "sync_state.json"

    def _load_state(self) -> SyncState:
        """Load sync state from disk."""
        return SyncState.load(self._state_path)

    def _save_state(self, state: SyncState) -> None:
        """Save sync state to disk."""
        state.save(self._state_path)

    async def full_sync(
        self,
        projects: list[str] | None = None,
    ) -> SyncResult:
        """Perform a full sync of all issues.

        Args:
            projects: List of project keys to sync. If None, syncs all
                      projects from config or all accessible projects.

        Returns:
            SyncResult with statistics
        """
        start_time = datetime.utcnow()
        result = SyncResult()
        state = self._load_state()

        # Determine projects to sync
        if projects:
            projects_to_sync = projects
        elif self.config.sync_projects:
            projects_to_sync = self.config.sync_projects
        else:
            # Get all accessible projects
            projects_to_sync = await self._get_all_projects()

        logger.info(f"Starting full sync for projects: {projects_to_sync}")

        for project_key in projects_to_sync:
            try:
                project_result = await self._sync_project(
                    project_key, incremental=False, state=state
                )
                result.issues_processed += project_result.issues_processed
                result.issues_embedded += project_result.issues_embedded
                result.issues_skipped += project_result.issues_skipped
                result.errors.extend(project_result.errors)

                # Update state
                if project_key not in state.projects_synced:
                    state.projects_synced.append(project_key)

            except Exception as e:
                error_msg = f"Error syncing project {project_key}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        # Finalize state
        state.last_sync_at = datetime.utcnow()
        state.total_issues_indexed = result.issues_embedded
        self._save_state(state)

        result.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Full sync complete: {result.issues_embedded} issues indexed "
            f"in {result.duration_seconds:.1f}s"
        )

        return result

    async def incremental_sync(
        self,
        projects: list[str] | None = None,
    ) -> SyncResult:
        """Perform incremental sync of changed issues.

        Only syncs issues updated since the last sync.

        Args:
            projects: List of project keys to sync

        Returns:
            SyncResult with statistics
        """
        start_time = datetime.utcnow()
        result = SyncResult()
        state = self._load_state()

        # Use previously synced projects if none specified
        if projects:
            projects_to_sync = projects
        elif state.projects_synced:
            projects_to_sync = state.projects_synced
        elif self.config.sync_projects:
            projects_to_sync = self.config.sync_projects
        else:
            logger.warning("No projects specified for incremental sync")
            return result

        logger.info(
            f"Starting incremental sync for projects: {projects_to_sync} "
            f"(since {state.last_issue_updated})"
        )

        for project_key in projects_to_sync:
            try:
                project_result = await self._sync_project(
                    project_key, incremental=True, state=state
                )
                result.issues_processed += project_result.issues_processed
                result.issues_embedded += project_result.issues_embedded
                result.issues_skipped += project_result.issues_skipped
                result.errors.extend(project_result.errors)

            except Exception as e:
                error_msg = f"Error in incremental sync for {project_key}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        # Detect and remove deleted issues (periodically during incremental sync)
        # Only run deletion detection if we processed a significant number of issues
        # or if it's been a while since last deletion check
        if result.issues_processed > 0:
            for project_key in projects_to_sync:
                try:
                    deleted = await self._detect_and_remove_deleted_issues(project_key)
                    result.issues_deleted += deleted
                except Exception as e:
                    logger.warning(f"Deletion detection failed for {project_key}: {e}")

        # Finalize state
        state.last_sync_at = datetime.utcnow()
        state.total_issues_indexed += result.issues_embedded - result.issues_deleted
        self._save_state(state)

        result.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Incremental sync complete: {result.issues_embedded} updated, "
            f"{result.issues_deleted} deleted in {result.duration_seconds:.1f}s"
        )

        return result

    async def _detect_and_remove_deleted_issues(
        self,
        project_key: str,
        batch_size: int = 100,
    ) -> int:
        """Detect and remove issues that have been deleted from Jira.

        Compares indexed issue IDs against current Jira issues and removes
        stale entries from the vector index.

        Args:
            project_key: Project key to check
            batch_size: Number of issues to verify per Jira API call

        Returns:
            Number of deleted issues removed from index
        """
        # Get all indexed issue IDs for this project
        indexed_ids = self.store.get_all_issue_ids(project_key=project_key)
        if not indexed_ids:
            return 0

        logger.info(f"Checking {len(indexed_ids)} indexed issues for deletion in {project_key}")

        # Check which issues still exist in Jira (in batches)
        deleted_ids: list[str] = []
        indexed_list = list(indexed_ids)

        for i in range(0, len(indexed_list), batch_size):
            batch = indexed_list[i : i + batch_size]

            # Build JQL to find existing issues
            # Use issue key directly for efficiency
            keys_str = ", ".join(batch)
            jql = f"key in ({keys_str})"

            try:
                search_result = self.jira.search_issues(
                    jql=jql,
                    fields="key",
                    limit=len(batch),
                )
                existing_keys = {issue.key for issue in search_result.issues}

                # Find issues that no longer exist
                for issue_id in batch:
                    if issue_id not in existing_keys:
                        deleted_ids.append(issue_id)

            except Exception as e:
                logger.warning(f"Error checking issue existence: {e}")
                # Don't delete if we can't verify - could be a transient error
                continue

        # Remove deleted issues from index
        if deleted_ids:
            logger.info(f"Removing {len(deleted_ids)} deleted issues from index: {deleted_ids[:5]}...")
            self.store.delete_issues_by_ids(deleted_ids)

        return len(deleted_ids)

    async def _sync_project(
        self,
        project_key: str,
        incremental: bool,
        state: SyncState,
    ) -> SyncResult:
        """Sync a single project.

        Args:
            project_key: Project key to sync
            incremental: Whether this is an incremental sync
            state: Current sync state

        Returns:
            SyncResult for this project
        """
        result = SyncResult()

        # For full syncs, clear existing data for this project first
        if not incremental:
            cleared = self.store.clear_issues(project_key=project_key)
            if cleared > 0:
                logger.info(f"Cleared {cleared} existing issues for {project_key}")

        # Build JQL
        if incremental and state.last_issue_updated > datetime.min:
            updated_str = state.last_issue_updated.strftime("%Y-%m-%d %H:%M")
            jql = (
                f'project = "{project_key}" '
                f"AND updated >= '{updated_str}' "
                f"ORDER BY updated ASC"
            )
        else:
            # Only sync issues updated since 2022. Use ORDER BY key for stable
            # pagination (updated DESC causes duplicates as issues change)
            jql = (
                f'project = "{project_key}" '
                f'AND updated >= "2022-01-01" ORDER BY key DESC'
            )

        logger.info(f"Syncing project {project_key} with JQL: {jql}")

        # For Jira Cloud, pagination via 'start' offset doesn't work - the API
        # uses token-based pagination internally. Process in batches for embedding.
        embed_batch_size = 100 if not incremental else self.config.batch_size
        issues_to_embed: dict[str, dict[str, Any]] = {}  # Dedupe by issue_id
        synced_ids: set[str] = set()  # Track IDs to prevent cross-batch dupes
        max_updated = state.last_issue_updated
        last_key: str | None = None  # For key-based pagination

        while True:
            try:
                # Use key-based pagination: fetch issues with key < last_key
                # Insert the key filter before ORDER BY clause
                if last_key:
                    if "ORDER BY" in jql.upper():
                        parts = jql.upper().split("ORDER BY")
                        base_jql = jql[: len(parts[0])]
                        order_part = jql[len(parts[0]) :]
                        current_jql = f"{base_jql} AND key < '{last_key}' {order_part}"
                    else:
                        current_jql = f"{jql} AND key < '{last_key}'"
                else:
                    current_jql = jql

                search_result = self.jira.search_issues(
                    jql=current_jql,
                    fields="*all",
                    start=0,  # Always start from 0, use key filter for pagination
                    limit=1000,  # Fetch more per call, internal pagination handles it
                )

                if not search_result.issues:
                    break

                # Track the last key for next iteration
                last_key = search_result.issues[-1].key

                for issue in search_result.issues:
                    result.issues_processed += 1

                    # Convert to dict for processing
                    issue_dict = self._issue_to_dict(issue)
                    issue_id = issue_dict["issue_id"]

                    # Skip if already synced this run (prevents cross-batch duplicates)
                    if issue_id in synced_ids:
                        result.issues_skipped += 1
                        continue

                    # Check if content changed (skip if hash matches)
                    content_hash = compute_content_hash(
                        summary=issue_dict["summary"],
                        description=issue_dict.get("description"),
                        labels=issue_dict.get("labels", []),
                        status=issue_dict["status"],
                    )

                    if incremental:
                        existing = self.store.get_issue_by_key(issue_id)
                        if existing and existing.content_hash == content_hash:
                            result.issues_skipped += 1
                            continue

                    issue_dict["content_hash"] = content_hash
                    issues_to_embed[issue_dict["issue_id"]] = issue_dict  # Dedupe by ID

                    # Track max updated time (parse string to datetime for comparison)
                    updated_at_str = issue_dict["updated_at"]
                    if isinstance(updated_at_str, str):
                        try:
                            updated_at_dt = datetime.fromisoformat(
                                updated_at_str.replace("Z", "+00:00")
                            )
                        except ValueError:
                            updated_at_dt = datetime.utcnow()
                    else:
                        updated_at_dt = updated_at_str

                    if updated_at_dt > max_updated:
                        max_updated = updated_at_dt

                # Embed and store in batches
                if len(issues_to_embed) >= embed_batch_size:
                    embedded_count = await self._embed_and_store(
                        list(issues_to_embed.values()), bulk_insert=not incremental
                    )
                    result.issues_embedded += embedded_count
                    # Track synced IDs to prevent duplicates in future batches
                    synced_ids.update(issues_to_embed.keys())
                    logger.info(
                        f"Progress: {result.issues_embedded} embedded, "
                        f"{result.issues_processed} processed, {len(synced_ids)} unique"
                    )
                    issues_to_embed = {}

                # Check if we got fewer results than requested (last page)
                if len(search_result.issues) < 1000:
                    break

            except Exception as e:
                error_msg = f"Error fetching issues (last_key={last_key}): {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                break

        # Process remaining issues
        if issues_to_embed:
            embedded_count = await self._embed_and_store(
                list(issues_to_embed.values()), bulk_insert=not incremental
            )
            result.issues_embedded += embedded_count
            synced_ids.update(issues_to_embed.keys())

        # Compact the table after full sync to reduce storage
        if not incremental and result.issues_embedded > 0:
            logger.info("Compacting database after full sync...")
            self.store.compact()

        # Update state with max updated time
        if max_updated > state.last_issue_updated:
            state.last_issue_updated = max_updated

        # Sync comments for embedded issues (if enabled)
        if self.config.sync_comments and result.issues_embedded > 0:
            all_issue_keys = self.store.get_all_issue_ids(project_key=project_key)
            # Limit to recently processed issues for incremental sync
            if incremental:
                # Only sync comments for issues that were just embedded
                issue_keys_to_sync = [
                    i["issue_id"] for i in issues_to_embed
                ] if issues_to_embed else []
            else:
                issue_keys_to_sync = all_issue_keys[:100]  # Limit for full sync

            if issue_keys_to_sync:
                logger.info(f"Syncing comments for {len(issue_keys_to_sync)} issues")
                comments_processed, comments_embedded, comment_errors = (
                    await self._sync_comments_for_issues(issue_keys_to_sync)
                )
                result.comments_processed += comments_processed
                result.comments_embedded += comments_embedded
                result.errors.extend(comment_errors)

        return result

    async def _embed_and_store(
        self,
        issues: list[dict[str, Any]],
        bulk_insert: bool = False,
    ) -> int:
        """Embed issues and store in vector database.

        Args:
            issues: List of issue dictionaries to embed
            bulk_insert: If True, use bulk insert (faster for full syncs)

        Returns:
            Number of issues successfully embedded
        """
        if not issues:
            return 0

        # Prepare texts for embedding
        texts = [prepare_issue_for_embedding(issue) for issue in issues]

        # Generate embeddings
        embeddings = await self.embedder.embed_batch(texts)

        # Create embedding records
        records = []
        for issue, embedding in zip(issues, embeddings, strict=False):
            record = JiraIssueEmbedding(
                issue_id=issue["issue_id"],
                project_key=issue["project_key"],
                vector=embedding,
                summary=issue["summary"],
                description_preview=issue.get("description_preview", ""),
                issue_type=issue["issue_type"],
                status=issue["status"],
                status_category=issue.get("status_category", "To Do"),
                priority=issue.get("priority"),
                assignee=issue.get("assignee"),
                reporter=issue.get("reporter", "Unknown"),
                labels=issue.get("labels", []),
                components=issue.get("components", []),
                created_at=issue["created_at"],
                updated_at=issue["updated_at"],
                resolved_at=issue.get("resolved_at"),
                parent_key=issue.get("parent_key"),
                linked_issues=issue.get("linked_issues", []),
                content_hash=issue["content_hash"],
                embedding_version=self.config.embedding_model,
                indexed_at=datetime.utcnow(),
            )
            records.append(record)

        # Store in vector database
        if bulk_insert:
            count = self.store.bulk_insert_issues(records)
        else:
            count = self.store.upsert_issues(records)
        logger.debug(f"Stored {count} issue embeddings")

        return count

    async def _sync_comments_for_issues(
        self,
        issue_keys: list[str],
    ) -> tuple[int, int, list[str]]:
        """Fetch and embed comments for a list of issues.

        Args:
            issue_keys: List of issue keys to fetch comments for

        Returns:
            Tuple of (comments_processed, comments_embedded, errors)
        """
        comments_processed = 0
        comments_embedded = 0
        errors: list[str] = []
        comments_to_embed: list[dict[str, Any]] = []

        for issue_key in issue_keys:
            try:
                # Fetch comments via Jira API
                comments_result = self.jira.get_issue_comments(issue_key)
                if not comments_result:
                    continue

                # Get parent issue info for denormalization
                issue = self.store.get_issue_by_key(issue_key)
                if not issue:
                    continue

                issue_dict = {
                    "issue_id": issue.issue_id,
                    "summary": issue.summary,
                    "project_key": issue.project_key,
                    "issue_type": issue.issue_type,
                    "status": issue.status,
                }

                for comment in comments_result:
                    comments_processed += 1
                    comment_dict = self._comment_to_dict(comment, issue_dict)
                    if comment_dict:
                        comments_to_embed.append(comment_dict)

                # Embed in batches
                if len(comments_to_embed) >= self.config.batch_size:
                    count = await self._embed_and_store_comments(comments_to_embed)
                    comments_embedded += count
                    comments_to_embed = []

            except Exception as e:
                error_msg = f"Error fetching comments for {issue_key}: {e}"
                logger.warning(error_msg)
                errors.append(error_msg)

        # Process remaining comments
        if comments_to_embed:
            count = await self._embed_and_store_comments(comments_to_embed)
            comments_embedded += count

        return comments_processed, comments_embedded, errors

    async def _embed_and_store_comments(
        self,
        comments: list[dict[str, Any]],
    ) -> int:
        """Embed comments and store in vector database.

        Args:
            comments: List of comment dictionaries to embed

        Returns:
            Number of comments successfully embedded
        """
        if not comments:
            return 0

        # Prepare texts for embedding
        texts = []
        for comment in comments:
            issue_dict = {
                "issue_id": comment["issue_key"],
                "summary": comment.get("issue_summary", ""),
            }
            text = prepare_comment_for_embedding(comment, issue_dict)
            texts.append(text)

        # Generate embeddings
        embeddings = await self.embedder.embed_batch(texts)

        # Create embedding records
        records = []
        for comment, embedding in zip(comments, embeddings, strict=False):
            # Compute content hash for change detection
            content_hash = hashlib.md5(
                comment.get("body", "").encode()
            ).hexdigest()

            record = JiraCommentEmbedding(
                comment_id=comment["comment_id"],
                issue_key=comment["issue_key"],
                vector=embedding,
                body_preview=comment.get("body_preview", ""),
                author=comment.get("author", "Unknown"),
                created_at=comment.get("created_at", datetime.utcnow()),
                project_key=comment.get("project_key", ""),
                issue_type=comment.get("issue_type", ""),
                issue_status=comment.get("issue_status", ""),
                content_hash=content_hash,
                indexed_at=datetime.utcnow(),
            )
            records.append(record)

        # Store in vector database
        count = self.store.upsert_comments(records)
        logger.debug(f"Stored {count} comment embeddings")

        return count

    def _comment_to_dict(
        self, comment: Any, issue_dict: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Convert comment to dictionary for embedding.

        Args:
            comment: Comment object from Jira API
            issue_dict: Parent issue information

        Returns:
            Dictionary with required fields or None if invalid
        """
        try:
            # Handle different comment object formats
            # Skip if comment is a string (sometimes raw text is passed)
            if isinstance(comment, str):
                return None
            if hasattr(comment, "id"):
                comment_id = str(comment.id)
            elif isinstance(comment, dict):
                comment_id = str(comment.get("id", ""))
            else:
                return None

            if not comment_id:
                return None

            # Get body
            if hasattr(comment, "body"):
                body = comment.body or ""
            elif isinstance(comment, dict):
                body = comment.get("body", "")
            else:
                body = ""

            # Clean and truncate body
            clean_body = clean_jira_markup(body)
            body_preview = truncate_at_sentence(clean_body, max_chars=300)

            # Get author with robust type checking
            author = "Unknown"
            if hasattr(comment, "author") and comment.author:
                author = getattr(comment.author, "displayName", None)
                if not author:
                    author = getattr(comment.author, "name", "Unknown")
            elif isinstance(comment, dict):
                author_data = comment.get("author")
                if isinstance(author_data, dict):
                    author = author_data.get(
                        "displayName", author_data.get("name", "Unknown")
                    )
                elif isinstance(author_data, str):
                    author = author_data

            # Get created date
            if hasattr(comment, "created"):
                created_at = comment.created
            elif isinstance(comment, dict):
                created_str = comment.get("created", "")
                if created_str:
                    created_at = datetime.fromisoformat(
                        created_str.replace("Z", "+00:00")
                    )
                else:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()

            return {
                "comment_id": comment_id,
                "issue_key": issue_dict["issue_id"],
                "issue_summary": issue_dict.get("summary", ""),
                "body": body,
                "body_preview": body_preview,
                "author": author,
                "created_at": created_at,
                "project_key": issue_dict.get("project_key", ""),
                "issue_type": issue_dict.get("issue_type", ""),
                "issue_status": issue_dict.get("status", ""),
            }
        except Exception as e:
            logger.warning(f"Error processing comment: {e}")
            return None

    def _issue_to_dict(self, issue: JiraIssue) -> dict[str, Any]:
        """Convert JiraIssue model to dictionary for embedding.

        Args:
            issue: JiraIssue model instance

        Returns:
            Dictionary with required fields
        """
        # Get description preview
        description = issue.description or ""
        if description:
            clean_desc = clean_jira_markup(description)
            description_preview = truncate_at_sentence(clean_desc, max_chars=500)
        else:
            description_preview = ""

        # Extract project key from issue key
        project_key = issue.key.split("-")[0] if issue.key else ""

        # Get status category
        status_category = "To Do"
        if hasattr(issue, "status") and issue.status:
            if isinstance(issue.status, str):
                status_name = issue.status.lower()
            else:
                status_name = str(issue.status).lower()
            done_terms = ["done", "closed", "resolved", "complete"]
            progress_terms = ["progress", "review", "testing", "active"]
            if any(s in status_name for s in done_terms):
                status_category = "Done"
            elif any(s in status_name for s in progress_terms):
                status_category = "In Progress"

        # Get linked issues
        linked_issues = []
        if hasattr(issue, "links") and issue.links:
            for link in issue.links:
                if hasattr(link, "inward_issue") and link.inward_issue:
                    linked_issues.append(link.inward_issue)
                if hasattr(link, "outward_issue") and link.outward_issue:
                    linked_issues.append(link.outward_issue)

        # Extract string values from nested objects
        issue_type_name = issue.issue_type.name if issue.issue_type else "Task"
        status_name = issue.status.name if issue.status else "Open"
        priority_name = issue.priority.name if issue.priority else None
        assignee_name = issue.assignee.display_name if issue.assignee else None
        reporter_name = issue.reporter.display_name if issue.reporter else "Unknown"

        return {
            "issue_id": issue.key,
            "project_key": project_key,
            "summary": issue.summary or "",
            "description": description,
            "description_preview": description_preview,
            "issue_type": issue_type_name,
            "status": status_name,
            "status_category": status_category,
            "priority": priority_name,
            "assignee": assignee_name,
            "reporter": reporter_name,
            "labels": issue.labels or [],
            "components": list(issue.components or []),
            "created_at": issue.created or datetime.utcnow().isoformat(),
            "updated_at": issue.updated or datetime.utcnow().isoformat(),
            "resolved_at": issue.resolutiondate,
            "parent_key": issue.parent.get("key") if issue.parent else None,
            "linked_issues": linked_issues,
        }

    async def _get_all_projects(self) -> list[str]:
        """Get all accessible project keys.

        Returns:
            List of project keys
        """
        try:
            projects = self.jira.get_all_projects()
            return [p.key for p in projects if hasattr(p, "key")]
        except Exception as e:
            logger.error(f"Error fetching projects: {e}")
            return []

    def get_sync_status(self) -> dict[str, Any]:
        """Get current sync status.

        Returns:
            Dictionary with sync statistics
        """
        state = self._load_state()
        store_stats = self.store.get_stats()

        return {
            "last_sync_at": state.last_sync_at.isoformat()
            if state.last_sync_at > datetime.min
            else None,
            "last_issue_updated": state.last_issue_updated.isoformat()
            if state.last_issue_updated > datetime.min
            else None,
            "projects_synced": state.projects_synced,
            "total_issues_indexed": store_stats["total_issues"],
            "total_comments_indexed": store_stats["total_comments"],
            "embedding_model": state.embedding_model,
            "db_path": str(self.config.db_path),
        }


async def run_sync(
    jira_facade: JiraFacade,
    projects: list[str] | None = None,
    full: bool = False,
    config: VectorConfig | None = None,
) -> SyncResult:
    """Run a sync operation.

    Convenience function for running sync from CLI or scripts.

    Args:
        jira_facade: Jira client facade
        projects: Projects to sync
        full: Whether to do a full sync (vs incremental)
        config: Optional vector config

    Returns:
        SyncResult with statistics
    """
    engine = VectorSyncEngine(jira_facade, config=config)

    if full:
        return await engine.full_sync(projects=projects)
    else:
        return await engine.incremental_sync(projects=projects)
