"""Sync engine for indexing Jira issues into vector store."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.embeddings import EmbeddingPipeline
from mcp_atlassian.vector.schemas import (
    JiraIssueEmbedding,
    clean_jira_markup,
    compute_content_hash,
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

        # Finalize state
        state.last_sync_at = datetime.utcnow()
        state.total_issues_indexed += result.issues_embedded
        self._save_state(state)

        result.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Incremental sync complete: {result.issues_embedded} issues updated "
            f"in {result.duration_seconds:.1f}s"
        )

        return result

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

        # Build JQL
        if incremental and state.last_issue_updated > datetime.min:
            updated_str = state.last_issue_updated.strftime("%Y-%m-%d %H:%M")
            jql = (
                f'project = "{project_key}" '
                f"AND updated >= '{updated_str}' "
                f"ORDER BY updated ASC"
            )
        else:
            jql = f'project = "{project_key}" ORDER BY created ASC'

        logger.info(f"Syncing project {project_key} with JQL: {jql}")

        # Fetch issues in batches
        offset = 0
        batch_size = 100
        issues_to_embed: list[dict[str, Any]] = []
        max_updated = state.last_issue_updated

        while True:
            try:
                search_result = self.jira.search_issues(
                    jql=jql,
                    fields="*all",
                    start=offset,
                    limit=batch_size,
                )

                if not search_result.issues:
                    break

                for issue in search_result.issues:
                    result.issues_processed += 1

                    # Convert to dict for processing
                    issue_dict = self._issue_to_dict(issue)

                    # Check if content changed (skip if hash matches)
                    content_hash = compute_content_hash(
                        summary=issue_dict["summary"],
                        description=issue_dict.get("description"),
                        labels=issue_dict.get("labels", []),
                        status=issue_dict["status"],
                    )

                    if incremental:
                        existing = self.store.get_issue_by_key(issue_dict["issue_id"])
                        if existing and existing.content_hash == content_hash:
                            result.issues_skipped += 1
                            continue

                    issue_dict["content_hash"] = content_hash
                    issues_to_embed.append(issue_dict)

                    # Track max updated time
                    if issue_dict["updated_at"] > max_updated:
                        max_updated = issue_dict["updated_at"]

                # Embed and store in batches
                if len(issues_to_embed) >= self.config.batch_size:
                    embedded_count = await self._embed_and_store(issues_to_embed)
                    result.issues_embedded += embedded_count
                    issues_to_embed = []

                offset += batch_size

                # Check if we got fewer results than requested (last page)
                if len(search_result.issues) < batch_size:
                    break

            except Exception as e:
                error_msg = f"Error fetching issues at offset {offset}: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                break

        # Process remaining issues
        if issues_to_embed:
            embedded_count = await self._embed_and_store(issues_to_embed)
            result.issues_embedded += embedded_count

        # Update state with max updated time
        if max_updated > state.last_issue_updated:
            state.last_issue_updated = max_updated

        return result

    async def _embed_and_store(
        self,
        issues: list[dict[str, Any]],
    ) -> int:
        """Embed issues and store in vector database.

        Args:
            issues: List of issue dictionaries to embed

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
        count = self.store.upsert_issues(records)
        logger.debug(f"Stored {count} issue embeddings")

        return count

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

        return {
            "issue_id": issue.key,
            "project_key": project_key,
            "summary": issue.summary or "",
            "description": description,
            "description_preview": description_preview,
            "issue_type": issue.issue_type or "Task",
            "status": issue.status or "Open",
            "status_category": status_category,
            "priority": issue.priority,
            "assignee": issue.assignee,
            "reporter": issue.reporter or "Unknown",
            "labels": issue.labels or [],
            "components": list(issue.components or []),
            "created_at": issue.created or datetime.utcnow(),
            "updated_at": issue.updated or datetime.utcnow(),
            "resolved_at": issue.resolution_date,
            "parent_key": issue.parent_key,
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
