"""Non-interactive execution mode for embient CLI.

Provides `run_non_interactive` which runs a single user task against the
agent graph, streams results to stdout, and exits with an appropriate code.

In non-interactive mode, all tool calls are auto-approved (no HITL prompts).
An optional quiet mode (`--quiet` / `-q`) redirects all console output to
stderr, leaving stdout exclusively for the agent's response text.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from langchain_core.messages import AIMessage
from langgraph.types import Command, Interrupt
from pydantic import TypeAdapter, ValidationError
from rich.console import Console

from embient.agent import create_cli_agent
from embient.config import create_model
from embient.sessions import generate_thread_id, get_checkpointer
from embient.tools import fetch_url, http_request
from embient.trading_tools.research import web_search as park_web_search

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.pregel import Pregel

logger = logging.getLogger(__name__)

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)
_STREAM_CHUNK_LENGTH = 3
_MESSAGE_DATA_LENGTH = 2
_MAX_HITL_ITERATIONS = 50


def _write_text(text: str) -> None:
    """Write agent response text to stdout."""
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_newline() -> None:
    sys.stdout.write("\n")
    sys.stdout.flush()


@dataclass
class StreamState:
    """Mutable state accumulated while iterating over the agent stream."""

    quiet: bool = False
    full_response: list[str] = field(default_factory=list)
    tool_call_buffers: dict[int | str, dict[str, str | None]] = field(default_factory=dict)
    pending_interrupts: dict[str, HITLRequest] = field(default_factory=dict)
    hitl_response: dict[str, dict[str, list[dict[str, str]]]] = field(default_factory=dict)
    interrupt_occurred: bool = False


def _process_interrupts(
    data: dict[str, list[Interrupt]],
    state: StreamState,
    console: Console,
) -> None:
    """Extract HITL interrupts from an updates chunk and auto-approve them."""
    interrupts = data["__interrupt__"]
    if interrupts:
        for interrupt_obj in interrupts:
            try:
                validated_request = _HITL_REQUEST_ADAPTER.validate_python(interrupt_obj.value)
            except ValidationError:
                logger.warning("Rejecting malformed HITL interrupt %s", interrupt_obj.id)
                state.hitl_response[interrupt_obj.id] = {
                    "decisions": [{"type": "reject", "message": "Malformed interrupt"}]
                }
                continue
            state.pending_interrupts[interrupt_obj.id] = validated_request
            state.interrupt_occurred = True


def _process_ai_message(
    message_obj: AIMessage,
    state: StreamState,
    console: Console,
) -> None:
    """Extract text and tool-call blocks from an AI message."""
    if not hasattr(message_obj, "content_blocks"):
        return
    for block in message_obj.content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if text:
                _write_text(text)
                state.full_response.append(text)
        elif block_type in {"tool_call_chunk", "tool_call"}:
            chunk_name = block.get("name")
            chunk_index = block.get("index")
            chunk_id = block.get("id")
            buffer_key: int | str
            if chunk_index is not None:
                buffer_key = chunk_index
            elif chunk_id is not None:
                buffer_key = chunk_id
            else:
                buffer_key = f"unknown-{len(state.tool_call_buffers)}"
            if buffer_key not in state.tool_call_buffers:
                state.tool_call_buffers[buffer_key] = {"name": None, "id": None}
            if chunk_name:
                state.tool_call_buffers[buffer_key]["name"] = chunk_name
                if state.full_response and not state.quiet:
                    _write_newline()
                console.print(f"[dim]Calling tool: {chunk_name}[/dim]")


def _process_stream_chunk(
    chunk: object,
    state: StreamState,
    console: Console,
) -> None:
    """Route a single raw stream chunk to the appropriate handler."""
    if not isinstance(chunk, tuple) or len(chunk) != _STREAM_CHUNK_LENGTH:
        return

    namespace, stream_mode, data = chunk
    if namespace:  # Skip subagent output
        return

    if stream_mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
        _process_interrupts(cast("dict[str, list[Interrupt]]", data), state, console)
    elif stream_mode == "messages":
        if not isinstance(data, tuple) or len(data) != _MESSAGE_DATA_LENGTH:
            return
        message_obj, metadata = data
        # Skip summarization middleware synthetic messages
        if metadata and metadata.get("lc_source") == "summarization":
            return
        if isinstance(message_obj, AIMessage):
            _process_ai_message(message_obj, state, console)


def _process_hitl_interrupts(state: StreamState, console: Console) -> None:
    """Auto-approve all pending HITL interrupts."""
    current_interrupts = dict(state.pending_interrupts)
    state.pending_interrupts.clear()

    for interrupt_id, hitl_request in current_interrupts.items():
        decisions = []
        for action_request in hitl_request["action_requests"]:
            action_name = action_request.get("name", "")
            console.print(f"[dim]Auto-approved: {action_name}[/dim]")
            decisions.append({"type": "approve"})
        state.hitl_response[interrupt_id] = {"decisions": decisions}


async def _stream_agent(
    agent: Pregel,
    stream_input: dict[str, Any] | Command,
    config: RunnableConfig,
    state: StreamState,
    console: Console,
) -> None:
    """Consume the full agent stream and update state with results."""
    async for chunk in agent.astream(
        stream_input,
        stream_mode=["messages", "updates"],
        subgraphs=True,
        config=config,
    ):
        _process_stream_chunk(chunk, state, console)


async def _run_agent_loop(
    agent: Pregel,
    message: str,
    config: RunnableConfig,
    console: Console,
    *,
    quiet: bool = False,
) -> None:
    """Run the agent and handle HITL interrupts until the task completes."""
    state = StreamState(quiet=quiet)
    stream_input: dict[str, Any] | Command = {"messages": [{"role": "user", "content": message}]}

    await _stream_agent(agent, stream_input, config, state, console)

    iterations = 0
    while state.interrupt_occurred:
        iterations += 1
        if iterations > _MAX_HITL_ITERATIONS:
            raise RuntimeError(
                f"Exceeded {_MAX_HITL_ITERATIONS} HITL interrupt rounds. "
                "The agent may be stuck retrying rejected commands."
            )
        state.interrupt_occurred = False
        state.hitl_response.clear()
        _process_hitl_interrupts(state, console)
        stream_input = Command(resume=state.hitl_response)
        await _stream_agent(agent, stream_input, config, state, console)

    if state.full_response:
        _write_newline()

    if not quiet:
        console.print()
        console.print("[green]Task completed[/green]")


async def run_non_interactive(
    message: str,
    assistant_id: str = "agent",
    model_name: str | None = None,
    provider_name: str | None = None,
    *,
    quiet: bool = False,
    auto_approve: bool = True,
) -> int:
    """Run a single task non-interactively and exit.

    All tool calls are auto-approved in non-interactive mode.

    Args:
        message: The task/message to execute.
        assistant_id: Agent identifier for memory storage.
        model_name: Optional model name to use.
        provider_name: Optional provider override (copilot, zai, etc.).
        quiet: When True, console output goes to stderr; stdout is agent text only.
        auto_approve: Auto-approve all HITL prompts.

    Returns:
        Exit code: 0 for success, 1 for error, 130 for keyboard interrupt.
    """
    console = Console(stderr=True) if quiet else Console()

    try:
        model = create_model(model_name, provider_override=provider_name)
    except SystemExit:
        console.print("[bold red]Error:[/bold red] Failed to create model")
        return 1

    thread_id = generate_thread_id()

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "assistant_id": assistant_id,
            "agent_name": assistant_id,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    }

    if not quiet:
        console.print("[dim]Running task non-interactively...[/dim]")
        console.print(f"[dim]Agent: {assistant_id} | Thread: {thread_id}[/dim]")
        console.print()

    try:
        async with get_checkpointer() as checkpointer:
            tools = [http_request, fetch_url, park_web_search]

            agent, _backend = create_cli_agent(
                model=model,
                assistant_id=assistant_id,
                tools=tools,
                auto_approve=auto_approve,
                checkpointer=checkpointer,
            )

            await _run_agent_loop(
                agent,
                message,
                config,
                console,
                quiet=quiet,
            )
            return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 130
    except (ValueError, OSError) as e:
        logger.exception("Error during non-interactive execution")
        console.print(f"\n[red]Error: {e}[/red]")
        return 1
    except Exception as e:
        logger.exception("Unexpected error during non-interactive execution")
        console.print(f"\n[red]Unexpected error ({type(e).__name__}): {e}[/red]")
        return 1
