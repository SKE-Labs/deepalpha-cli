"""Spawn executor — runs individual spawn agents as background tasks.

Handles agent creation, timeout enforcement, result extraction,
error tracking with exponential backoff, and notification delivery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import HumanMessage

from deepalpha.context import get_auth_token, set_thread_id
from deepalpha.spawns.agent_factory import create_spawn_agent
from deepalpha.spawns.models import SpawnRecord, SpawnRunRecord, _new_id, _now_iso
from deepalpha.spawns.schedule import (
    compute_backoff_next_run,
    compute_next_run,
    is_within_active_hours,
    should_complete,
    should_fail,
)

if TYPE_CHECKING:
    from deepalpha.spawns.store import SpawnStore

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SPAWNS = 3
SPAWN_TIMEOUT_SECONDS = 300  # 5 minutes


class SpawnExecutor:
    """Executes individual spawn runs with lifecycle management."""

    def __init__(
        self,
        store: SpawnStore,
        on_result: Callable[[SpawnRecord, SpawnRunRecord], Any] | None = None,
    ):
        self._store = store
        self._on_result = on_result
        self._active: set[str] = set()  # spawn IDs currently executing
        self.max_concurrent = MAX_CONCURRENT_SPAWNS

    @property
    def active_count(self) -> int:
        return len(self._active)

    def can_accept(self) -> bool:
        return self.active_count < self.max_concurrent

    async def execute(self, spawn: SpawnRecord) -> None:
        """Execute a single spawn run with full lifecycle management."""
        if spawn.id in self._active:
            logger.debug(f"Spawn {spawn.id} already executing, skipping")
            return

        self._active.add(spawn.id)
        run = SpawnRunRecord(
            id=_new_id(),
            spawn_id=spawn.id,
            started_at=_now_iso(),
        )

        start_time = time.monotonic()

        try:
            if not is_within_active_hours(spawn):
                logger.info(f"Spawn '{spawn.name}' outside active hours, skipping")
                run.status = "skipped"
                run.completed_at = _now_iso()
                await self._finalize_run(spawn, run, "skipped")
                return

            logger.info(f"Executing spawn '{spawn.name}' (type={spawn.spawn_type}, run #{spawn.run_count + 1})")

            thread_id = f"spawn-{spawn.id}-{run.id}"
            set_thread_id(thread_id)

            agent = create_spawn_agent(spawn, model_override=spawn.model)
            message_content = self._build_message(spawn)

            result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [HumanMessage(content=message_content)]},
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                        }
                    },
                ),
                timeout=SPAWN_TIMEOUT_SECONDS,
            )

            result_text = self._extract_result(result)

            duration_ms = int((time.monotonic() - start_time) * 1000)
            run.status = "ok"
            run.result = result_text
            run.duration_ms = duration_ms
            run.completed_at = _now_iso()

            logger.info(f"Spawn '{spawn.name}' completed in {duration_ms}ms")

            await self._finalize_run(spawn, run, "success")

        except TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            run.status = "error"
            run.error = f"Execution timed out after {SPAWN_TIMEOUT_SECONDS}s"
            run.duration_ms = duration_ms
            run.completed_at = _now_iso()
            logger.error(f"Spawn '{spawn.name}' timed out after {SPAWN_TIMEOUT_SECONDS}s")
            await self._finalize_run(spawn, run, "error")

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            run.status = "error"
            run.error = str(e)[:500]
            run.duration_ms = duration_ms
            run.completed_at = _now_iso()
            logger.exception(f"Spawn '{spawn.name}' failed: {e}")
            await self._finalize_run(spawn, run, "error")

        finally:
            self._active.discard(spawn.id)

    async def _finalize_run(
        self,
        spawn: SpawnRecord,
        run: SpawnRunRecord,
        outcome: Literal["success", "error", "skipped"],
    ) -> None:
        """Persist run record, update spawn state, handle notifications."""
        await self._store.create_run(run)

        if outcome == "success":
            next_run = compute_next_run(spawn)
            updates: dict[str, Any] = {
                "run_count": spawn.run_count + 1,
                "last_run_at": run.completed_at,
                "consecutive_errors": 0,
            }

            if should_complete(spawn):
                updates["status"] = "completed"
                updates["next_run_at"] = None
            elif next_run:
                updates["next_run_at"] = next_run
            else:
                updates["status"] = "completed"
                updates["next_run_at"] = None

            await self._store.update_spawn(spawn.id, **updates)

            await self._maybe_notify(spawn, run)

        elif outcome == "error":
            new_errors = spawn.consecutive_errors + 1
            updates = {
                "run_count": spawn.run_count + 1,
                "consecutive_errors": new_errors,
                "last_run_at": run.completed_at,
            }

            if should_fail(spawn):
                updates["status"] = "failed"
                updates["next_run_at"] = None
                logger.warning(f"Spawn '{spawn.name}' failed after {new_errors} consecutive errors")
            else:
                updates["next_run_at"] = compute_backoff_next_run(spawn)

            await self._store.update_spawn(spawn.id, **updates)

        elif outcome == "skipped":
            next_run = compute_next_run(spawn)
            updates = {
                "run_count": spawn.run_count + 1,
            }
            if next_run:
                updates["next_run_at"] = next_run
            await self._store.update_spawn(spawn.id, **updates)

        await self._store.prune_runs(spawn.id, keep=50)

        if self._on_result:
            try:
                self._on_result(spawn, run)
            except Exception:
                logger.debug("on_result callback failed", exc_info=True)

    async def _maybe_notify(self, spawn: SpawnRecord, run: SpawnRunRecord) -> None:
        """Send notification via Basement if configured in spawn payload."""
        notification_config = spawn.payload.get("notification")
        if not notification_config:
            return

        token = get_auth_token()
        if not token:
            return

        try:
            from deepalpha.clients import basement_client

            title = notification_config.get("title", f"Spawn: {spawn.name}")
            body = run.result[:500] if run.result else f"Spawn '{spawn.name}' completed"
            priority = notification_config.get("priority", 5)

            await basement_client.send_notification(
                token=token,
                title=title,
                body=body,
                priority=priority,
                data={"spawn_id": spawn.id, "run_id": run.id},
            )
        except Exception:
            logger.debug("Failed to send spawn notification", exc_info=True)

    def _build_message(self, spawn: SpawnRecord) -> str:
        """Build the human message for the spawn agent."""
        parts = []

        parts.append(f"**Run #{spawn.run_count + 1}** of max {spawn.max_runs}")
        parts.append(f"Current time: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")

        if spawn.consecutive_errors > 0:
            parts.append(f"Last status: error (consecutive errors: {spawn.consecutive_errors})")
        elif spawn.last_run_at:
            parts.append("Last status: ok")

        parts.append("")

        if spawn.spawn_type == "monitoring" and spawn.signal_id:
            parts.append(f"**Monitor trading insight #{spawn.signal_id}**")
            parts.append("")
        message = spawn.payload.get("message", "")
        if message:
            parts.append(message)

        return "\n".join(parts)

    def _extract_result(self, result: dict) -> str:
        """Extract text from the agent's final response."""
        messages = result.get("messages", [])
        if not messages:
            return "No response generated."

        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                content = msg.content
                if isinstance(content, str):
                    return content[:2000]
                if isinstance(content, list):
                    # Handle content blocks (text + tool_use)
                    text_parts = []
                    for block in content:
                        if isinstance(block, str):
                            text_parts.append(block)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    if text_parts:
                        return "\n".join(text_parts)[:2000]

        return "Agent completed without text response."
