"""Tests for the vector schemas module."""

from datetime import datetime

import pytest

from mcp_atlassian.vector.schemas import (
    JiraCommentEmbedding,
    JiraIssueEmbedding,
    clean_jira_markup,
    compute_content_hash,
    prepare_comment_for_embedding,
    prepare_issue_for_embedding,
    truncate_at_sentence,
)


class TestCleanJiraMarkup:
    """Tests for clean_jira_markup function."""

    def test_removes_code_blocks(self):
        """Test that code blocks are removed."""
        text = "Before {code}some code here{code} After"
        result = clean_jira_markup(text)
        assert "some code here" not in result
        assert "Before" in result
        assert "After" in result

    def test_keeps_noformat_content(self):
        """Test that noformat content is kept but tags removed."""
        text = "Before {noformat}preformatted text{noformat} After"
        result = clean_jira_markup(text)
        assert "preformatted text" in result
        assert "{noformat}" not in result

    def test_keeps_panel_content(self):
        """Test that panel content is kept but tags removed."""
        text = "{panel:title=Test}Panel content{panel}"
        result = clean_jira_markup(text)
        assert "Panel content" in result
        assert "{panel" not in result

    def test_cleans_mention_links(self):
        """Test that @mentions are preserved without brackets."""
        text = "Thanks [~accountid:abc123] for the help"
        result = clean_jira_markup(text)
        # Should remove the accountid part but keep something readable
        assert "[~accountid" not in result

    def test_cleans_issue_links(self):
        """Test that issue links are preserved."""
        text = "Related to [PROJ-123]"
        result = clean_jira_markup(text)
        assert "PROJ-123" in result

    def test_normalizes_whitespace(self):
        """Test that excessive whitespace is normalized."""
        text = "Hello    world\n\n\n\ntest"
        result = clean_jira_markup(text)
        assert "    " not in result
        assert "\n\n\n\n" not in result

    def test_handles_empty_string(self):
        """Test that empty strings are handled."""
        assert clean_jira_markup("") == ""

    def test_handles_none(self):
        """Test that None is handled."""
        assert clean_jira_markup(None) == ""


class TestTruncateAtSentence:
    """Tests for truncate_at_sentence function."""

    def test_short_text_unchanged(self):
        """Test that short text is not truncated."""
        text = "Short text."
        result = truncate_at_sentence(text, max_chars=100)
        assert result == text

    def test_truncates_at_sentence_boundary(self):
        """Test that truncation happens at sentence boundary."""
        text = "First sentence. Second sentence. Third sentence."
        result = truncate_at_sentence(text, max_chars=30)
        assert result.endswith(".")
        assert len(result) <= 30

    def test_truncates_at_word_boundary(self):
        """Test that if no sentence boundary, truncates at word."""
        text = "This is a long sentence without any ending punctuation"
        result = truncate_at_sentence(text, max_chars=20)
        assert len(result) <= 23  # Some buffer for "..."
        assert not result.endswith(" ")

    def test_handles_empty_string(self):
        """Test empty string handling."""
        assert truncate_at_sentence("", max_chars=100) == ""

    def test_handles_single_long_word(self):
        """Test handling of single very long word."""
        text = "a" * 200
        result = truncate_at_sentence(text, max_chars=50)
        assert len(result) <= 53


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_consistent_hash(self):
        """Test that same content produces same hash."""
        hash1 = compute_content_hash(
            summary="Test",
            description="Desc",
            labels=["a", "b"],
            status="Open",
        )
        hash2 = compute_content_hash(
            summary="Test",
            description="Desc",
            labels=["a", "b"],
            status="Open",
        )
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        hash1 = compute_content_hash(
            summary="Test 1",
            description="Desc",
            labels=[],
            status="Open",
        )
        hash2 = compute_content_hash(
            summary="Test 2",
            description="Desc",
            labels=[],
            status="Open",
        )
        assert hash1 != hash2

    def test_label_order_does_not_matter(self):
        """Test that label order does not affect hash (sorted internally)."""
        hash1 = compute_content_hash(
            summary="Test",
            description=None,
            labels=["a", "b"],
            status="Open",
        )
        hash2 = compute_content_hash(
            summary="Test",
            description=None,
            labels=["b", "a"],
            status="Open",
        )
        # Labels are sorted before hashing
        assert hash1 == hash2

    def test_handles_none_description(self):
        """Test that None description is handled."""
        hash1 = compute_content_hash(
            summary="Test",
            description=None,
            labels=[],
            status="Open",
        )
        assert hash1 is not None
        assert len(hash1) == 32  # MD5 hex


class TestPrepareIssueForEmbedding:
    """Tests for prepare_issue_for_embedding function."""

    def test_formats_issue_correctly(self):
        """Test that issue is formatted for embedding."""
        issue = {
            "summary": "Fix the bug",
            "description": "There is a bug in the login",
            "issue_type": "Bug",
            "project_key": "PROJ",
            "status": "Open",
            "labels": ["critical"],
            "components": ["auth"],
        }
        result = prepare_issue_for_embedding(issue)

        assert "Issue: Fix the bug" in result
        assert "bug in the login" in result
        assert "Bug" in result
        assert "Status: Open" in result
        assert "Labels: critical" in result
        assert "Components: auth" in result

    def test_handles_missing_fields(self):
        """Test that missing fields don't cause errors."""
        issue = {
            "summary": "Test issue",
        }
        result = prepare_issue_for_embedding(issue)
        assert "Test issue" in result

    def test_handles_empty_description(self):
        """Test that empty description is handled."""
        issue = {
            "summary": "Test",
            "description": "",
        }
        result = prepare_issue_for_embedding(issue)
        assert "Test" in result


class TestPrepareCommentForEmbedding:
    """Tests for prepare_comment_for_embedding function."""

    def test_formats_comment_correctly(self):
        """Test that comment is formatted for embedding."""
        comment = {
            "body": "This is the fix approach",
            "author": "John Doe",
        }
        issue = {
            "issue_id": "PROJ-123",
            "summary": "Bug in login",
        }
        result = prepare_comment_for_embedding(comment, issue)

        assert "PROJ-123" in result
        assert "Bug in login" in result
        assert "This is the fix approach" in result
        assert "Author: John Doe" in result


class TestJiraIssueEmbedding:
    """Tests for JiraIssueEmbedding model."""

    def test_model_fields_defined(self):
        """Test that required fields are defined in the model."""
        # Check that the model has expected fields
        fields = JiraIssueEmbedding.model_fields
        assert "issue_id" in fields
        assert "project_key" in fields
        assert "vector" in fields
        assert "summary" in fields
        assert "issue_type" in fields
        assert "status" in fields
        assert "reporter" in fields
        assert "content_hash" in fields

    def test_optional_fields_defined(self):
        """Test that optional fields are defined."""
        fields = JiraIssueEmbedding.model_fields
        assert "priority" in fields
        assert "assignee" in fields
        assert "parent_key" in fields
        assert "resolved_at" in fields
        # Check that optional fields have defaults
        assert fields["priority"].default is None
        assert fields["assignee"].default is None


class TestJiraCommentEmbedding:
    """Tests for JiraCommentEmbedding model."""

    def test_model_fields_defined(self):
        """Test that required fields are defined in the model."""
        fields = JiraCommentEmbedding.model_fields
        assert "comment_id" in fields
        assert "issue_key" in fields
        assert "vector" in fields
        assert "body_preview" in fields
        assert "author" in fields
        assert "created_at" in fields
        assert "project_key" in fields
        assert "content_hash" in fields
