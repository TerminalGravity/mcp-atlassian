"""Insights and analysis utilities for vector store data.

Provides clustering, trend detection, and pattern analysis over
indexed Jira issues and comments.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClusterResult:
    """Result of clustering analysis."""

    cluster_id: int
    size: int
    representative_issues: list[str]
    common_labels: list[str]
    common_components: list[str]
    theme_keywords: list[str]
    centroid: list[float] = field(default_factory=list)


@dataclass
class TrendAnalysis:
    """Result of temporal trend analysis."""

    period_start: datetime
    period_end: datetime
    total_created: int
    total_resolved: int
    net_change: int
    by_type: dict[str, int]
    by_priority: dict[str, int]
    trending_labels: list[tuple[str, int]]


class InsightsEngine:
    """Engine for generating insights from vector store data."""

    def __init__(self, store: Any) -> None:
        """Initialize insights engine.

        Args:
            store: LanceDBStore instance
        """
        self.store = store

    def cluster_issues(
        self,
        project_key: str | None = None,
        n_clusters: int = 5,
        min_cluster_size: int = 3,
    ) -> list[ClusterResult]:
        """Cluster issues by semantic similarity.

        Uses K-means clustering on issue embeddings to identify
        natural groupings/themes in the issues.

        Args:
            project_key: Optional project filter
            n_clusters: Target number of clusters
            min_cluster_size: Minimum issues per cluster

        Returns:
            List of ClusterResult objects
        """
        try:
            # Get all issues with vectors
            issues_df = self.store.issues_table.to_pandas()

            if project_key:
                issues_df = issues_df[issues_df["project_key"] == project_key]

            if len(issues_df) < n_clusters * min_cluster_size:
                logger.warning(
                    f"Not enough issues for clustering: {len(issues_df)}"
                )
                return []

            # Extract vectors
            vectors = np.array(issues_df["vector"].tolist())

            # Simple K-means clustering
            clusters = self._kmeans_cluster(vectors, n_clusters)

            # Build cluster results
            results = []
            for cluster_id in range(n_clusters):
                mask = clusters == cluster_id
                cluster_issues = issues_df[mask]

                if len(cluster_issues) < min_cluster_size:
                    continue

                # Get representative issues (closest to centroid)
                centroid = vectors[mask].mean(axis=0)
                distances = np.linalg.norm(vectors[mask] - centroid, axis=1)
                top_indices = np.argsort(distances)[:3]
                representative_keys = (
                    cluster_issues.iloc[top_indices]["issue_id"].tolist()
                )

                # Find common labels
                all_labels: list[str] = []
                for labels in cluster_issues["labels"]:
                    if isinstance(labels, list):
                        all_labels.extend(labels)
                label_counts = Counter(all_labels)
                common_labels = [lbl for lbl, _ in label_counts.most_common(5)]

                # Find common components
                all_components: list[str] = []
                for components in cluster_issues["components"]:
                    if isinstance(components, list):
                        all_components.extend(components)
                component_counts = Counter(all_components)
                common_components = [c for c, _ in component_counts.most_common(5)]

                # Extract theme keywords from summaries
                theme_keywords = self._extract_keywords(
                    cluster_issues["summary"].tolist()
                )

                results.append(
                    ClusterResult(
                        cluster_id=cluster_id,
                        size=len(cluster_issues),
                        representative_issues=representative_keys,
                        common_labels=common_labels,
                        common_components=common_components,
                        theme_keywords=theme_keywords,
                        centroid=centroid.tolist(),
                    )
                )

            # Sort by size descending
            results.sort(key=lambda x: x.size, reverse=True)
            return results

        except Exception as e:
            logger.error(f"Clustering error: {e}", exc_info=True)
            return []

    def _kmeans_cluster(
        self,
        vectors: np.ndarray,
        n_clusters: int,
        max_iterations: int = 100,
    ) -> np.ndarray:
        """Simple K-means clustering implementation.

        Args:
            vectors: Array of vectors to cluster
            n_clusters: Number of clusters
            max_iterations: Maximum iterations

        Returns:
            Array of cluster assignments
        """
        n_samples = len(vectors)

        # Initialize centroids randomly
        rng = np.random.default_rng(42)
        centroid_indices = rng.choice(n_samples, n_clusters, replace=False)
        centroids = vectors[centroid_indices].copy()

        for _ in range(max_iterations):
            # Assign points to nearest centroid
            distances = np.linalg.norm(
                vectors[:, np.newaxis] - centroids, axis=2
            )
            clusters = np.argmin(distances, axis=1)

            # Update centroids
            new_centroids = np.zeros_like(centroids)
            for k in range(n_clusters):
                mask = clusters == k
                if mask.sum() > 0:
                    new_centroids[k] = vectors[mask].mean(axis=0)
                else:
                    new_centroids[k] = centroids[k]

            # Check convergence
            if np.allclose(centroids, new_centroids):
                break
            centroids = new_centroids

        return clusters

    def _extract_keywords(
        self,
        texts: list[str],
        top_k: int = 5,
    ) -> list[str]:
        """Extract common keywords from texts.

        Simple frequency-based keyword extraction.

        Args:
            texts: List of texts to analyze
            top_k: Number of keywords to return

        Returns:
            List of common keywords
        """
        # Common stopwords to filter
        stopwords = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "as", "is", "was", "are",
            "be", "been", "being", "have", "has", "had", "do", "does",
            "did", "will", "would", "could", "should", "may", "might",
            "must", "shall", "can", "need", "not", "this", "that", "these",
            "those", "it", "its", "we", "they", "them", "their", "our",
            "your", "my", "all", "any", "some", "no", "when", "where",
            "how", "what", "which", "who", "why", "if", "then", "than",
            "so", "just", "only", "also", "very", "too", "more", "most",
            "other", "into", "over", "after", "before", "between",
        }

        # Tokenize and count
        word_counts: Counter[str] = Counter()
        for text in texts:
            words = text.lower().split()
            for word in words:
                # Clean word
                word = "".join(c for c in word if c.isalnum())
                if len(word) > 2 and word not in stopwords:
                    word_counts[word] += 1

        return [word for word, _ in word_counts.most_common(top_k)]

    def analyze_trends(
        self,
        project_key: str | None = None,
        days: int = 30,
        period_days: int = 7,
    ) -> list[TrendAnalysis]:
        """Analyze issue trends over time.

        Groups issues by time period and calculates metrics.

        Args:
            project_key: Optional project filter
            days: Total days to analyze
            period_days: Days per period for grouping

        Returns:
            List of TrendAnalysis for each period
        """
        try:
            issues_df = self.store.issues_table.to_pandas()

            if project_key:
                issues_df = issues_df[issues_df["project_key"] == project_key]

            if len(issues_df) == 0:
                return []

            now = datetime.utcnow()
            start_date = now - timedelta(days=days)

            results = []
            current_start = start_date

            while current_start < now:
                current_end = min(current_start + timedelta(days=period_days), now)

                # Filter issues created in this period
                period_created = issues_df[
                    (issues_df["created_at"] >= current_start)
                    & (issues_df["created_at"] < current_end)
                ]

                # Filter issues resolved in this period
                period_resolved = issues_df[
                    (issues_df["resolved_at"].notna())
                    & (issues_df["resolved_at"] >= current_start)
                    & (issues_df["resolved_at"] < current_end)
                ]

                # Count by type
                by_type = period_created["issue_type"].value_counts().to_dict()

                # Count by priority
                by_priority = period_created["priority"].value_counts().to_dict()

                # Trending labels
                all_labels: list[str] = []
                for labels in period_created["labels"]:
                    if isinstance(labels, list):
                        all_labels.extend(labels)
                label_counts = Counter(all_labels)
                trending_labels = label_counts.most_common(5)

                results.append(
                    TrendAnalysis(
                        period_start=current_start,
                        period_end=current_end,
                        total_created=len(period_created),
                        total_resolved=len(period_resolved),
                        net_change=len(period_created) - len(period_resolved),
                        by_type=by_type,
                        by_priority=by_priority,
                        trending_labels=trending_labels,
                    )
                )

                current_start = current_end

            return results

        except Exception as e:
            logger.error(f"Trend analysis error: {e}", exc_info=True)
            return []

    def find_bug_patterns(
        self,
        project_key: str | None = None,
        min_similarity: float = 0.8,
    ) -> list[dict[str, Any]]:
        """Find recurring bug patterns based on similarity.

        Groups similar bugs to identify patterns that might
        indicate systemic issues.

        Args:
            project_key: Optional project filter
            min_similarity: Minimum similarity threshold

        Returns:
            List of bug pattern groups
        """
        try:
            issues_df = self.store.issues_table.to_pandas()

            # Filter to bugs only
            bugs_df = issues_df[issues_df["issue_type"] == "Bug"]

            if project_key:
                bugs_df = bugs_df[bugs_df["project_key"] == project_key]

            if len(bugs_df) < 2:
                return []

            vectors = np.array(bugs_df["vector"].tolist())

            # Find similar pairs
            patterns: list[dict[str, Any]] = []
            used_indices: set[int] = set()

            for i in range(len(vectors)):
                if i in used_indices:
                    continue

                # Find similar bugs
                similarities = 1 - np.linalg.norm(vectors - vectors[i], axis=1) / 2
                similar_mask = similarities >= min_similarity
                similar_indices = np.where(similar_mask)[0]

                if len(similar_indices) > 1:
                    group_issues = bugs_df.iloc[similar_indices]
                    used_indices.update(similar_indices.tolist())

                    patterns.append({
                        "pattern_id": len(patterns),
                        "bug_count": len(similar_indices),
                        "bugs": group_issues["issue_id"].tolist()[:5],
                        "common_summary_terms": self._extract_keywords(
                            group_issues["summary"].tolist(), top_k=3
                        ),
                        "statuses": group_issues["status"].value_counts().to_dict(),
                    })

            # Sort by count descending
            patterns.sort(key=lambda x: x["bug_count"], reverse=True)
            return patterns[:10]

        except Exception as e:
            logger.error(f"Bug pattern analysis error: {e}", exc_info=True)
            return []

    def get_velocity_metrics(
        self,
        project_key: str,
        weeks: int = 4,
    ) -> dict[str, Any]:
        """Calculate velocity metrics for a project.

        Args:
            project_key: Project to analyze
            weeks: Number of weeks to analyze

        Returns:
            Dictionary with velocity metrics
        """
        try:
            issues_df = self.store.issues_table.to_pandas()
            project_issues = issues_df[issues_df["project_key"] == project_key]

            if len(project_issues) == 0:
                return {"project_key": project_key, "error": "No issues found"}

            now = datetime.utcnow()
            weekly_metrics = []

            for week in range(weeks):
                week_start = now - timedelta(weeks=week + 1)
                week_end = now - timedelta(weeks=week)

                # Issues created this week
                created = project_issues[
                    (project_issues["created_at"] >= week_start)
                    & (project_issues["created_at"] < week_end)
                ]

                # Issues resolved this week
                resolved = project_issues[
                    (project_issues["resolved_at"].notna())
                    & (project_issues["resolved_at"] >= week_start)
                    & (project_issues["resolved_at"] < week_end)
                ]

                weekly_metrics.append({
                    "week": week + 1,
                    "week_ending": week_end.strftime("%Y-%m-%d"),
                    "created": len(created),
                    "resolved": len(resolved),
                    "net": len(created) - len(resolved),
                })

            # Calculate averages
            avg_created = (
                sum(w["created"] for w in weekly_metrics) / len(weekly_metrics)
            )
            avg_resolved = (
                sum(w["resolved"] for w in weekly_metrics) / len(weekly_metrics)
            )

            return {
                "project_key": project_key,
                "weeks_analyzed": weeks,
                "weekly_metrics": weekly_metrics,
                "averages": {
                    "avg_created_per_week": round(avg_created, 1),
                    "avg_resolved_per_week": round(avg_resolved, 1),
                    "avg_net_change": round(avg_created - avg_resolved, 1),
                },
                "backlog_trend": (
                    "growing" if avg_created > avg_resolved else "shrinking"
                ),
            }

        except Exception as e:
            logger.error(f"Velocity metrics error: {e}", exc_info=True)
            return {"project_key": project_key, "error": str(e)}
