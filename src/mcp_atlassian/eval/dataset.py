"""Evaluation dataset management."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp_atlassian.eval.store import EvaluationStore

logger = logging.getLogger(__name__)

# Default dataset location
DEFAULT_DATASET_PATH = Path(__file__).parent.parent.parent.parent / "data" / "eval"


class EvaluationDataset:
    """Manage evaluation datasets for testing and benchmarking."""

    def __init__(
        self,
        store: EvaluationStore | None = None,
        dataset_path: Path | str | None = None,
    ) -> None:
        """Initialize the evaluation dataset manager.

        Args:
            store: Optional evaluation store instance
            dataset_path: Path to dataset files (default: data/eval/)
        """
        self.store = store or EvaluationStore()
        self.dataset_path = Path(dataset_path) if dataset_path else DEFAULT_DATASET_PATH

    def load_ground_truth(self, filename: str = "ground_truth.json") -> list[dict[str, Any]]:
        """Load ground truth dataset from JSON file.

        Ground truth format:
        [
            {
                "query": "How do payments work?",
                "expected_tools": ["semantic_search"],
                "expected_issues": ["DS-1234", "DS-5678"],
                "expected_keywords": ["payment", "gateway", "transaction"],
                "ground_truth_answer": "Payments are processed through..."
            }
        ]

        Args:
            filename: Name of the ground truth file

        Returns:
            List of ground truth entries
        """
        filepath = self.dataset_path / filename
        if not filepath.exists():
            logger.warning(f"Ground truth file not found: {filepath}")
            return []

        with open(filepath) as f:
            data = json.load(f)

        logger.info(f"Loaded {len(data)} ground truth entries from {filepath}")
        return data

    def save_ground_truth(
        self,
        entries: list[dict[str, Any]],
        filename: str = "ground_truth.json",
    ) -> Path:
        """Save ground truth dataset to JSON file.

        Args:
            entries: List of ground truth entries
            filename: Name of the output file

        Returns:
            Path to the saved file
        """
        self.dataset_path.mkdir(parents=True, exist_ok=True)
        filepath = self.dataset_path / filename

        with open(filepath, "w") as f:
            json.dump(entries, f, indent=2)

        logger.info(f"Saved {len(entries)} ground truth entries to {filepath}")
        return filepath

    def seed_sample_data(self) -> int:
        """Seed MongoDB with sample evaluation data for testing.

        Returns:
            Number of documents seeded
        """
        sample_data = [
            {
                "conversation_id": "sample-conv-001",
                "turn_index": 1,
                "query": "How do we handle payment failures?",
                "tool_calls": [
                    {
                        "tool_name": "semantic_search",
                        "input": {"query": "payment failures handling"},
                        "output": {"issues": ["DS-1234", "DS-5678"], "count": 2},
                        "latency_ms": 150,
                    }
                ],
                "retrieved_issues": ["DS-1234", "DS-5678"],
                "response_text": "Payment failures are handled through a retry mechanism "
                "implemented in DS-1234. The system attempts up to 3 retries with "
                "exponential backoff. Failed transactions are logged in DS-5678 for "
                "manual review.",
                "citations": [
                    {"index": 1, "issue_id": "DS-1234"},
                    {"index": 2, "issue_id": "DS-5678"},
                ],
                "model_id": "gpt-4.1",
                "output_mode_id": None,
            },
            {
                "conversation_id": "sample-conv-002",
                "turn_index": 1,
                "query": "What is the status of the API refactoring project?",
                "tool_calls": [
                    {
                        "tool_name": "jql_search",
                        "input": {"jql": "project = DS AND labels = api-refactor"},
                        "output": {"issues": ["DS-2001", "DS-2002", "DS-2003"], "count": 3},
                        "latency_ms": 200,
                    },
                    {
                        "tool_name": "semantic_search",
                        "input": {"query": "API refactoring status"},
                        "output": {"issues": ["DS-2001"], "count": 1},
                        "latency_ms": 120,
                    },
                ],
                "retrieved_issues": ["DS-2001", "DS-2002", "DS-2003"],
                "response_text": "The API refactoring project is currently in progress. "
                "DS-2001 (Epic) tracks the overall effort. DS-2002 handles the "
                "authentication changes and is 80% complete. DS-2003 covers "
                "endpoint standardization and is pending review.",
                "citations": [
                    {"index": 1, "issue_id": "DS-2001"},
                    {"index": 2, "issue_id": "DS-2002"},
                    {"index": 3, "issue_id": "DS-2003"},
                ],
                "model_id": "gpt-4.1",
                "output_mode_id": None,
            },
            {
                "conversation_id": "sample-conv-003",
                "turn_index": 1,
                "query": "Show me open bugs assigned to me",
                "tool_calls": [
                    {
                        "tool_name": "jql_search",
                        "input": {
                            "jql": "project = DS AND issuetype = Bug AND "
                            "assignee = currentUser() AND resolution = Unresolved"
                        },
                        "output": {"issues": ["DS-3001", "DS-3002"], "count": 2},
                        "latency_ms": 180,
                    }
                ],
                "retrieved_issues": ["DS-3001", "DS-3002"],
                "response_text": "You have 2 open bugs assigned:\n\n"
                "1. **DS-3001** - Login timeout on mobile devices (High priority)\n"
                "2. **DS-3002** - Dashboard chart not rendering (Medium priority)",
                "citations": [
                    {"index": 1, "issue_id": "DS-3001"},
                    {"index": 2, "issue_id": "DS-3002"},
                ],
                "model_id": "gpt-4.1",
                "output_mode_id": None,
            },
        ]

        count = 0
        for data in sample_data:
            self.store.log_turn(data)
            count += 1

        logger.info(f"Seeded {count} sample evaluation documents")
        return count

    def create_ground_truth_template(self) -> Path:
        """Create a template ground truth file.

        Returns:
            Path to the template file
        """
        template = [
            {
                "query": "Example: How do payments work?",
                "expected_tools": ["semantic_search"],
                "expected_issues": ["DS-1234"],
                "expected_keywords": ["payment", "gateway"],
                "ground_truth_answer": "Payments are processed through the gateway...",
                "notes": "Add your test cases here",
            }
        ]
        return self.save_ground_truth(template, "ground_truth_template.json")

    def export_from_mongodb(
        self,
        limit: int = 100,
        filename: str = "exported_evaluations.json",
    ) -> Path:
        """Export evaluation data from MongoDB to JSON file.

        Args:
            limit: Maximum number of documents to export
            filename: Output filename

        Returns:
            Path to the exported file
        """
        cursor = self.store.collection.find({}, limit=limit).sort("timestamp", -1)

        documents = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if doc.get("timestamp"):
                doc["timestamp"] = doc["timestamp"].isoformat()
            if doc.get("evaluated_at"):
                doc["evaluated_at"] = doc["evaluated_at"].isoformat()
            documents.append(doc)

        self.dataset_path.mkdir(parents=True, exist_ok=True)
        filepath = self.dataset_path / filename

        with open(filepath, "w") as f:
            json.dump(documents, f, indent=2, default=str)

        logger.info(f"Exported {len(documents)} documents to {filepath}")
        return filepath

    def import_to_mongodb(self, filename: str = "exported_evaluations.json") -> int:
        """Import evaluation data from JSON file to MongoDB.

        Args:
            filename: Input filename

        Returns:
            Number of documents imported
        """
        filepath = self.dataset_path / filename
        if not filepath.exists():
            msg = f"Import file not found: {filepath}"
            raise FileNotFoundError(msg)

        with open(filepath) as f:
            documents = json.load(f)

        count = 0
        for doc in documents:
            # Remove MongoDB ID to create new document
            doc.pop("_id", None)
            doc.pop("id", None)
            self.store.log_turn(doc)
            count += 1

        logger.info(f"Imported {count} documents from {filepath}")
        return count
