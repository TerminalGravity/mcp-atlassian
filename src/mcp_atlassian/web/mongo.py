"""MongoDB connection helper for output modes storage."""

import os
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

# Global MongoDB client
_client: MongoClient[dict[str, Any]] | None = None
_db: Database[dict[str, Any]] | None = None


def get_mongodb_url() -> str:
    """Get MongoDB URL from environment."""
    return os.getenv("MONGODB_URL", "mongodb://localhost:27017/jira_knowledge")


def get_database() -> Database[dict[str, Any]]:
    """Get MongoDB database instance, creating connection if needed."""
    global _client, _db
    if _db is None:
        url = get_mongodb_url()
        _client = MongoClient(url)
        # Extract database name from URL or use default
        db_name = url.rsplit("/", 1)[-1].split("?")[0] or "jira_knowledge"
        _db = _client[db_name]
    return _db


def close_connection() -> None:
    """Close MongoDB connection."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


def check_connection() -> bool:
    """Check if MongoDB connection is healthy."""
    try:
        db = get_database()
        db.command("ping")
        return True
    except Exception:
        return False
