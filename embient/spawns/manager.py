"""SpawnManager — top-level orchestrator for the local spawn system.

Ties together SpawnStore, SpawnScheduler, and SpawnExecutor.
Manages lifecycle (start/stop) and provides a high-level API
for spawn CRUD used by the LLM tools and TUI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from embient.spawns.executor import SpawnExecutor
from embient.spawns.models import SpawnRecord, SpawnRunRecord, _new_id, _now_iso
from embient.spawns.schedule import compute_initial_next_run
from embient.spawns.scheduler import SpawnScheduler
from embient.spawns.store import SpawnStore

logger = logging.getLogger(__name__)


class SpawnManager:
    """High-level manager for the local spawn system."""

    def __init__(
        self,
        on_result: Callable[[SpawnRecord, SpawnRunRecord], Any] | None = None,
        db_path: str | None = None,
    ):
        self._store = SpawnStore(db_path=db_path)
        self._executor = SpawnExecutor(self._store, on_result=on_result)
        self._scheduler = SpawnScheduler(self._store, self._executor)
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def active_spawn_count(self) -> int:
        return self._executor.active_count

    async def start(self) -> None:
        """Initialize the store and start the scheduler."""
        if self._started:
            return
        await self._store.initialize()
        await self._scheduler.start()
        self._started = True
        logger.info("SpawnManager started")

    async def stop(self) -> None:
        """Stop the scheduler. Active runs will complete but no new ones start."""
        await self._scheduler.stop()
        self._started = False
        logger.info("SpawnManager stopped")

    # =========================================================================
    # Spawn CRUD (used by LLM tools)
    # =========================================================================

    async def create_spawn(
        self,
        name: str,
        spawn_type: str,
        schedule_type: str,
        payload_message: str,
        *,
        description: str | None = None,
        schedule_at: str | None = None,
        schedule_interval_minutes: int | None = None,
        schedule_cron: str | None = None,
        schedule_timezone: str = "UTC",
        model: str | None = None,
        signal_id: int | None = None,
        max_runs: int = 15,
        active_hours_start: str | None = None,
        active_hours_end: str | None = None,
        active_hours_timezone: str | None = None,
        notification_config: dict | None = None,
    ) -> SpawnRecord:
        """Create a new spawn and register it with the scheduler."""
        payload: dict = {"message": payload_message}
        if notification_config:
            payload["notification"] = notification_config

        spawn = SpawnRecord(
            id=_new_id(),
            name=name,
            description=description,
            spawn_type=spawn_type,
            status="active",
            schedule_type=schedule_type,
            schedule_at=schedule_at,
            schedule_interval_minutes=schedule_interval_minutes,
            schedule_cron=schedule_cron,
            schedule_timezone=schedule_timezone,
            payload=payload,
            model=model,
            signal_id=signal_id,
            max_runs=max_runs,
            active_hours_start=active_hours_start,
            active_hours_end=active_hours_end,
            active_hours_timezone=active_hours_timezone,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )

        # Compute initial next_run_at
        spawn.next_run_at = compute_initial_next_run(spawn)

        await self._store.create_spawn(spawn)
        logger.info(f"Created spawn '{name}' (id={spawn.id}, next_run={spawn.next_run_at})")
        return spawn

    async def list_spawns(self, status: str | None = None) -> list[SpawnRecord]:
        """List spawns, optionally filtered by status."""
        return await self._store.list_spawns(status=status)

    async def get_spawn(self, spawn_id: str) -> SpawnRecord | None:
        """Get a single spawn by ID."""
        return await self._store.get_spawn(spawn_id)

    async def update_spawn(self, spawn_id: str, **updates: Any) -> SpawnRecord | None:
        """Update a spawn's configuration."""
        return await self._store.update_spawn(spawn_id, **updates)

    async def cancel_spawn(self, spawn_id: str) -> bool:
        """Cancel a spawn (sets status to 'cancelled')."""
        spawn = await self._store.get_spawn(spawn_id)
        if not spawn:
            return False
        if spawn.status in ("completed", "cancelled"):
            return False
        await self._store.update_spawn(
            spawn_id,
            status="cancelled",
            next_run_at=None,
        )
        logger.info(f"Cancelled spawn '{spawn.name}' (id={spawn_id})")
        return True

    async def pause_spawn(self, spawn_id: str) -> bool:
        """Pause an active spawn."""
        spawn = await self._store.get_spawn(spawn_id)
        if not spawn or spawn.status != "active":
            return False
        await self._store.update_spawn(spawn_id, status="paused", next_run_at=None)
        logger.info(f"Paused spawn '{spawn.name}'")
        return True

    async def resume_spawn(self, spawn_id: str) -> bool:
        """Resume a paused spawn."""
        spawn = await self._store.get_spawn(spawn_id)
        if not spawn or spawn.status != "paused":
            return False
        # Recompute next_run_at
        next_run = compute_initial_next_run(spawn)
        await self._store.update_spawn(spawn_id, status="active", next_run_at=next_run)
        logger.info(f"Resumed spawn '{spawn.name}' (next_run={next_run})")
        return True

    async def get_spawn_runs(self, spawn_id: str, limit: int = 10) -> list[SpawnRunRecord]:
        """Get run history for a spawn."""
        return await self._store.get_runs(spawn_id, limit=limit)
