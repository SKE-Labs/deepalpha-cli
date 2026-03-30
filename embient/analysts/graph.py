"""Deep Analysts agent using LangChain create_agent + SubAgentMiddleware pattern.

This module provides a middleware-based approach to the trading analyst workflow,
using the `task` tool pattern instead of explicit StateGraph routing.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deepanalysts.backends import BackendProtocol, FilesystemBackend
from deepanalysts.middleware import (
    FilesystemMiddleware,
    MemoryMiddleware,
    PatchToolCallsMiddleware,
    SkillsMiddleware,
    SubAgentMiddleware,
    SummarizationMiddleware,
    ToolErrorHandlingMiddleware,
)
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from embient.trading_tools import (
    calculate_position_size,
    cancel_signal,
    close_position,
    create_memory,
    create_trading_insight,
    delete_memory,
    get_latest_candle,
    get_portfolio_summary,
    get_user_trading_insights,
    get_user_watchlist,
    list_memories,
    send_notification,
    update_memory,
    update_trading_insight,
)
from embient.trading_tools.spawns import (
    cancel_spawn,
    create_spawn,
    get_spawn_runs,
    list_spawns,
    update_spawn,
)
from embient.utils.prompt_loader import load_prompt

SUPERVISOR_PROMPT = load_prompt("analysts/supervisor.md")

# Signal tools for orchestrator (handles signal management directly)
_SIGNAL_TOOLS = [
    get_latest_candle,
    get_user_trading_insights,
    get_portfolio_summary,
    get_user_watchlist,
    calculate_position_size,
    create_trading_insight,
    update_trading_insight,
    close_position,
    cancel_signal,
    send_notification,
]

# Memory tools for orchestrator (manages user memories directly)
_MEMORY_TOOLS = [
    list_memories,
    create_memory,
    update_memory,
    delete_memory,
]

# Spawn tools for orchestrator (manages autonomous background agents)
_SPAWN_TOOLS = [
    create_spawn,
    list_spawns,
    update_spawn,
    cancel_spawn,
    get_spawn_runs,
]


def create_deep_analysts(
    model: BaseChatModel,
    tools: Sequence[BaseTool | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    checkpointer: Checkpointer | None = None,
    backend: BackendProtocol | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    debug: bool = False,
) -> CompiledStateGraph:
    """Create a trading analyst agent with comprehensive middleware stack.

    This agent uses the `task` tool to delegate work to specialized analysts
    (technical_analyst, fundamental_analyst). The technical_analyst performs
    comprehensive multi-timeframe analysis (macro, swing, scalp) in a single pass.

    The orchestrator handles signal creation/updates directly (no signal_manager subagent).

    Middleware order (orchestrator):
    1. ToolErrorHandlingMiddleware - Graceful error handling
    2. TodoListMiddleware - Planning & task tracking
    3. SummarizationMiddleware - Context window management
    4. MemoryMiddleware - User preferences (if configured)
    5. SkillsMiddleware - Trading workflows (if configured)
    6. FilesystemMiddleware - Context management
    7. SubAgentMiddleware - Analyst delegation
    8. PatchToolCallsMiddleware - Handle dangling tool calls

    Subagents receive: ToolErrorHandlingMiddleware, SkillsMiddleware*, FilesystemMiddleware, PatchToolCallsMiddleware

    Args:
        model: The model to use for the orchestrator and subagents.
        tools: Additional tools to provide to the orchestrator.
        system_prompt: Override the default supervisor prompt.
        checkpointer: Optional checkpointer for state persistence.
        backend: Optional backend for filesystem operations. Defaults to FilesystemBackend.
        skills: Optional skill source paths (e.g., ["/skills/trading/"]).
        memory: Optional memory source paths (e.g., ["/memory/AGENTS.md"]).
        debug: Enable debug mode.

    Returns:
        A compiled agent graph.

    Usage:
        ```python
        from embient.analysts import create_deep_analysts
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model="gpt-4o")
        agent = create_deep_analysts(
            model,
            checkpointer=memory_saver,
        )

        # Invoke with session context
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Analyze BTC/USD")]},
            config={
                "configurable": {
                    "thread_id": "abc123",
                    "symbol": "BTC/USDT",
                    "exchange": "binance",
                    "interval": "4h",
                }
            },
        )
        ```
    """
    # Get analyst subagent definitions
    # Import here to avoid circular import
    from embient.analysts.fundamental import get_fundamental_analyst
    from embient.analysts.technical import get_technical_analyst

    subagents = [
        get_technical_analyst(model),
        get_fundamental_analyst(model),
    ]

    # Use provided backend or default to local filesystem
    fs_backend = backend if backend is not None else FilesystemBackend()

    # Built-in skills directory (memory-creator, etc.) + user-provided skills
    built_in_skills_dir = str(Path(__file__).parent.parent / "built_in_skills")
    all_skills = [built_in_skills_dir, *list(skills or [])]

    # Build subagent middleware factory
    def get_subagent_middleware(subagent_name: str) -> list[AgentMiddleware]:
        """Create middleware stack for a specific subagent.

        ToolErrorHandlingMiddleware is first to catch all tool errors before other
        middleware processes them. PatchToolCallsMiddleware is last to handle
        dangling tool calls from interruptions.
        """
        subagent_middleware: list[AgentMiddleware] = [
            ToolErrorHandlingMiddleware(),  # First: catch all tool errors
        ]

        if all_skills:
            subagent_middleware.append(SkillsMiddleware(sources=all_skills, backend=fs_backend))

        subagent_middleware.extend(
            [
                FilesystemMiddleware(backend=fs_backend),
                PatchToolCallsMiddleware(),  # Last: handle dangling tool calls
            ]
        )
        return subagent_middleware

    # Build orchestrator middleware stack
    middleware: list[AgentMiddleware] = [
        ToolErrorHandlingMiddleware(),
        TodoListMiddleware(),
        SummarizationMiddleware(
            model=model,
            backend=fs_backend,
            trigger=("tokens", 100000),
            keep=("messages", 20),
            truncate_args_settings={
                "trigger": ("messages", 20),
                "keep": ("messages", 20),
                "max_length": 2000,
            },
        ),
    ]

    if memory:
        middleware.append(MemoryMiddleware(sources=memory, backend=fs_backend))

    if all_skills:
        middleware.append(SkillsMiddleware(sources=all_skills, backend=fs_backend))

    middleware.extend(
        [
            FilesystemMiddleware(backend=fs_backend),
            SubAgentMiddleware(
                default_model=model,
                default_tools=tools or [],
                default_middleware_factory=get_subagent_middleware,
                subagents=subagents,
            ),
            PatchToolCallsMiddleware(),  # Handle dangling tool calls from interruptions
            # HITL for signal management (orchestrator handles these directly)
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "create_trading_insight": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                    "update_trading_insight": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                    "close_position": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                    "cancel_signal": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                    "create_spawn": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                }
            ),
        ]
    )

    # Combine signal tools, memory tools, spawn tools, and any additional tools passed in
    all_tools = list(_SIGNAL_TOOLS) + list(_MEMORY_TOOLS) + list(_SPAWN_TOOLS) + list(tools or [])

    return create_agent(
        model,
        system_prompt=system_prompt or SUPERVISOR_PROMPT,
        tools=all_tools,
        middleware=middleware,
        checkpointer=checkpointer,
        debug=debug,
    ).with_config({"recursion_limit": 100})
