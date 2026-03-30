"""SQLite persistence layer for local spawns."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import aiosqlite

from embient.sessions import get_db_path
from embient.spawns.models import SpawnRecord, SpawnRunRecord

logger = logging.getLogger(__name__)

_CREATE_SPAWNS_TABLE = """
CREATE TABLE IF NOT EXISTS spawns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    spawn_type TEXT NOT NULL DEFAULT 'task',
    status TEXT NOT NULL DEFAULT 'active',
    schedule_type TEXT NOT NULL DEFAULT 'once',
    schedule_at TEXT,
    schedule_interval_minutes INTEGER,
    schedule_cron TEXT,
    schedule_timezone TEXT DEFAULT 'UTC',
    payload TEXT NOT NULL DEFAULT '{}',
    model TEXT,
    signal_id INTEGER,
    max_runs INTEGER DEFAULT 15,
    run_count INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    next_run_at TEXT,
    last_run_at TEXT,
    active_hours_start TEXT,
    active_hours_end TEXT,
    active_hours_timezone TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_SPAWN_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS spawn_runs (
    id TEXT PRIMARY KEY,
    spawn_id TEXT NOT NULL REFERENCES spawns(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT,
    result TEXT,
    duration_ms INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
"""

_CREATE_SPAWN_RUNS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_spawn_runs_spawn_id ON spawn_runs(spawn_id);
"""


def _row_to_spawn(row: aiosqlite.Row) -> SpawnRecord:
    d = dict(row)
    d["payload"] = SpawnRecord.payload_from_json(d.get("payload", "{}"))
    return SpawnRecord(**d)


def _row_to_run(row: aiosqlite.Row) -> SpawnRunRecord:
    return SpawnRunRecord(**dict(row))


class SpawnStore:
    """CRUD operations for local spawn data stored in SQLite."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(get_db_path())

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_CREATE_SPAWNS_TABLE)
            await db.execute(_CREATE_SPAWN_RUNS_TABLE)
            await db.execute(_CREATE_SPAWN_RUNS_INDEX)
            await db.commit()
        logger.debug("Spawn store initialized")

    # =========================================================================
    # Spawn CRUD
    # =========================================================================

    async def create_spawn(self, spawn: SpawnRecord) -> SpawnRecord:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO spawns (
                    id, name, description, spawn_type, status,
                    schedule_type, schedule_at, schedule_interval_minutes,
                    schedule_cron, schedule_timezone, payload, model,
                    signal_id, max_runs, run_count, consecutive_errors,
                    next_run_at, last_run_at, active_hours_start,
                    active_hours_end, active_hours_timezone, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spawn.id,
                    spawn.name,
                    spawn.description,
                    spawn.spawn_type,
                    spawn.status,
                    spawn.schedule_type,
                    spawn.schedule_at,
                    spawn.schedule_interval_minutes,
                    spawn.schedule_cron,
                    spawn.schedule_timezone,
                    spawn.payload_json,
                    spawn.model,
                    spawn.signal_id,
                    spawn.max_runs,
                    spawn.run_count,
                    spawn.consecutive_errors,
                    spawn.next_run_at,
                    spawn.last_run_at,
                    spawn.active_hours_start,
                    spawn.active_hours_end,
                    spawn.active_hours_timezone,
                    spawn.created_at,
                    spawn.updated_at,
                ),
            )
            await db.commit()
        logger.info(f"Created spawn '{spawn.name}' ({spawn.id})")
        return spawn

    async def get_spawn(self, spawn_id: str) -> SpawnRecord | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM spawns WHERE id = ?", (spawn_id,))
            row = await cursor.fetchone()
            return _row_to_spawn(row) if row else None

    async def list_spawns(self, status: str | None = None) -> list[SpawnRecord]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute(
                    "SELECT * FROM spawns WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cursor = await db.execute("SELECT * FROM spawns ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [_row_to_spawn(row) for row in rows]

    async def update_spawn(self, spawn_id: str, **updates: object) -> SpawnRecord | None:
        if not updates:
            return await self.get_spawn(spawn_id)

        updates["updated_at"] = datetime.now(UTC).isoformat()

        # Handle payload specially
        if "payload" in updates and isinstance(updates["payload"], dict):
            updates["payload"] = json.dumps(updates["payload"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = [*list(updates.values()), spawn_id]

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE spawns SET {set_clause} WHERE id = ?",
                values,
            )
            await db.commit()

        return await self.get_spawn(spawn_id)

    async def delete_spawn(self, spawn_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM spawns WHERE id = ?", (spawn_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_due_spawns(self) -> list[SpawnRecord]:
        """Get spawns that are active and due for execution (next_run_at <= now)."""
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM spawns WHERE status = 'active' AND next_run_at IS NOT NULL AND next_run_at <= ?",
                (now,),
            )
            rows = await cursor.fetchall()
            return [_row_to_spawn(row) for row in rows]

    # =========================================================================
    # Run CRUD
    # =========================================================================

    async def create_run(self, run: SpawnRunRecord) -> SpawnRunRecord:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO spawn_runs (id, spawn_id, status, error, result, duration_ms, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.spawn_id,
                    run.status,
                    run.error,
                    run.result,
                    run.duration_ms,
                    run.started_at,
                    run.completed_at,
                ),
            )
            await db.commit()
        return run

    async def update_run(self, run_id: str, **updates: object) -> None:
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = [*list(updates.values()), run_id]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE spawn_runs SET {set_clause} WHERE id = ?", values)
            await db.commit()

    async def get_runs(self, spawn_id: str, limit: int = 10) -> list[SpawnRunRecord]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM spawn_runs WHERE spawn_id = ? ORDER BY started_at DESC LIMIT ?",
                (spawn_id, limit),
            )
            rows = await cursor.fetchall()
            return [_row_to_run(row) for row in rows]

    async def get_latest_run(self, spawn_id: str) -> SpawnRunRecord | None:
        runs = await self.get_runs(spawn_id, limit=1)
        return runs[0] if runs else None

    async def prune_runs(self, spawn_id: str, keep: int = 50) -> int:
        """Delete old runs beyond the keep limit. Returns number deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """DELETE FROM spawn_runs WHERE spawn_id = ? AND id NOT IN (
                    SELECT id FROM spawn_runs WHERE spawn_id = ?
                    ORDER BY started_at DESC LIMIT ?
                )""",
                (spawn_id, spawn_id, keep),
            )
            await db.commit()
            return cursor.rowcount
