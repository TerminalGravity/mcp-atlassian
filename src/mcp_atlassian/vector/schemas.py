"""LanceDB schemas for Jira vector storage."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from lancedb.pydantic import LanceModel, Vector
from pydantic import Field


class JiraIssueEmbedding(LanceModel):
    """Schema for Jira issue embeddings in LanceDB.

    This model defines the structure for storing Jira issues with their
    vector embeddings for semantic search.
    """

    # Identity
    issue_id: str = Field(description="Jira issue key (e.g., PROJ-123)")
    project_key: str = Field(description="Project key extracted from issue_id")

    # Vector embedding (1536 dims for OpenAI text-embedding-3-small)
    vector: Vector(1536)  # type: ignore[valid-type]

    # Core text fields (indexed for FTS)
    summary: str = Field(description="Issue summary/title")
    description_preview: str = Field(
        default="", description="First 500 chars of description"
    )

    # Filterable metadata
    issue_type: str = Field(description="Bug, Story, Task, Epic, Sub-task")
    status: str = Field(description="Current status name")
    status_category: str = Field(
        description="Status category: To Do, In Progress, Done"
    )
    priority: str | None = Field(default=None, description="Priority level")
    assignee: str | None = Field(default=None, description="Assignee display name")
    reporter: str = Field(description="Reporter display name")
    labels: list[str] = Field(default_factory=list, description="Issue labels")
    components: list[str] = Field(default_factory=list, description="Component names")

    # Temporal fields
    created_at: datetime = Field(description="Issue creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")
    resolved_at: datetime | None = Field(
        default=None, description="Resolution timestamp"
    )

    # Relationships
    parent_key: str | None = Field(default=None, description="Parent issue key (Epic)")
    linked_issues: list[str] = Field(
        default_factory=list, description="Related issue keys"
    )

    # Sync metadata
    content_hash: str = Field(description="Hash for change detection")
    embedding_version: str = Field(
        default="1", description="Embedding model version"
    )
    indexed_at: datetime = Field(
        default_factory=datetime.utcnow, description="When indexed"
    )


class JiraCommentEmbedding(LanceModel):
    """Schema for Jira comment embeddings.

    Comments are stored separately to allow targeted search and to keep
    issue embeddings focused on core content.
    """

    # Identity
    comment_id: str = Field(description="Comment ID")
    issue_key: str = Field(description="Parent issue key")

    # Vector embedding
    vector: Vector(1536)  # type: ignore[valid-type]

    # Content
    body_preview: str = Field(description="First 300 chars of comment")
    author: str = Field(description="Comment author display name")
    created_at: datetime = Field(description="Comment creation timestamp")

    # Denormalized from parent issue (for efficient filtering)
    project_key: str = Field(description="Project key from parent issue")
    issue_type: str = Field(description="Issue type from parent")
    issue_status: str = Field(description="Issue status from parent")

    # Sync metadata
    content_hash: str = Field(description="Hash for change detection")
    indexed_at: datetime = Field(
        default_factory=datetime.utcnow, description="When indexed"
    )


def compute_content_hash(
    summary: str,
    description: str | None,
    labels: list[str],
    status: str,
) -> str:
    """Compute a hash of issue content for change detection.

    Only fields that affect the semantic meaning are included.
    """
    content = f"{summary}|{description or ''}|{','.join(sorted(labels))}|{status}"
    return hashlib.md5(content.encode()).hexdigest()


def clean_jira_markup(text: str) -> str:
    """Remove Jira/ADF markup, keeping semantic content.

    Args:
        text: Raw Jira markup text

    Returns:
        Cleaned text suitable for embedding
    """
    if not text:
        return ""

    # Remove code blocks (keep marker)
    text = re.sub(
        r"\{code[^}]*\}.*?\{code\}", "[code snippet]", text, flags=re.DOTALL
    )

    # Remove panels but keep content
    text = re.sub(r"\{panel[^}]*\}(.*?)\{panel\}", r"\1", text, flags=re.DOTALL)

    # Remove noformat blocks but keep content
    text = re.sub(r"\{noformat\}(.*?)\{noformat\}", r"\1", text, flags=re.DOTALL)

    # Remove images and attachments
    text = re.sub(r"![\w.-]+\|?[^!]*!", "", text)

    # Remove user mentions but keep names
    text = re.sub(r"\[~([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[~accountid:[^\]]+\]", "", text)

    # Remove URLs but keep link text
    text = re.sub(r"\[([^\]|]+)\|[^\]]+\]", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)

    # Remove Jira macros
    text = re.sub(r"\{[a-z]+[^}]*\}", "", text)

    # Clean up markdown-style formatting
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # Bold
    text = re.sub(r"\*([^*]+)\*", r"\1", text)  # Italic
    text = re.sub(r"_([^_]+)_", r"\1", text)  # Underscore italic
    text = re.sub(r"~~([^~]+)~~", r"\1", text)  # Strikethrough

    # Remove bullet points but keep text
    text = re.sub(r"^[\s]*[-*#]+\s*", "", text, flags=re.MULTILINE)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def truncate_at_sentence(text: str, max_chars: int = 500) -> str:
    """Truncate text at a sentence boundary.

    Args:
        text: Text to truncate
        max_chars: Maximum characters to keep

    Returns:
        Truncated text ending at a sentence boundary if possible
    """
    if len(text) <= max_chars:
        return text

    # Find last sentence boundary before max_chars
    truncated = text[:max_chars]

    # Look for sentence endings
    for ending in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
        last_end = truncated.rfind(ending)
        if last_end > max_chars // 2:  # Only use if not too short
            return truncated[: last_end + 1].strip()

    # Fall back to word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        return truncated[:last_space].strip() + "..."

    return truncated.strip() + "..."


def prepare_issue_for_embedding(issue: dict[str, Any]) -> str:
    """Prepare a Jira issue dict for embedding.

    Creates an optimized text representation that captures the semantic
    meaning of the issue for vector embedding.

    Args:
        issue: Jira issue data dictionary

    Returns:
        Text suitable for embedding
    """
    parts = []

    # Summary is highest signal
    summary = issue.get("summary", "")
    parts.append(f"Issue: {summary}")

    # Type and project context
    issue_type = issue.get("issue_type", "")
    project = issue.get("project_key", "")
    if issue_type and project:
        parts.append(f"Type: {issue_type} in {project}")

    # Status
    status = issue.get("status", "")
    if status:
        parts.append(f"Status: {status}")

    # Labels are semantic signals
    labels = issue.get("labels", [])
    if labels:
        parts.append(f"Labels: {', '.join(labels[:10])}")

    # Components indicate domain
    components = issue.get("components", [])
    if components:
        parts.append(f"Components: {', '.join(components[:5])}")

    # Description - cleaned and truncated
    description = issue.get("description", "")
    if description:
        clean_desc = clean_jira_markup(description)
        truncated = truncate_at_sentence(clean_desc, max_chars=1000)
        parts.append(f"Description: {truncated}")

    return "\n".join(parts)


def prepare_comment_for_embedding(
    comment: dict[str, Any],
    issue: dict[str, Any],
) -> str:
    """Prepare a Jira comment for embedding with parent issue context.

    Args:
        comment: Comment data dictionary
        issue: Parent issue data dictionary

    Returns:
        Text suitable for embedding
    """
    issue_key = issue.get("issue_id", "")
    summary = issue.get("summary", "")
    author = comment.get("author", "")
    body = comment.get("body", "")

    clean_body = clean_jira_markup(body)
    truncated = truncate_at_sentence(clean_body, max_chars=500)

    return f"""Comment on {issue_key}: {summary}
Author: {author}
Content: {truncated}""".strip()
