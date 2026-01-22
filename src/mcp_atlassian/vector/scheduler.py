"""Background sync scheduler for vector store."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from typing import TYPE_CHECKING

from mcp_atlassian.vector.config import VectorConfig
from mcp_atlassian.vector.sync import SyncResult, VectorSyncEngine

if TYPE_CHECKING:
    from mcp_atlassian.jira import JiraFacade

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Background scheduler for periodic vector sync.

    Runs incremental sync at configurable intervals to keep the
    vector index up-to-date with Jira changes.
    """

    def __init__(
        self,
        jira_facade: JiraFacade,
        config: VectorConfig | None = None,
        interval_minutes: int | None = None,
    ) -> None:
        """Initialize the scheduler.

        Args:
            jira_facade: Jira client facade for API access.
            config: Vector configuration.
            interval_minutes: Sync interval in minutes. Defaults to config value.
        """
        self.jira = jira_facade
        self.config = config or VectorConfig.from_env()
        self.interval_minutes = interval_minutes or self.config.sync_interval_minutes
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_sync: datetime | None = None
        self._last_result: SyncResult | None = None
        self._sync_count = 0
        self._error_count = 0

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._running

    @property
    def status(self) -> dict:
        """Get current scheduler status."""
        return {
            "running": self._running,
            "interval_minutes": self.interval_minutes,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "sync_count": self._sync_count,
            "error_count": self._error_count,
            "last_result": {
                "issues_processed": self._last_result.issues_processed,
                "issues_embedded": self._last_result.issues_embedded,
                "issues_skipped": self._last_result.issues_skipped,
                "errors": len(self._last_result.errors),
                "duration_seconds": self._last_result.duration_seconds,
            }
            if self._last_result
            else None,
        }

    async def start(self) -> None:
        """Start the background sync scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Sync scheduler started (interval: {self.interval_minutes} minutes)"
        )

    async def stop(self) -> None:
        """Stop the background sync scheduler."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Sync scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        engine = VectorSyncEngine(self.jira, config=self.config)

        while self._running:
            try:
                logger.info("Starting scheduled incremental sync...")
                result = await engine.incremental_sync()

                self._last_sync = datetime.utcnow()
                self._last_result = result
                self._sync_count += 1

                if result.errors:
                    self._error_count += len(result.errors)
                    logger.warning(
                        f"Sync completed with {len(result.errors)} errors: "
                        f"{result.issues_embedded} issues updated"
                    )
                else:
                    logger.info(
                        f"Sync completed: {result.issues_embedded} issues updated "
                        f"in {result.duration_seconds:.1f}s"
                    )

            except Exception as e:
                self._error_count += 1
                logger.error(f"Sync error: {e}", exc_info=True)

            # Wait for next interval
            if self._running:
                await asyncio.sleep(self.interval_minutes * 60)

    async def run_once(self) -> SyncResult:
        """Run a single sync immediately.

        Returns:
            SyncResult with statistics.
        """
        engine = VectorSyncEngine(self.jira, config=self.config)
        result = await engine.incremental_sync()

        self._last_sync = datetime.utcnow()
        self._last_result = result
        self._sync_count += 1

        if result.errors:
            self._error_count += len(result.errors)

        return result


async def run_daemon(
    jira_facade: JiraFacade,
    config: VectorConfig | None = None,
    interval_minutes: int | None = None,
) -> None:
    """Run the sync scheduler as a daemon.

    This function blocks until interrupted (Ctrl+C).

    Args:
        jira_facade: Jira client facade.
        config: Vector configuration.
        interval_minutes: Sync interval in minutes.
    """
    scheduler = SyncScheduler(
        jira_facade, config=config, interval_minutes=interval_minutes
    )

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await scheduler.start()
        logger.info("Sync daemon running. Press Ctrl+C to stop.")

        # Wait for shutdown signal
        await stop_event.wait()

    finally:
        await scheduler.stop()
        logger.info("Sync daemon stopped")
