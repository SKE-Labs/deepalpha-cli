"""Spawn management tools for the orchestrator agent.

These tools let the LLM create, list, update, cancel spawns and view run history.
Spawns run locally using the user's own API keys (BYOK).
"""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from embient.context import get_spawn_manager

logger = logging.getLogger(__name__)


def _get_manager():
    """Get the SpawnManager from context, raising if not available."""
    manager = get_spawn_manager()
    if manager is None:
        raise ToolException("Spawn system is not running. Please restart the CLI.")
    return manager


class CreateSpawnArgs(BaseModel):
    """Arguments for create_spawn tool."""

    name: str = Field(
        ..., description="Short descriptive name for the spawn (e.g., 'BTC monitoring', 'Daily portfolio summary')"
    )
    spawn_type: str = Field(..., description="Type: 'monitoring' (position management) or 'task' (analysis/research)")
    schedule_type: str = Field(
        ..., description="Schedule: 'once' (single run), 'interval' (recurring minutes), or 'cron' (cron expression)"
    )
    payload_message: str = Field(..., description="The task/instruction for the spawn agent to execute each run")
    description: str | None = Field(default=None, description="Longer description of what this spawn does")
    schedule_at: str | None = Field(
        default=None, description="ISO timestamp for 'once' schedule (e.g., '2026-03-29T15:00:00Z')"
    )
    schedule_interval_minutes: int | None = Field(
        default=None, description="Minutes between runs for 'interval' schedule"
    )
    schedule_cron: str | None = Field(
        default=None, description="5-field cron expression for 'cron' schedule (e.g., '30 9 * * 1-5')"
    )
    schedule_timezone: str = Field(default="UTC", description="IANA timezone for schedule evaluation")
    model: str | None = Field(
        default=None, description="LLM model override (e.g., 'gpt-5-mini', 'claude-sonnet-4-5-20250929')"
    )
    signal_id: int | None = Field(
        default=None, description="Trading insight ID to monitor (required for monitoring spawns)"
    )
    max_runs: int = Field(default=15, description="Auto-complete after this many runs")
    active_hours_start: str | None = Field(
        default=None, description="Active window start in HH:MM format (e.g., '09:30')"
    )
    active_hours_end: str | None = Field(default=None, description="Active window end in HH:MM format (e.g., '16:00')")
    send_notification: bool = Field(default=True, description="Send push notification on completion")


@tool(args_schema=CreateSpawnArgs)
async def create_spawn(
    name: str,
    spawn_type: str,
    schedule_type: str,
    payload_message: str,
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
    send_notification: bool = True,
) -> str:
    """Create a local autonomous spawn that runs on YOUR machine using YOUR API key (BYOK).

    Spawns are background agents that execute scheduled tasks autonomously.

    ## Spawn Types

    - **monitoring**: Monitors a trading insight — checks price vs SL/TP, evaluates thesis validity, manages position. Requires `signal_id`.
    - **task**: Executes any analysis/research task — pattern scanning, portfolio summaries, news monitoring, etc.

    ## Schedule Types

    - **once**: Runs once at `schedule_at` timestamp, then auto-completes.
    - **interval**: Runs every `schedule_interval_minutes` minutes (e.g., every 30 min).
    - **cron**: Runs on a cron schedule (e.g., '30 9 * * 1-5' = 9:30 AM weekdays).

    ## When to Use

    - User asks to "monitor this position" or "watch this signal" → monitoring spawn
    - User asks to "check X every hour" or "send me a daily summary" → task spawn
    - User asks for a one-time scheduled analysis → task spawn with once schedule

    ## When NOT to Use

    - For immediate analysis → just do it directly
    - For one-off price checks → use get_latest_candle

    IMPORTANT:
    - Spawns use the user's API key for LLM calls — each run consumes tokens
    - Monitoring spawns REQUIRE signal_id
    - Interval spawns REQUIRE schedule_interval_minutes
    - Cron spawns REQUIRE schedule_cron
    - The CLI must be running for spawns to execute
    """
    manager = _get_manager()

    # Validation
    if spawn_type not in ("monitoring", "task"):
        raise ToolException(f"Invalid spawn_type '{spawn_type}'. Must be 'monitoring' or 'task'.")
    if spawn_type == "monitoring" and not signal_id:
        raise ToolException(
            "Monitoring spawns require a signal_id. Use get_user_trading_insights to find the signal ID."
        )
    if schedule_type == "interval" and not schedule_interval_minutes:
        raise ToolException("Interval schedule requires schedule_interval_minutes.")
    if schedule_type == "cron" and not schedule_cron:
        raise ToolException("Cron schedule requires schedule_cron expression.")
    if schedule_type == "once" and not schedule_at:
        raise ToolException("Once schedule requires schedule_at ISO timestamp.")

    notification_config = {"title": f"Spawn: {name}", "priority": 5} if send_notification else None

    try:
        spawn = await manager.create_spawn(
            name=name,
            spawn_type=spawn_type,
            schedule_type=schedule_type,
            payload_message=payload_message,
            description=description,
            schedule_at=schedule_at,
            schedule_interval_minutes=schedule_interval_minutes,
            schedule_cron=schedule_cron,
            schedule_timezone=schedule_timezone,
            model=model,
            signal_id=signal_id,
            max_runs=max_runs,
            active_hours_start=active_hours_start,
            active_hours_end=active_hours_end,
            notification_config=notification_config,
        )

        lines = [
            f"Spawn created: **{spawn.name}** (ID: {spawn.id})",
            f"- Type: {spawn.spawn_type}",
            f"- Schedule: {schedule_type}",
        ]
        if schedule_interval_minutes:
            lines.append(f"- Interval: every {schedule_interval_minutes} minutes")
        if schedule_cron:
            lines.append(f"- Cron: {schedule_cron} ({schedule_timezone})")
        if spawn.next_run_at:
            lines.append(f"- Next run: {spawn.next_run_at}")
        lines.append(f"- Max runs: {max_runs}")
        if signal_id:
            lines.append(f"- Monitoring signal: #{signal_id}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"create_spawn failed: {e}")
        raise ToolException(f"Error creating spawn: {e}") from e


class ListSpawnsArgs(BaseModel):
    """Arguments for list_spawns tool."""

    status: str | None = Field(
        default=None,
        description="Filter by status: active, paused, completed, failed, cancelled. Omit for all.",
    )


@tool(args_schema=ListSpawnsArgs)
async def list_spawns(status: str | None = None) -> str:
    """List all local spawns with their status and schedule.

    ## When to Use

    - User asks "what spawns do I have?" or "show my monitors"
    - Before creating a new spawn, to check for duplicates
    - To check spawn status after creation

    Returns: Formatted list of spawns with ID, name, type, status, schedule, and run count.
    """
    manager = _get_manager()

    try:
        spawns = await manager.list_spawns(status=status)

        if not spawns:
            if status:
                return f"No spawns with status '{status}'."
            return "No spawns created yet. Use create_spawn to schedule autonomous tasks."

        lines = [f"**Spawns ({len(spawns)})**", ""]
        for s in spawns:
            lines.append(f"- **{s.name}** (ID: {s.id})")
            lines.append(f"  Type: {s.spawn_type} | Status: {s.status} | Schedule: {s.schedule_display}")
            lines.append(f"  Runs: {s.run_count}/{s.max_runs} | Next: {s.next_run_at or 'N/A'}")
            if s.signal_id:
                lines.append(f"  Signal: #{s.signal_id}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"list_spawns failed: {e}")
        raise ToolException(f"Error listing spawns: {e}") from e


class UpdateSpawnArgs(BaseModel):
    """Arguments for update_spawn tool."""

    spawn_id: str = Field(..., description="The spawn ID to update")
    action: str = Field(
        ...,
        description="Action: 'pause' (stop scheduling), 'resume' (restart scheduling), or 'update' (modify settings)",
    )
    schedule_interval_minutes: int | None = Field(default=None, description="New interval (for interval schedules)")
    max_runs: int | None = Field(default=None, description="New max runs limit")
    active_hours_start: str | None = Field(default=None, description="New active hours start (HH:MM)")
    active_hours_end: str | None = Field(default=None, description="New active hours end (HH:MM)")


@tool(args_schema=UpdateSpawnArgs)
async def update_spawn(
    spawn_id: str,
    action: str,
    schedule_interval_minutes: int | None = None,
    max_runs: int | None = None,
    active_hours_start: str | None = None,
    active_hours_end: str | None = None,
) -> str:
    """Update, pause, or resume a spawn.

    ## Actions

    - **pause**: Stop the spawn from running (preserves config, can resume later)
    - **resume**: Restart a paused spawn
    - **update**: Modify spawn settings (interval, max_runs, active_hours)

    ## When to Use

    - User wants to pause/resume monitoring
    - User wants to change check frequency
    - User wants to extend or limit remaining runs
    """
    manager = _get_manager()

    try:
        if action == "pause":
            ok = await manager.pause_spawn(spawn_id)
            if not ok:
                raise ToolException(f"Cannot pause spawn {spawn_id} — not found or not active.")
            return f"Spawn {spawn_id} paused."

        elif action == "resume":
            ok = await manager.resume_spawn(spawn_id)
            if not ok:
                raise ToolException(f"Cannot resume spawn {spawn_id} — not found or not paused.")
            return f"Spawn {spawn_id} resumed."

        elif action == "update":
            updates = {}
            if schedule_interval_minutes is not None:
                updates["schedule_interval_minutes"] = schedule_interval_minutes
            if max_runs is not None:
                updates["max_runs"] = max_runs
            if active_hours_start is not None:
                updates["active_hours_start"] = active_hours_start
            if active_hours_end is not None:
                updates["active_hours_end"] = active_hours_end

            if not updates:
                raise ToolException("No update fields provided.")

            result = await manager.update_spawn(spawn_id, **updates)
            if result is None:
                raise ToolException(f"Spawn {spawn_id} not found.")

            return f"Spawn {spawn_id} updated: {', '.join(f'{k}={v}' for k, v in updates.items())}"

        else:
            raise ToolException(f"Invalid action '{action}'. Must be 'pause', 'resume', or 'update'.")

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"update_spawn failed: {e}")
        raise ToolException(f"Error updating spawn: {e}") from e


class CancelSpawnArgs(BaseModel):
    """Arguments for cancel_spawn tool."""

    spawn_id: str = Field(..., description="The spawn ID to cancel")
    reason: str | None = Field(default=None, description="Why the spawn is being cancelled")


@tool(args_schema=CancelSpawnArgs)
async def cancel_spawn(
    spawn_id: str,
    reason: str | None = None,
) -> str:
    """Cancel a spawn permanently — it will not run again.

    ## When to Use

    - User wants to stop a spawn completely (not just pause)
    - A monitoring spawn's position has been closed manually
    - A task spawn is no longer needed

    ## When NOT to Use

    - User just wants to temporarily stop → use update_spawn with action='pause'
    """
    manager = _get_manager()

    try:
        ok = await manager.cancel_spawn(spawn_id)
        if not ok:
            raise ToolException(f"Cannot cancel spawn {spawn_id} — not found, already completed, or already cancelled.")

        msg = f"Spawn {spawn_id} cancelled."
        if reason:
            msg += f" Reason: {reason}"
        return msg

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"cancel_spawn failed: {e}")
        raise ToolException(f"Error cancelling spawn: {e}") from e


class GetSpawnRunsArgs(BaseModel):
    """Arguments for get_spawn_runs tool."""

    spawn_id: str = Field(..., description="The spawn ID to view run history for")
    limit: int = Field(default=5, description="Number of recent runs to show (default 5)")


@tool(args_schema=GetSpawnRunsArgs)
async def get_spawn_runs(
    spawn_id: str,
    limit: int = 5,
) -> str:
    """View run history for a spawn — shows status, duration, and result summary.

    ## When to Use

    - User asks "how is my monitor doing?" or "what did the spawn find?"
    - To check if a spawn is running successfully or encountering errors
    - To review what a spawn reported in recent runs

    Returns: List of recent runs with status, timing, and result preview.
    """
    manager = _get_manager()

    try:
        runs = await manager.get_spawn_runs(spawn_id, limit=limit)

        if not runs:
            return f"No runs recorded for spawn {spawn_id} yet."

        spawn = await manager.get_spawn(spawn_id)
        name = spawn.name if spawn else spawn_id

        lines = [f"**Recent runs for '{name}'** ({len(runs)} shown)", ""]
        for r in runs:
            duration = f"{r.duration_ms}ms" if r.duration_ms else "N/A"
            lines.append(f"- **{r.status.upper()}** | {r.started_at} | {duration}")
            if r.error:
                lines.append(f"  Error: {r.error[:200]}")
            elif r.result:
                # Show first 200 chars of result
                preview = r.result[:200].replace("\n", " ")
                lines.append(f"  Result: {preview}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"get_spawn_runs failed: {e}")
        raise ToolException(f"Error fetching spawn runs: {e}") from e
