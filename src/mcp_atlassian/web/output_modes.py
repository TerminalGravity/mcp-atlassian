"""Output modes API for configurable response formatting."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mcp_atlassian.web.mongo import get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/output-modes", tags=["output-modes"])


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------


class QueryPatterns(BaseModel):
    """Patterns for auto-detecting output mode from query text."""

    keywords: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)
    priority: int = 0


class SystemPromptSections(BaseModel):
    """Sections that compose the system prompt for this output mode."""

    formatting: str
    behavior: str | None = None
    constraints: str | None = None


class OutputModeCreate(BaseModel):
    """Request model for creating an output mode."""

    name: str
    display_name: str
    description: str
    query_patterns: QueryPatterns
    system_prompt_sections: SystemPromptSections
    is_default: bool = False


class OutputModeUpdate(BaseModel):
    """Request model for updating an output mode."""

    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    query_patterns: QueryPatterns | None = None
    system_prompt_sections: SystemPromptSections | None = None
    is_default: bool | None = None


class OutputModeResponse(BaseModel):
    """Response model for an output mode."""

    id: str
    name: str
    display_name: str
    description: str
    owner_id: str | None
    is_default: bool
    query_patterns: QueryPatterns
    system_prompt_sections: SystemPromptSections
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic config."""

        from_attributes = True


class ClassifyQueryRequest(BaseModel):
    """Request to classify a query and determine output mode."""

    query: str


class ClassifyQueryResponse(BaseModel):
    """Response with the matched output mode ID."""

    mode_id: str | None
    mode_name: str | None
    confidence: float
    matched_pattern: str | None


class UserPreferencesResponse(BaseModel):
    """User preferences for output modes."""

    user_id: str
    default_output_mode_id: str | None
    auto_detect_mode: bool


class UserPreferencesUpdate(BaseModel):
    """Request to update user preferences."""

    default_output_mode_id: str | None = None
    auto_detect_mode: bool | None = None


# -----------------------------------------------------------------------------
# Default Templates
# -----------------------------------------------------------------------------

DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "narrative",
        "display_name": "Narrative Summary",
        "description": "Prose paragraphs with inline issue references. Best for explanatory answers.",
        "owner_id": None,
        "is_default": True,
        "query_patterns": {
            "keywords": ["what is", "explain", "describe", "tell me about", "how does"],
            "regex": [r"^what\s+", r"^explain\s+", r"^describe\s+"],
            "priority": 0,
        },
        "system_prompt_sections": {
            "formatting": """Format your response as clear, flowing prose paragraphs.
- Use inline issue references like [DS-1234] when mentioning specific issues
- Structure with logical flow: context -> findings -> implications
- Use markdown headers (##) only for major sections if the answer is long
- Highlight key people, dates, and decisions naturally in the text""",
            "behavior": "Synthesize information across issues to tell a coherent story.",
            "constraints": None,
        },
    },
    {
        "name": "table",
        "display_name": "Table Format",
        "description": "Structured markdown tables grouped by category. Best for comparisons and lists.",
        "owner_id": None,
        "is_default": False,
        "query_patterns": {
            "keywords": ["list", "show all", "compare", "by status", "by type", "breakdown", "show me"],
            "regex": [r"^list\s+", r"^show\s+(all|me)", r"compare\s+", r"by\s+(status|type|priority)"],
            "priority": 1,
        },
        "system_prompt_sections": {
            "formatting": """Format your response using markdown tables.
- Use tables for structured data: | Issue | Summary | Status | Assignee |
- Group related items with headers (## By Status, ## By Type, etc.)
- Include a brief summary sentence before each table
- Sort tables logically (by status priority, date, or alphabetically)""",
            "behavior": "Organize data into clear, scannable tables. Prefer tables over prose for lists.",
            "constraints": "Always include at least Issue ID and Summary columns.",
        },
    },
    {
        "name": "brief",
        "display_name": "Brief Answer",
        "description": "2-3 sentences maximum. Best for quick factual questions.",
        "owner_id": None,
        "is_default": False,
        "query_patterns": {
            "keywords": ["who", "when", "how many", "quick", "briefly", "tldr", "tl;dr"],
            "regex": [r"^who\s+", r"^when\s+", r"^how\s+many", r"^is\s+there"],
            "priority": 2,
        },
        "system_prompt_sections": {
            "formatting": """Keep your response to 2-3 sentences maximum.
- Lead with the direct answer
- Include one supporting detail if relevant
- Reference specific issue keys inline""",
            "behavior": "Be direct and concise. Skip context unless essential.",
            "constraints": "Maximum 50 words. No headers or bullet points.",
        },
    },
    {
        "name": "analysis",
        "display_name": "Deep Analysis",
        "description": "Executive summary followed by detailed breakdown. Best for investigations.",
        "owner_id": None,
        "is_default": False,
        "query_patterns": {
            "keywords": ["analyze", "investigate", "why", "impact", "root cause", "deep dive", "examine"],
            "regex": [r"^why\s+", r"^analyze\s+", r"what.*impact", r"root\s+cause"],
            "priority": 3,
        },
        "system_prompt_sections": {
            "formatting": """Structure your response with:
## Executive Summary
(2-3 sentences capturing the key finding)

## Detailed Analysis
(Thorough breakdown with evidence from issues)

## Related Issues
(Table of connected issues if relevant)

## Recommendations
(If the query warrants it)""",
            "behavior": "Think deeply. Connect dots across issues. Identify patterns and root causes.",
            "constraints": None,
        },
    },
    {
        "name": "status",
        "display_name": "Status Report",
        "description": "Grouped by status with metrics. Best for standups and progress tracking.",
        "owner_id": None,
        "is_default": False,
        "query_patterns": {
            "keywords": ["status", "progress", "standup", "sprint", "update", "where are we"],
            "regex": [r"status\s+of", r"sprint\s+", r"progress\s+on", r"standup"],
            "priority": 4,
        },
        "system_prompt_sections": {
            "formatting": """Format as a status report:

**Summary**: (1 sentence overview with counts)

### In Progress
- [DS-XXX] Summary (Assignee)

### Blocked / Needs Attention
- [DS-XXX] Summary - *Reason*

### Recently Completed
- [DS-XXX] Summary

### Upcoming
- [DS-XXX] Summary""",
            "behavior": "Focus on actionable information. Highlight blockers and risks.",
            "constraints": "Always include issue counts. Flag items needing attention.",
        },
    },
]


# -----------------------------------------------------------------------------
# Database Helpers
# -----------------------------------------------------------------------------


def _doc_to_response(doc: dict[str, Any]) -> OutputModeResponse:
    """Convert MongoDB document to response model."""
    return OutputModeResponse(
        id=str(doc["_id"]),
        name=doc["name"],
        display_name=doc["display_name"],
        description=doc["description"],
        owner_id=doc.get("owner_id"),
        is_default=doc.get("is_default", False),
        query_patterns=QueryPatterns(**doc.get("query_patterns", {})),
        system_prompt_sections=SystemPromptSections(**doc.get("system_prompt_sections", {})),
        created_at=doc.get("created_at", datetime.now(timezone.utc)),
        updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
    )


def seed_default_templates() -> int:
    """Seed default output mode templates if they don't exist."""
    db = get_database()
    collection = db["output_modes"]
    seeded = 0

    for template in DEFAULT_TEMPLATES:
        # Check if template with this name already exists (system template)
        existing = collection.find_one({"name": template["name"], "owner_id": None})
        if not existing:
            now = datetime.now(timezone.utc)
            doc = {
                **template,
                "created_at": now,
                "updated_at": now,
            }
            collection.insert_one(doc)
            seeded += 1
            logger.info(f"Seeded output mode template: {template['name']}")

    return seeded


# -----------------------------------------------------------------------------
# Query Classification
# -----------------------------------------------------------------------------


def classify_query(query: str) -> tuple[str | None, str | None, float, str | None]:
    """
    Classify a query and return the best matching output mode.

    Returns:
        tuple of (mode_id, mode_name, confidence, matched_pattern)
    """
    db = get_database()
    collection = db["output_modes"]

    query_lower = query.lower().strip()
    best_match: dict[str, Any] | None = None
    best_score = 0.0
    matched_pattern: str | None = None

    # Get all output modes (system templates)
    modes = list(collection.find({"owner_id": None}))

    for mode in modes:
        patterns = mode.get("query_patterns", {})
        keywords = patterns.get("keywords", [])
        regex_patterns = patterns.get("regex", [])
        priority = patterns.get("priority", 0)

        mode_score = 0.0
        pattern_matched: str | None = None

        # Check keywords (partial match)
        for keyword in keywords:
            if keyword.lower() in query_lower:
                # Score based on keyword length and position
                keyword_score = len(keyword) / len(query_lower) * 0.5
                if query_lower.startswith(keyword.lower()):
                    keyword_score += 0.3  # Bonus for starting with keyword
                if keyword_score > mode_score:
                    mode_score = keyword_score
                    pattern_matched = f"keyword: {keyword}"

        # Check regex patterns (stronger match)
        for pattern in regex_patterns:
            try:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    regex_score = 0.8  # Regex matches are strong signals
                    if regex_score > mode_score:
                        mode_score = regex_score
                        pattern_matched = f"regex: {pattern}"
            except re.error:
                logger.warning(f"Invalid regex pattern in mode {mode['name']}: {pattern}")

        # Apply priority as a tiebreaker (lower priority = earlier in list = slight preference)
        mode_score += (10 - priority) * 0.01

        if mode_score > best_score:
            best_score = mode_score
            best_match = mode
            matched_pattern = pattern_matched

    if best_match and best_score >= 0.1:  # Minimum threshold
        return (
            str(best_match["_id"]),
            best_match["name"],
            min(best_score, 1.0),
            matched_pattern,
        )

    # Default to narrative if no strong match
    narrative = collection.find_one({"name": "narrative", "owner_id": None})
    if narrative:
        return str(narrative["_id"]), "narrative", 0.5, "default"

    return None, None, 0.0, None


# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------


@router.get("", response_model=list[OutputModeResponse])
async def list_output_modes(owner_id: str | None = None) -> list[OutputModeResponse]:
    """List all output modes (system defaults + user's custom modes)."""
    db = get_database()
    collection = db["output_modes"]

    # Get system templates (owner_id = None) and optionally user's custom modes
    query: dict[str, Any] = {"$or": [{"owner_id": None}]}
    if owner_id:
        query["$or"].append({"owner_id": owner_id})

    modes = list(collection.find(query).sort("name", 1))
    return [_doc_to_response(m) for m in modes]


@router.get("/{mode_id}", response_model=OutputModeResponse)
async def get_output_mode(mode_id: str) -> OutputModeResponse:
    """Get a single output mode by ID."""
    db = get_database()
    collection = db["output_modes"]

    try:
        doc = collection.find_one({"_id": ObjectId(mode_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid mode ID format")

    if not doc:
        raise HTTPException(status_code=404, detail="Output mode not found")

    return _doc_to_response(doc)


@router.post("", response_model=OutputModeResponse)
async def create_output_mode(
    mode: OutputModeCreate,
    owner_id: str | None = None,
) -> OutputModeResponse:
    """Create a new custom output mode."""
    db = get_database()
    collection = db["output_modes"]

    # Check for duplicate name for this owner
    existing = collection.find_one({"name": mode.name, "owner_id": owner_id})
    if existing:
        raise HTTPException(status_code=409, detail=f"Output mode '{mode.name}' already exists")

    now = datetime.now(timezone.utc)
    doc = {
        "name": mode.name,
        "display_name": mode.display_name,
        "description": mode.description,
        "owner_id": owner_id,
        "is_default": mode.is_default,
        "query_patterns": mode.query_patterns.model_dump(),
        "system_prompt_sections": mode.system_prompt_sections.model_dump(),
        "created_at": now,
        "updated_at": now,
    }

    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id

    logger.info(f"Created output mode: {mode.name} (owner: {owner_id})")
    return _doc_to_response(doc)


@router.put("/{mode_id}", response_model=OutputModeResponse)
async def update_output_mode(
    mode_id: str,
    mode: OutputModeUpdate,
    owner_id: str | None = None,
) -> OutputModeResponse:
    """Update an existing output mode (owner only)."""
    db = get_database()
    collection = db["output_modes"]

    try:
        existing = collection.find_one({"_id": ObjectId(mode_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid mode ID format")

    if not existing:
        raise HTTPException(status_code=404, detail="Output mode not found")

    # Only owner can modify (or anyone can modify system templates in dev)
    if existing.get("owner_id") is not None and existing.get("owner_id") != owner_id:
        raise HTTPException(status_code=403, detail="Cannot modify another user's output mode")

    # Build update
    update_data: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if mode.name is not None:
        update_data["name"] = mode.name
    if mode.display_name is not None:
        update_data["display_name"] = mode.display_name
    if mode.description is not None:
        update_data["description"] = mode.description
    if mode.is_default is not None:
        update_data["is_default"] = mode.is_default
    if mode.query_patterns is not None:
        update_data["query_patterns"] = mode.query_patterns.model_dump()
    if mode.system_prompt_sections is not None:
        update_data["system_prompt_sections"] = mode.system_prompt_sections.model_dump()

    collection.update_one({"_id": ObjectId(mode_id)}, {"$set": update_data})

    updated = collection.find_one({"_id": ObjectId(mode_id)})
    logger.info(f"Updated output mode: {mode_id}")
    return _doc_to_response(updated)  # type: ignore[arg-type]


@router.delete("/{mode_id}")
async def delete_output_mode(mode_id: str, owner_id: str | None = None) -> dict[str, bool]:
    """Delete an output mode (owner only, cannot delete system templates)."""
    db = get_database()
    collection = db["output_modes"]

    try:
        existing = collection.find_one({"_id": ObjectId(mode_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid mode ID format")

    if not existing:
        raise HTTPException(status_code=404, detail="Output mode not found")

    # Cannot delete system templates
    if existing.get("owner_id") is None:
        raise HTTPException(status_code=403, detail="Cannot delete system output modes")

    # Only owner can delete
    if existing.get("owner_id") != owner_id:
        raise HTTPException(status_code=403, detail="Cannot delete another user's output mode")

    collection.delete_one({"_id": ObjectId(mode_id)})
    logger.info(f"Deleted output mode: {mode_id}")
    return {"deleted": True}


@router.post("/{mode_id}/clone", response_model=OutputModeResponse)
async def clone_output_mode(mode_id: str, owner_id: str | None = None) -> OutputModeResponse:
    """Clone an existing output mode."""
    db = get_database()
    collection = db["output_modes"]

    try:
        existing = collection.find_one({"_id": ObjectId(mode_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid mode ID format")

    if not existing:
        raise HTTPException(status_code=404, detail="Output mode not found")

    # Create a clone with modified name
    now = datetime.now(timezone.utc)
    clone_name = f"{existing['name']}_copy"
    counter = 1
    while collection.find_one({"name": clone_name, "owner_id": owner_id}):
        clone_name = f"{existing['name']}_copy_{counter}"
        counter += 1

    doc = {
        "name": clone_name,
        "display_name": f"{existing['display_name']} (Copy)",
        "description": existing["description"],
        "owner_id": owner_id,
        "is_default": False,
        "query_patterns": existing["query_patterns"],
        "system_prompt_sections": existing["system_prompt_sections"],
        "created_at": now,
        "updated_at": now,
    }

    result = collection.insert_one(doc)
    doc["_id"] = result.inserted_id

    logger.info(f"Cloned output mode: {existing['name']} -> {clone_name}")
    return _doc_to_response(doc)


@router.post("/classify", response_model=ClassifyQueryResponse)
async def classify_query_endpoint(request: ClassifyQueryRequest) -> ClassifyQueryResponse:
    """Auto-detect the best output mode for a query."""
    mode_id, mode_name, confidence, matched_pattern = classify_query(request.query)
    return ClassifyQueryResponse(
        mode_id=mode_id,
        mode_name=mode_name,
        confidence=confidence,
        matched_pattern=matched_pattern,
    )


# -----------------------------------------------------------------------------
# User Preferences Endpoints
# -----------------------------------------------------------------------------


@router.get("/user-preferences/{user_id}", response_model=UserPreferencesResponse)
async def get_user_preferences(user_id: str) -> UserPreferencesResponse:
    """Get user preferences for output modes."""
    db = get_database()
    collection = db["user_preferences"]

    doc = collection.find_one({"user_id": user_id})
    if not doc:
        # Return defaults
        return UserPreferencesResponse(
            user_id=user_id,
            default_output_mode_id=None,
            auto_detect_mode=True,
        )

    return UserPreferencesResponse(
        user_id=user_id,
        default_output_mode_id=str(doc["default_output_mode_id"]) if doc.get("default_output_mode_id") else None,
        auto_detect_mode=doc.get("auto_detect_mode", True),
    )


@router.put("/user-preferences/{user_id}", response_model=UserPreferencesResponse)
async def update_user_preferences(user_id: str, prefs: UserPreferencesUpdate) -> UserPreferencesResponse:
    """Update user preferences for output modes."""
    db = get_database()
    collection = db["user_preferences"]

    update_data: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if prefs.default_output_mode_id is not None:
        update_data["default_output_mode_id"] = ObjectId(prefs.default_output_mode_id) if prefs.default_output_mode_id else None
    if prefs.auto_detect_mode is not None:
        update_data["auto_detect_mode"] = prefs.auto_detect_mode

    collection.update_one(
        {"user_id": user_id},
        {
            "$set": update_data,
            "$setOnInsert": {"user_id": user_id, "created_at": datetime.now(timezone.utc)},
        },
        upsert=True,
    )

    return await get_user_preferences(user_id)
