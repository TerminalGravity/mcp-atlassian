"""Tests for the vector sync module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.sync import SyncResult, SyncState, VectorSyncEngine


class TestSyncState:
    """Tests for SyncState class."""

    def test_default_state(self):
        """Test default state values."""
        state = SyncState()
        assert state.last_sync_at == datetime.min
        assert state.last_issue_updated == datetime.min
        assert state.projects_synced == []
        assert state.total_issues_indexed == 0
        assert state.total_comments_indexed == 0
        assert state.embedding_model == "text-embedding-3-small"
        assert state.checkpoint_project is None
        assert state.checkpoint_offset == 0

    def test_save_and_load(self, tmp_path):
        """Test saving and loading state."""
        state_path = tmp_path / "sync_state.json"

        # Create and save state
        state = SyncState(
            last_sync_at=datetime(2024, 1, 15, 10, 30),
            last_issue_updated=datetime(2024, 1, 15, 9, 0),
            projects_synced=["PROJ", "ENG"],
            total_issues_indexed=100,
            total_comments_indexed=50,
        )
        state.save(state_path)

        # Load and verify
        loaded = SyncState.load(state_path)
        assert loaded.last_sync_at == datetime(2024, 1, 15, 10, 30)
        assert loaded.last_issue_updated == datetime(2024, 1, 15, 9, 0)
        assert loaded.projects_synced == ["PROJ", "ENG"]
        assert loaded.total_issues_indexed == 100
        assert loaded.total_comments_indexed == 50

    def test_load_missing_file(self, tmp_path):
        """Test loading from non-existent file returns default state."""
        state_path = tmp_path / "nonexistent.json"
        state = SyncState.load(state_path)

        assert state.last_sync_at == datetime.min
        assert state.projects_synced == []

    def test_load_corrupted_file(self, tmp_path):
        """Test loading corrupted file returns default state."""
        state_path = tmp_path / "corrupted.json"
        state_path.write_text("not valid json")

        state = SyncState.load(state_path)
        assert state.last_sync_at == datetime.min

    def test_save_creates_directory(self, tmp_path):
        """Test that save creates parent directories."""
        state_path = tmp_path / "nested" / "dir" / "state.json"
        state = SyncState()
        state.save(state_path)

        assert state_path.exists()


class TestSyncResult:
    """Tests for SyncResult class."""

    def test_default_result(self):
        """Test default result values."""
        result = SyncResult()
        assert result.issues_processed == 0
        assert result.issues_embedded == 0
        assert result.issues_skipped == 0
        assert result.comments_processed == 0
        assert result.comments_embedded == 0
        assert result.errors == []
        assert result.duration_seconds == 0.0

    def test_accumulate_results(self):
        """Test accumulating results."""
        result = SyncResult()
        result.issues_processed += 10
        result.issues_embedded += 8
        result.issues_skipped += 2
        result.errors.append("Error 1")

        assert result.issues_processed == 10
        assert result.issues_embedded == 8
        assert result.issues_skipped == 2
        assert len(result.errors) == 1


class TestVectorSyncEngine:
    """Tests for VectorSyncEngine class."""

    @pytest.fixture
    def mock_jira(self):
        """Create mock Jira facade."""
        mock = MagicMock()
        mock.search_issues.return_value = MagicMock(issues=[])
        mock.get_all_projects.return_value = []
        return mock

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return VectorConfig(
            db_path=tmp_path / "lancedb",
            batch_size=10,
            sync_comments=False,
        )

    def test_engine_initialization(self, mock_jira, config):
        """Test engine initialization."""
        engine = VectorSyncEngine(mock_jira, config=config)

        assert engine.jira == mock_jira
        assert engine.config == config
        assert engine._state_path == config.db_path / "sync_state.json"

    def test_load_state(self, mock_jira, config, tmp_path):
        """Test loading state from disk."""
        # Create state file
        config.db_path.mkdir(parents=True, exist_ok=True)
        state_path = config.db_path / "sync_state.json"
        state_data = {
            "last_sync_at": "2024-01-15T10:30:00",
            "last_issue_updated": "2024-01-15T09:00:00",
            "projects_synced": ["PROJ"],
            "total_issues_indexed": 50,
            "total_comments_indexed": 0,
            "embedding_model": "text-embedding-3-small",
            "embedding_version": "1",
            "checkpoint_project": None,
            "checkpoint_offset": 0,
        }
        state_path.write_text(json.dumps(state_data))

        engine = VectorSyncEngine(mock_jira, config=config)
        state = engine._load_state()

        assert state.projects_synced == ["PROJ"]
        assert state.total_issues_indexed == 50

    @pytest.mark.asyncio
    async def test_full_sync_empty_projects(self, mock_jira, config):
        """Test full sync with no projects configured."""
        mock_jira.get_all_projects.return_value = []

        engine = VectorSyncEngine(mock_jira, config=config)

        with patch.object(engine, "_sync_project", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = SyncResult()

            result = await engine.full_sync()

            # Should not sync anything if no projects
            assert result.issues_processed == 0

    @pytest.mark.asyncio
    async def test_full_sync_with_projects(self, mock_jira, config):
        """Test full sync with specified projects."""
        engine = VectorSyncEngine(mock_jira, config=config)

        project_result = SyncResult(
            issues_processed=10,
            issues_embedded=8,
            issues_skipped=2,
        )

        with patch.object(engine, "_sync_project", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = project_result

            result = await engine.full_sync(projects=["PROJ", "ENG"])

            assert mock_sync.call_count == 2
            assert result.issues_processed == 20
            assert result.issues_embedded == 16

    @pytest.mark.asyncio
    async def test_incremental_sync_no_prior_state(self, mock_jira, config):
        """Test incremental sync with no prior sync state."""
        config.sync_projects = ["PROJ"]
        engine = VectorSyncEngine(mock_jira, config=config)

        with patch.object(engine, "_sync_project", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = SyncResult()

            result = await engine.incremental_sync()

            # Should use config projects when no prior state
            mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_project_builds_correct_jql(self, mock_jira, config):
        """Test that sync builds correct JQL for project."""
        engine = VectorSyncEngine(mock_jira, config=config)

        # Mock the search to return no issues
        mock_jira.search_issues.return_value = MagicMock(issues=[])

        state = SyncState()
        with patch.object(engine.store, "get_all_issue_ids", return_value=[]):
            result = await engine._sync_project("PROJ", incremental=False, state=state)

        # Check JQL was built correctly
        call_args = mock_jira.search_issues.call_args
        jql = call_args[1]["jql"]
        assert 'project = "PROJ"' in jql
        assert "ORDER BY created ASC" in jql

    def test_issue_to_dict(self, mock_jira, config):
        """Test converting JiraIssue to dictionary."""
        engine = VectorSyncEngine(mock_jira, config=config)

        # Create mock issue with proper nested objects
        mock_issue_type = MagicMock()
        mock_issue_type.name = "Bug"

        mock_status = MagicMock()
        mock_status.name = "Open"

        mock_priority = MagicMock()
        mock_priority.name = "High"

        mock_assignee = MagicMock()
        mock_assignee.display_name = "John"

        mock_reporter = MagicMock()
        mock_reporter.display_name = "Jane"

        mock_issue = MagicMock()
        mock_issue.key = "PROJ-123"
        mock_issue.summary = "Test issue"
        mock_issue.description = "Test description"
        mock_issue.issue_type = mock_issue_type
        mock_issue.status = mock_status
        mock_issue.priority = mock_priority
        mock_issue.assignee = mock_assignee
        mock_issue.reporter = mock_reporter
        mock_issue.labels = ["critical"]
        mock_issue.components = ["auth"]
        mock_issue.created = "2024-01-15T10:00:00"
        mock_issue.updated = "2024-01-15T12:00:00"
        mock_issue.resolutiondate = None
        mock_issue.parent = None
        mock_issue.links = []

        result = engine._issue_to_dict(mock_issue)

        assert result["issue_id"] == "PROJ-123"
        assert result["project_key"] == "PROJ"
        assert result["summary"] == "Test issue"
        assert result["issue_type"] == "Bug"
        assert result["status"] == "Open"
        assert result["priority"] == "High"
        assert result["assignee"] == "John"
        assert result["reporter"] == "Jane"
        assert result["labels"] == ["critical"]

    def test_issue_to_dict_with_parent(self, mock_jira, config):
        """Test converting issue with parent."""
        engine = VectorSyncEngine(mock_jira, config=config)

        mock_issue = MagicMock()
        mock_issue.key = "PROJ-124"
        mock_issue.summary = "Sub-task"
        mock_issue.description = None
        mock_issue.issue_type = MagicMock(name="Sub-task")
        mock_issue.status = MagicMock(name="Open")
        mock_issue.priority = None
        mock_issue.assignee = None
        mock_issue.reporter = MagicMock(display_name="Jane")
        mock_issue.labels = []
        mock_issue.components = []
        mock_issue.created = "2024-01-15T10:00:00"
        mock_issue.updated = "2024-01-15T12:00:00"
        mock_issue.resolutiondate = None
        mock_issue.parent = {"key": "PROJ-100"}
        mock_issue.links = []

        result = engine._issue_to_dict(mock_issue)

        assert result["parent_key"] == "PROJ-100"

    def test_get_sync_status(self, mock_jira, config):
        """Test getting sync status."""
        engine = VectorSyncEngine(mock_jira, config=config)

        with patch.object(engine.store, "get_stats") as mock_stats:
            mock_stats.return_value = {
                "total_issues": 100,
                "total_comments": 50,
                "projects": ["PROJ"],
            }

            status = engine.get_sync_status()

            assert status["total_issues_indexed"] == 100
            assert status["total_comments_indexed"] == 50
            assert str(config.db_path) in status["db_path"]
