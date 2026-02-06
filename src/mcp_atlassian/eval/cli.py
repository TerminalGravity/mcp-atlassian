"""CLI for running evaluations."""

from __future__ import annotations

import asyncio
import json
import logging
import sys

import click

from mcp_atlassian.eval.dataset import EvaluationDataset
from mcp_atlassian.eval.service import EvaluationService
from mcp_atlassian.eval.store import EvaluationStore

logger = logging.getLogger(__name__)

# Dataset path
DATASET_PATH = "data/eval"


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Jira Knowledge Chat Evaluation CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@cli.command()
@click.option(
    "--sample",
    "-n",
    default=10,
    help="Number of turns to evaluate",
)
@click.option(
    "--fetch-issues/--no-fetch-issues",
    default=False,
    help="Fetch full issue data for faithfulness check",
)
@click.option(
    "--use-deepeval/--no-deepeval",
    default=True,
    help="Use DeepEval metrics (requires install)",
)
@click.option(
    "--use-ragas/--no-ragas",
    default=True,
    help="Use RAGAS metrics (requires install)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file for results (JSON)",
)
def run(
    sample: int,
    fetch_issues: bool,
    use_deepeval: bool,
    use_ragas: bool,
    output: str | None,
) -> None:
    """Run batch evaluation on unevaluated chat turns.

    Example:
        uv run python -m mcp_atlassian.eval.cli run --sample 10
    """
    click.echo(f"Running evaluation on {sample} turns...")

    service = EvaluationService(
        use_deepeval=use_deepeval,
        use_ragas=use_ragas,
    )

    # Run async evaluation
    result = asyncio.run(
        service.run_batch(
            sample_size=sample,
            fetch_issue_data=fetch_issues,
        )
    )

    # Display results
    click.echo("\n" + "=" * 50)
    click.echo("Evaluation Results")
    click.echo("=" * 50)

    click.echo(f"Run ID: {result.get('run_id', 'N/A')}")
    click.echo(f"Evaluated: {result.get('evaluated', 0)} turns")
    click.echo(f"Errors: {result.get('errors', 0)}")

    if result.get("average_scores"):
        click.echo("\nAverage Scores:")
        scores = result["average_scores"]
        for metric, value in scores.items():
            if value is not None:
                click.echo(f"  {metric}: {value:.3f}")
            else:
                click.echo(f"  {metric}: N/A")

    # Save to file if requested
    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        click.echo(f"\nResults saved to: {output}")


@cli.command()
@click.option(
    "--days",
    "-d",
    default=30,
    help="Number of days to include in summary",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file for results (JSON)",
)
def summary(days: int, output: str | None) -> None:
    """Show metrics summary from evaluated turns.

    Example:
        uv run python -m mcp_atlassian.eval.cli summary --days 7
    """
    click.echo(f"Fetching metrics summary for last {days} days...")

    service = EvaluationService()
    result = service.get_metrics_summary(days)

    click.echo("\n" + "=" * 50)
    click.echo("Metrics Summary")
    click.echo("=" * 50)

    click.echo(f"Total evaluations: {result.get('total_evaluations', 0)}")
    click.echo(f"With scores: {result.get('evaluations_with_scores', 0)}")

    if result.get("average_scores"):
        click.echo("\nAverage Scores:")
        scores = result["average_scores"]
        for metric, value in scores.items():
            if value is not None:
                click.echo(f"  {metric}: {value:.3f}")
            else:
                click.echo(f"  {metric}: N/A")

    if output:
        with open(output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        click.echo(f"\nResults saved to: {output}")


@cli.command()
@click.option(
    "--limit",
    "-n",
    default=20,
    help="Number of turns to show",
)
def pending(limit: int) -> None:
    """Show pending (unevaluated) turns.

    Example:
        uv run python -m mcp_atlassian.eval.cli pending --limit 10
    """
    store = EvaluationStore()
    docs = store.get_unevaluated(limit=limit)

    click.echo(f"Found {len(docs)} unevaluated turns:\n")

    for doc in docs:
        click.echo(f"ID: {doc.get('id', 'N/A')}")
        click.echo(f"  Query: {doc.get('query', 'N/A')[:60]}...")
        click.echo(f"  Timestamp: {doc.get('timestamp', 'N/A')}")
        click.echo(f"  Tool calls: {len(doc.get('tool_calls', []))}")
        click.echo(f"  Issues retrieved: {len(doc.get('retrieved_issues', []))}")
        click.echo()


@cli.command()
@click.argument("run_id")
def status(run_id: str) -> None:
    """Check status of an evaluation run.

    Example:
        uv run python -m mcp_atlassian.eval.cli status <run-id>
    """
    store = EvaluationStore()
    run = store.get_run(run_id)

    if not run:
        click.echo(f"Run {run_id} not found")
        sys.exit(1)

    click.echo(f"Run ID: {run.run_id}")
    click.echo(f"Status: {run.status}")
    click.echo(f"Started: {run.started_at}")
    click.echo(f"Completed: {run.completed_at or 'N/A'}")
    click.echo(f"Progress: {run.completed_evaluations}/{run.total_evaluations}")

    if run.average_scores:
        click.echo("\nAverage Scores:")
        for metric, value in run.average_scores.model_dump().items():
            if value is not None:
                click.echo(f"  {metric}: {value:.3f}")

    if run.errors:
        click.echo(f"\nErrors ({len(run.errors)}):")
        for err in run.errors[:5]:
            click.echo(f"  - {err}")


@cli.command()
def seed() -> None:
    """Seed MongoDB with sample evaluation data for testing.

    Example:
        uv run python -m mcp_atlassian.eval.cli seed
    """
    dataset = EvaluationDataset()
    count = dataset.seed_sample_data()
    click.echo(f"Seeded {count} sample evaluation documents")
    click.echo(f"\nDataset path: {dataset.dataset_path}")


@cli.command("export")
@click.option(
    "--limit",
    "-n",
    default=100,
    help="Maximum documents to export",
)
@click.option(
    "--output",
    "-o",
    default="exported_evaluations.json",
    help="Output filename",
)
def export_data(limit: int, output: str) -> None:
    """Export evaluation data from MongoDB to JSON file.

    Example:
        uv run python -m mcp_atlassian.eval.cli export --limit 50
    """
    dataset = EvaluationDataset()
    filepath = dataset.export_from_mongodb(limit=limit, filename=output)
    click.echo(f"Exported to: {filepath}")


@cli.command("import")
@click.option(
    "--input",
    "-i",
    "input_file",
    default="exported_evaluations.json",
    help="Input filename",
)
def import_data(input_file: str) -> None:
    """Import evaluation data from JSON file to MongoDB.

    Example:
        uv run python -m mcp_atlassian.eval.cli import --input data.json
    """
    dataset = EvaluationDataset()
    try:
        count = dataset.import_to_mongodb(filename=input_file)
        click.echo(f"Imported {count} documents")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("init-ground-truth")
def init_ground_truth() -> None:
    """Create a template ground truth file for manual annotation.

    Example:
        uv run python -m mcp_atlassian.eval.cli init-ground-truth
    """
    dataset = EvaluationDataset()
    filepath = dataset.create_ground_truth_template()
    click.echo(f"Created ground truth template: {filepath}")
    click.echo("\nEdit this file to add your test cases, then use:")
    click.echo("  uv run python -m mcp_atlassian.eval.cli run --ground-truth")


def main() -> None:
    """Entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
