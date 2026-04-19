"""Schedule calculation utilities for spawn timing.

Handles next_run_at computation for once/interval/cron schedules,
active hours enforcement, and exponential backoff on errors.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from deepalpha.spawns.models import SpawnRecord

logger = logging.getLogger(__name__)

# Exponential backoff delays in minutes for consecutive errors
_BACKOFF_MINUTES = [0.5, 1, 5, 15, 60]
MAX_CONSECUTIVE_ERRORS = 5


def compute_initial_next_run(spawn: SpawnRecord) -> str | None:
    """Compute the initial next_run_at for a newly created spawn."""
    now = datetime.now(UTC)

    if spawn.schedule_type == "once":
        if spawn.schedule_at:
            return spawn.schedule_at
        return now.isoformat()

    elif spawn.schedule_type == "interval":
        if spawn.schedule_interval_minutes:
            return now.isoformat()  # Run immediately on creation
        return None

    elif spawn.schedule_type == "cron":
        return _next_cron_time(spawn.schedule_cron, spawn.schedule_timezone)

    return None


def compute_next_run(spawn: SpawnRecord) -> str | None:
    """Compute the next_run_at after a successful run.

    Returns None if the spawn should not run again (completed).
    """
    now = datetime.now(UTC)

    # Check completion conditions
    if spawn.schedule_type == "once":
        return None  # One-shot, done

    if spawn.run_count + 1 >= spawn.max_runs:
        return None  # Max runs reached

    if spawn.schedule_type == "interval":
        if not spawn.schedule_interval_minutes:
            return None
        next_time = now + timedelta(minutes=spawn.schedule_interval_minutes)
        return _apply_active_hours(next_time, spawn)

    elif spawn.schedule_type == "cron":
        next_time_str = _next_cron_time(spawn.schedule_cron, spawn.schedule_timezone)
        if next_time_str:
            next_time = datetime.fromisoformat(next_time_str)
            return _apply_active_hours(next_time, spawn)
        return None

    return None


def compute_backoff_next_run(spawn: SpawnRecord) -> str:
    """Compute next_run_at with exponential backoff after an error."""
    errors = min(spawn.consecutive_errors, len(_BACKOFF_MINUTES) - 1)
    delay = _BACKOFF_MINUTES[errors]
    next_time = datetime.now(UTC) + timedelta(minutes=delay)
    return next_time.isoformat()


def is_within_active_hours(spawn: SpawnRecord) -> bool:
    """Check if current time is within the spawn's active hours window."""
    if not spawn.active_hours_start or not spawn.active_hours_end:
        return True  # No active hours restriction

    tz_name = spawn.active_hours_timezone or spawn.schedule_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        logger.warning(f"Invalid timezone '{tz_name}', defaulting to UTC")
        tz = UTC

    now_local = datetime.now(tz)
    current_time = now_local.time()

    start = _parse_time(spawn.active_hours_start)
    end = _parse_time(spawn.active_hours_end)

    if start is None or end is None:
        return True

    # Handle overnight windows (e.g., 22:00 to 06:00)
    if start <= end:
        return start <= current_time <= end
    else:
        return current_time >= start or current_time <= end


def should_complete(spawn: SpawnRecord) -> bool:
    """Check if a spawn should be marked as completed after a run."""
    if spawn.schedule_type == "once":
        return True
    if spawn.run_count + 1 >= spawn.max_runs:
        return True
    return False


def should_fail(spawn: SpawnRecord) -> bool:
    """Check if a spawn should be marked as failed due to too many errors."""
    return spawn.consecutive_errors + 1 >= MAX_CONSECUTIVE_ERRORS


def _next_cron_time(cron_expr: str | None, tz_name: str | None = None) -> str | None:
    """Compute the next fire time for a cron expression."""
    if not cron_expr:
        return None

    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed, cron scheduling unavailable")
        return None

    tz_name = tz_name or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        tz = UTC

    now = datetime.now(tz)
    try:
        cron = croniter(cron_expr, now)
        next_fire = cron.get_next(datetime)
        # Convert to UTC for storage
        return next_fire.astimezone(UTC).isoformat()
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid cron expression '{cron_expr}': {e}")
        return None


def _apply_active_hours(next_time: datetime, spawn: SpawnRecord) -> str:
    """Adjust next_time to fall within active hours if configured."""
    if not spawn.active_hours_start or not spawn.active_hours_end:
        return next_time.isoformat()

    tz_name = spawn.active_hours_timezone or spawn.schedule_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, ValueError):
        return next_time.isoformat()

    local_time = next_time.astimezone(tz)
    start = _parse_time(spawn.active_hours_start)
    end = _parse_time(spawn.active_hours_end)

    if start is None or end is None:
        return next_time.isoformat()

    current_time = local_time.time()

    # Check if within window
    if start <= end:
        if start <= current_time <= end:
            return next_time.isoformat()
        # Outside window — advance to next window start
        if current_time < start:
            adjusted = local_time.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        else:
            adjusted = (local_time + timedelta(days=1)).replace(
                hour=start.hour, minute=start.minute, second=0, microsecond=0
            )
    else:
        # Overnight window
        if current_time >= start or current_time <= end:
            return next_time.isoformat()
        adjusted = local_time.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)

    return adjusted.astimezone(UTC).isoformat()


def _parse_time(time_str: str) -> dt_time | None:
    """Parse HH:MM time string."""
    try:
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None
