"""Asyncio-based scheduler for spawn execution.

Polls the SpawnStore every 30 seconds for due spawns and dispatches
them to the SpawnExecutor.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from embient.spawns.executor import SpawnExecutor
    from embient.spawns.store import SpawnStore

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30


class SpawnScheduler:
    """Polls for due spawns and dispatches execution."""

    def __init__(self, store: SpawnStore, executor: SpawnExecutor):
        self._store = store
        self._executor = executor
        self._task: asyncio.Task | None = None
        self._spawn_tasks: set[asyncio.Task] = set()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the scheduler loop as a background asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Spawn scheduler started (poll every %ds)", POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Gracefully stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Spawn scheduler stopped")

    async def _run_loop(self) -> None:
        """Poll for due spawns at regular intervals."""
        while self._running:
            try:
                due_spawns = await self._store.get_due_spawns()
                for spawn in due_spawns:
                    if self._executor.can_accept():
                        # Track the task to avoid GC and satisfy RUF006
                        task = asyncio.create_task(self._executor.execute(spawn))
                        self._spawn_tasks.add(task)
                        task.add_done_callback(self._spawn_tasks.discard)
                    else:
                        logger.debug(
                            "Executor at capacity (%d/%d), deferring spawn %s",
                            self._executor.active_count,
                            self._executor.max_concurrent,
                            spawn.id,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
