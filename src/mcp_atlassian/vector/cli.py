"""CLI commands for vector search operations."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

import click
from dotenv import load_dotenv

from mcp_atlassian.utils.env import is_env_truthy
from mcp_atlassian.utils.logging import setup_logging
from mcp_atlassian.vector.config import VectorConfig

if TYPE_CHECKING:
    from mcp_atlassian.jira import JiraFacade

logger = logging.getLogger(__name__)


def get_jira_facade() -> JiraFacade:
    """Get JiraFacade instance with current configuration."""
    from mcp_atlassian.jira import JiraFacade

    return JiraFacade()


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be used multiple times)",
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to .env file",
)
@click.pass_context
def vector_cli(ctx: click.Context, verbose: int, env_file: str | None) -> None:
    """Vector search operations for MCP Atlassian.

    Sync Jira issues to vector store for semantic search capabilities.
    """
    # Ensure context object exists
    ctx.ensure_object(dict)

    # Set up logging
    if verbose == 1:
        logging_level = logging.INFO
    elif verbose >= 2:
        logging_level = logging.DEBUG
    else:
        if is_env_truthy("MCP_VERY_VERBOSE", "false"):
            logging_level = logging.DEBUG
        elif is_env_truthy("MCP_VERBOSE", "false"):
            logging_level = logging.INFO
        else:
            logging_level = logging.WARNING

    logging_stream = sys.stdout if is_env_truthy("MCP_LOGGING_STDOUT") else sys.stderr
    setup_logging(logging_level, logging_stream)

    # Load environment
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=True)

    ctx.obj["verbose"] = verbose


@vector_cli.command("sync")
@click.option(
    "--full",
    is_flag=True,
    help="Perform full sync (default is incremental)",
)
@click.option(
    "--projects",
    type=str,
    help="Comma-separated project keys to sync (e.g., 'PROJ,ENG')",
)
@click.pass_context
def sync_command(ctx: click.Context, full: bool, projects: str | None) -> None:
    """Sync Jira issues to the vector store.

    By default, performs incremental sync (only changed issues).
    Use --full to sync all issues from scratch.
    """
    from mcp_atlassian.vector.sync import VectorSyncEngine

    click.echo("Starting vector sync...")

    # Parse projects
    project_list = None
    if projects:
        project_list = [p.strip() for p in projects.split(",")]
        click.echo(f"Projects: {', '.join(project_list)}")

    try:
        jira = get_jira_facade()
        config = VectorConfig.from_env()
        engine = VectorSyncEngine(jira, config=config)

        # Run sync
        if full:
            click.echo("Running full sync...")
            result = asyncio.run(engine.full_sync(projects=project_list))
        else:
            click.echo("Running incremental sync...")
            result = asyncio.run(engine.incremental_sync(projects=project_list))

        # Report results
        click.echo("")
        click.echo("Sync completed:")
        click.echo(f"  Issues processed: {result.issues_processed}")
        click.echo(f"  Issues embedded:  {result.issues_embedded}")
        click.echo(f"  Issues skipped:   {result.issues_skipped}")
        click.echo(f"  Duration:         {result.duration_seconds:.1f}s")

        if result.errors:
            click.echo("")
            click.secho(f"Errors ({len(result.errors)}):", fg="yellow")
            for error in result.errors[:5]:
                click.echo(f"  - {error}")
            if len(result.errors) > 5:
                click.echo(f"  ... and {len(result.errors) - 5} more")

    except Exception as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


@vector_cli.command("status")
@click.pass_context
def status_command(ctx: click.Context) -> None:
    """Show vector sync status and statistics."""
    from mcp_atlassian.vector.store import LanceDBStore

    try:
        config = VectorConfig.from_env()
        store = LanceDBStore(config=config)
        stats = store.get_stats()

        click.echo("Vector Store Status")
        click.echo("=" * 40)
        click.echo(f"Database path: {stats['db_path']}")
        click.echo(f"Total issues:  {stats['total_issues']}")
        click.echo(f"Total comments: {stats['total_comments']}")
        click.echo(f"Projects:      {', '.join(stats['projects']) or 'None'}")

        # Load sync state
        state_path = config.db_path / "sync_state.json"
        if state_path.exists():
            import json

            state_data = json.loads(state_path.read_text())
            click.echo("")
            click.echo("Sync State")
            click.echo("-" * 40)
            click.echo(f"Last sync:     {state_data.get('last_sync_at', 'Never')}")
            click.echo(
                f"Last updated:  {state_data.get('last_issue_updated', 'Never')}"
            )
            click.echo(
                f"Projects:      {', '.join(state_data.get('projects_synced', []))}"
            )
        else:
            click.echo("")
            click.echo("No sync state found. Run 'mcp-atlassian-vector sync --full'.")

    except Exception as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


@vector_cli.command("clear")
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_context
def clear_command(ctx: click.Context, yes: bool) -> None:
    """Clear all data from the vector store."""
    import shutil

    config = VectorConfig.from_env()

    if not yes:
        click.confirm(
            f"This will delete all data in {config.db_path}. Continue?",
            abort=True,
        )

    if config.db_path.exists():
        shutil.rmtree(config.db_path)
        click.echo(f"Cleared vector store at {config.db_path}")
    else:
        click.echo("Vector store does not exist.")


@vector_cli.command("compact")
@click.pass_context
def compact_command(ctx: click.Context) -> None:
    """Compact the vector database to optimize storage."""
    from mcp_atlassian.vector.store import LanceDBStore

    try:
        config = VectorConfig.from_env()
        store = LanceDBStore(config=config)

        click.echo("Compacting vector database...")
        store.compact()
        click.echo("Compaction complete.")

    except Exception as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        raise SystemExit(1) from e


def main() -> None:
    """Entry point for vector CLI."""
    vector_cli()


if __name__ == "__main__":
    main()
