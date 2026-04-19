"""Data models for the local spawn system."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class SpawnRecord:
    """A local agent spawn definition."""

    id: str = field(default_factory=_new_id)
    name: str = ""
    description: str | None = None
    spawn_type: str = "task"  # "monitoring" | "task"
    status: str = "active"  # "active" | "paused" | "completed" | "failed" | "cancelled"
    schedule_type: str = "once"  # "once" | "interval" | "cron"
    schedule_at: str | None = None  # ISO timestamp for "once"
    schedule_interval_minutes: int | None = None  # for "interval"
    schedule_cron: str | None = None  # cron expression for "cron"
    schedule_timezone: str = "UTC"
    payload: dict = field(default_factory=dict)  # {"message": "...", "notification": {...}}
    model: str | None = None  # BYOK model override
    signal_id: int | None = None  # for monitoring spawns
    max_runs: int = 15
    run_count: int = 0
    consecutive_errors: int = 0
    next_run_at: str | None = None
    last_run_at: str | None = None
    active_hours_start: str | None = None  # HH:MM
    active_hours_end: str | None = None  # HH:MM
    active_hours_timezone: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @property
    def schedule_display(self) -> str:
        """Human-readable schedule description."""
        if self.schedule_interval_minutes:
            return f"every {self.schedule_interval_minutes}m"
        if self.schedule_cron:
            return f"cron: {self.schedule_cron}"
        return self.schedule_type

    @property
    def payload_json(self) -> str:
        return json.dumps(self.payload)

    @staticmethod
    def payload_from_json(s: str) -> dict:
        try:
            return json.loads(s) if s else {}
        except (json.JSONDecodeError, TypeError):
            return {}


@dataclass
class SpawnRunRecord:
    """A single execution record for a spawn."""

    id: str = field(default_factory=_new_id)
    spawn_id: str = ""
    status: str = "ok"  # "ok" | "error" | "skipped"
    error: str | None = None
    result: str | None = None
    duration_ms: int | None = None
    started_at: str = field(default_factory=_now_iso)
    completed_at: str | None = None
