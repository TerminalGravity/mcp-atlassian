"""Self-querying parser for natural language to structured filters.

Uses LLM to extract filters and semantic search terms from natural language queries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Query cache with TTL
_query_cache: dict[str, tuple[Any, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes
_CACHE_MAX_SIZE = 1000

# Jira field schema for self-querying
JIRA_FIELD_SCHEMA = {
    "project_key": {
        "description": "Jira project key (e.g., 'PROJ', 'ENG', 'PLATFORM')",
        "type": "string",
        "operators": ["$eq", "$in"],
    },
    "issue_type": {
        "description": "Type of issue: Bug, Story, Task, Epic, Sub-task",
        "type": "string",
        "operators": ["$eq", "$in"],
        "enum": ["Bug", "Story", "Task", "Epic", "Sub-task"],
    },
    "status": {
        "description": "Issue status (e.g., 'Open', 'In Progress', 'Done')",
        "type": "string",
        "operators": ["$eq", "$in", "$ne"],
    },
    "status_category": {
        "description": "Status category: 'To Do', 'In Progress', 'Done'",
        "type": "string",
        "operators": ["$eq", "$ne"],
        "enum": ["To Do", "In Progress", "Done"],
    },
    "priority": {
        "description": "Issue priority (e.g., 'Critical', 'High', 'Medium', 'Low')",
        "type": "string",
        "operators": ["$eq", "$in"],
        "enum": ["Critical", "High", "Medium", "Low", "Lowest"],
    },
    "assignee": {
        "description": "Person assigned to the issue (username or display name)",
        "type": "string",
        "operators": ["$eq", "$in"],
    },
    "reporter": {
        "description": "Person who created the issue",
        "type": "string",
        "operators": ["$eq"],
    },
    "labels": {
        "description": "Labels attached to the issue",
        "type": "list[string]",
        "operators": ["$contains"],
    },
    "components": {
        "description": "Components the issue belongs to",
        "type": "list[string]",
        "operators": ["$contains"],
    },
    "created_at": {
        "description": "When the issue was created",
        "type": "datetime",
        "operators": ["$gte", "$lte", "$gt", "$lt"],
    },
    "updated_at": {
        "description": "When the issue was last updated",
        "type": "datetime",
        "operators": ["$gte", "$lte", "$gt", "$lt"],
    },
}

def _now() -> datetime:
    """Get current UTC datetime."""
    return datetime.utcnow()


def _days_ago(m: re.Match) -> datetime:
    return _now() - timedelta(days=int(m.group(1)))


def _weeks_ago(m: re.Match) -> datetime:
    return _now() - timedelta(weeks=int(m.group(1)))


def _months_ago(m: re.Match) -> datetime:
    return _now() - timedelta(days=int(m.group(1)) * 30)


def _this_week(m: re.Match) -> datetime:
    return _now() - timedelta(days=_now().weekday())


# Date expression patterns
DATE_PATTERNS: dict[str, Any] = {
    r"last\s+(\d+)\s+days?": _days_ago,
    r"last\s+(\d+)\s+weeks?": _weeks_ago,
    r"last\s+(\d+)\s+months?": _months_ago,
    r"last\s+week": lambda m: _now() - timedelta(weeks=1),
    r"last\s+month": lambda m: _now() - timedelta(days=30),
    r"this\s+week": _this_week,
    r"this\s+month": lambda m: _now().replace(day=1),
    r"yesterday": lambda m: _now() - timedelta(days=1),
    r"today": lambda m: _now().replace(hour=0, minute=0, second=0),
    r"q1\s*(\d{4})?": lambda m: _quarter_start(1, m.group(1)),
    r"q2\s*(\d{4})?": lambda m: _quarter_start(2, m.group(1)),
    r"q3\s*(\d{4})?": lambda m: _quarter_start(3, m.group(1)),
    r"q4\s*(\d{4})?": lambda m: _quarter_start(4, m.group(1)),
}


def _quarter_start(quarter: int, year_str: str | None) -> datetime:
    """Get the start date of a quarter."""
    year = int(year_str) if year_str else datetime.utcnow().year
    month = (quarter - 1) * 3 + 1
    return datetime(year, month, 1)


def parse_date_expression(expr: str) -> datetime | None:
    """Parse natural language date expressions."""
    expr_lower = expr.lower().strip()
    for pattern, handler in DATE_PATTERNS.items():
        match = re.search(pattern, expr_lower)
        if match:
            return handler(match)
    return None


@dataclass
class ParsedQuery:
    """Result of parsing a natural language query."""

    semantic_query: str
    """The semantic search portion of the query."""

    filters: dict[str, Any] = dataclass_field(default_factory=dict)
    """Structured filters to apply."""

    interpretation: str = ""
    """Human-readable interpretation of what was parsed."""

    confidence: float = 1.0
    """Confidence score (0-1) in the parsing."""

    raw_query: str = ""
    """Original query before parsing."""


SELF_QUERY_SYSTEM_PROMPT = """\
You are a query parser for a Jira issue search system. Extract structured \
filters and semantic search terms from natural language queries.

## Available Fields for Filtering

{schema}

## Instructions

1. Extract any explicit filters mentioned in the query
2. Identify the semantic search portion (what to search for by meaning)
3. Return a JSON object with:
   - "semantic_query": string - the part to search semantically (empty if filter-only)
   - "filters": object - structured filters using field names and operators
   - "interpretation": string - brief explanation of how you interpreted the query

## Filter Format

Use this format for filters:
- Simple equality: {{"field": "value"}}
- Operators: {{"field": {{"$op": "value"}}}}
- Multiple values: {{"field": {{"$in": ["val1", "val2"]}}}}
- Date comparisons: {{"created_at": {{"$gte": "2024-01-01"}}}}

## Date Handling

For relative dates like "last week", "last month", "last 30 days", use the marker:
- {{"created_at": {{"$gte": "RELATIVE:last month"}}}}

The system will resolve these to actual dates.

## Examples

Query: "auth bugs from last month"
Response:
{{
  "semantic_query": "auth authentication",
  "filters": {{
    "issue_type": "Bug",
    "created_at": {{"$gte": "RELATIVE:last month"}}
  }},
  "interpretation": "Auth bugs created in the last 30 days"
}}

Query: "open stories in PLATFORM project"
Response:
{{
  "semantic_query": "",
  "filters": {{
    "issue_type": "Story",
    "status_category": {{"$ne": "Done"}},
    "project_key": "PLATFORM"
  }},
  "interpretation": "All non-completed stories in the PLATFORM project"
}}

Query: "issues assigned to john about API performance"
Response:
{{
  "semantic_query": "API performance",
  "filters": {{
    "assignee": "john"
  }},
  "interpretation": "Issues assigned to john related to API performance"
}}

Query: "high priority bugs in backlog"
Response:
{{
  "semantic_query": "backlog",
  "filters": {{
    "issue_type": "Bug",
    "priority": "High",
    "status_category": "To Do"
  }},
  "interpretation": "High priority bugs that are in To Do status (backlog)"
}}

## Important Rules

1. Be conservative - only add filters when explicitly mentioned or clearly implied
2. If something is ambiguous, put it in semantic_query instead of filters
3. Project keys are usually UPPERCASE (e.g., PROJ, ENG, PLATFORM)
4. Common synonyms: "bugs" = Bug, "stories" = Story, "tasks" = Task
5. "open" usually means status_category != "Done"
6. "closed" or "done" means status_category = "Done"
7. "in progress" means status_category = "In Progress"

Return ONLY valid JSON, no markdown or explanation outside the JSON."""


def _format_schema_for_prompt() -> str:
    """Format the field schema for the system prompt."""
    lines = []
    for field_name, info in JIRA_FIELD_SCHEMA.items():
        desc = info["description"]
        ops = ", ".join(info["operators"])
        if "enum" in info:
            enum_vals = ", ".join(info["enum"])
            lines.append(
                f"- {field_name}: {desc}. Ops: {ops}. Values: {enum_vals}"
            )
        else:
            lines.append(f"- {field_name}: {desc}. Ops: {ops}")
    return "\n".join(lines)


class SelfQueryParser:
    """Parser that uses LLM to extract filters from natural language queries.

    Includes query caching to reduce LLM latency for repeated queries.
    """

    def __init__(self, model: str = "gpt-4o-mini", use_cache: bool = True) -> None:
        """Initialize the parser.

        Args:
            model: OpenAI model to use for parsing.
            use_cache: Whether to cache parsed queries.
        """
        self.model = model
        self.use_cache = use_cache
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Get or create OpenAI client."""
        if self._client is None:
            self._client = AsyncOpenAI()
        return self._client

    def _get_cache_key(self, query: str) -> str:
        """Generate cache key for a query."""
        # Normalize query for caching (lowercase, strip whitespace)
        normalized = query.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> ParsedQuery | None:
        """Get cached parsed query if valid."""
        global _query_cache
        if cache_key in _query_cache:
            parsed, timestamp = _query_cache[cache_key]
            if time.time() - timestamp < _CACHE_TTL_SECONDS:
                logger.debug(f"Query cache hit for key {cache_key[:8]}")
                return parsed
            else:
                # Expired, remove from cache
                del _query_cache[cache_key]
        return None

    def _set_cached(self, cache_key: str, parsed: ParsedQuery) -> None:
        """Cache a parsed query."""
        global _query_cache
        # Evict old entries if cache is full
        if len(_query_cache) >= _CACHE_MAX_SIZE:
            # Remove oldest 10%
            sorted_keys = sorted(
                _query_cache.keys(),
                key=lambda k: _query_cache[k][1]
            )
            for key in sorted_keys[: _CACHE_MAX_SIZE // 10]:
                del _query_cache[key]

        _query_cache[cache_key] = (parsed, time.time())

    async def parse(self, query: str) -> ParsedQuery:
        """Parse a natural language query into structured filters.

        Uses caching to avoid redundant LLM calls for repeated queries.

        Args:
            query: Natural language query to parse.

        Returns:
            ParsedQuery with semantic query and filters.
        """
        if not query.strip():
            return ParsedQuery(
                semantic_query="",
                filters={},
                interpretation="Empty query",
                confidence=0.0,
                raw_query=query,
            )

        # Check cache first
        cache_key = self._get_cache_key(query)
        if self.use_cache:
            cached = self._get_cached(cache_key)
            if cached is not None:
                # Return a copy with the original raw_query
                return ParsedQuery(
                    semantic_query=cached.semantic_query,
                    filters=cached.filters.copy(),
                    interpretation=cached.interpretation,
                    confidence=cached.confidence,
                    raw_query=query,
                )

        try:
            # Call LLM to parse the query
            schema_text = _format_schema_for_prompt()
            system_prompt = SELF_QUERY_SYSTEM_PROMPT.format(schema=schema_text)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=500,
            )

            content = response.choices[0].message.content or "{}"

            # Parse JSON response
            parsed = self._parse_llm_response(content, query)

            # Resolve relative dates
            parsed.filters = self._resolve_relative_dates(parsed.filters)

            # Cache the result (before date resolution for reusability)
            if self.use_cache:
                self._set_cached(cache_key, parsed)

            return parsed

        except Exception as e:
            logger.warning(f"Failed to parse query '{query}': {e}")
            # Fallback: treat entire query as semantic search
            return ParsedQuery(
                semantic_query=query,
                filters={},
                interpretation="Fallback: treating entire query as semantic search",
                confidence=0.5,
                raw_query=query,
            )

    def _parse_llm_response(self, content: str, original_query: str) -> ParsedQuery:
        """Parse the LLM response JSON."""
        try:
            # Clean up potential markdown formatting
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```json?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)

            data = json.loads(content)

            return ParsedQuery(
                semantic_query=data.get("semantic_query", ""),
                filters=data.get("filters", {}),
                interpretation=data.get("interpretation", ""),
                confidence=0.9,
                raw_query=original_query,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            return ParsedQuery(
                semantic_query=original_query,
                filters={},
                interpretation="Failed to parse LLM response",
                confidence=0.3,
                raw_query=original_query,
            )

    def _resolve_relative_dates(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Resolve RELATIVE: date markers to actual datetime values."""
        resolved = {}
        for field, value in filters.items():
            if isinstance(value, dict):
                resolved_value = {}
                for op, operand in value.items():
                    if isinstance(operand, str) and operand.startswith("RELATIVE:"):
                        date_expr = operand[9:]  # Remove "RELATIVE:" prefix
                        resolved_date = parse_date_expression(date_expr)
                        if resolved_date:
                            resolved_value[op] = resolved_date.isoformat()
                        else:
                            # Keep original if we can't parse
                            resolved_value[op] = operand
                    else:
                        resolved_value[op] = operand
                resolved[field] = resolved_value
            else:
                resolved[field] = value
        return resolved

    def translate_to_lancedb_filters(
        self, filters: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate parsed filters to LanceDB filter format.

        Args:
            filters: Parsed filters from the query.

        Returns:
            Filters in LanceDB format.
        """
        translated = {}

        for field, value in filters.items():
            if isinstance(value, dict):
                # Already has operators
                translated[field] = value
            else:
                # Simple equality - keep as is
                translated[field] = value

        return translated
