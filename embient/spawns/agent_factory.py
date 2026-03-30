"""Spawn agent factory — creates restricted one-shot agents for spawn execution.

Key differences from the main create_deep_analysts():
- No SubAgentMiddleware (no nesting — spawns are leaf agents)
- No HumanInTheLoopMiddleware (autonomous execution)
- No TodoListMiddleware (one-shot, no planning)
- Filtered tool set by spawn_type
- Custom system prompt per spawn_type
"""

from __future__ import annotations

import logging
from pathlib import Path

from deepanalysts.backends import BackendProtocol, FilesystemBackend
from deepanalysts.middleware import (
    FilesystemMiddleware,
    MemoryMiddleware,
    PatchToolCallsMiddleware,
    SkillsMiddleware,
    SummarizationMiddleware,
    ToolErrorHandlingMiddleware,
)
from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from embient.config import create_model
from embient.spawns.models import SpawnRecord
from embient.spawns.prompts import get_spawn_prompt
from embient.trading_tools import (
    calculate_position_size,
    cancel_signal,
    close_position,
    create_memory,
    create_trading_insight,
    delete_memory,
    generate_chart,
    get_candles_around_date,
    get_economics_calendar,
    get_financial_news,
    get_fundamentals,
    get_indicator,
    get_latest_candle,
    get_portfolio_summary,
    get_user_trading_insights,
    get_user_watchlist,
    list_memories,
    send_notification,
    update_memory,
    update_trading_insight,
    web_search,
)

logger = logging.getLogger(__name__)

# Monitoring spawns: position management + market data + research
_MONITORING_TOOLS = [
    # Market data
    get_latest_candle,
    get_indicator,
    get_candles_around_date,
    generate_chart,
    # Position management
    get_user_trading_insights,
    get_portfolio_summary,
    close_position,
    cancel_signal,
    update_trading_insight,
    calculate_position_size,
    # Research (for checking catalysts)
    get_financial_news,
    get_economics_calendar,
    # Notification
    send_notification,
]

# Task spawns: full research + analysis, no position management
_TASK_TOOLS = [
    # Market data
    get_latest_candle,
    get_indicator,
    get_candles_around_date,
    generate_chart,
    # Research
    web_search,
    get_financial_news,
    get_fundamentals,
    get_economics_calendar,
    get_user_watchlist,
    # Signals (read + create, no close/cancel)
    get_user_trading_insights,
    get_portfolio_summary,
    calculate_position_size,
    create_trading_insight,
    # Memory
    list_memories,
    create_memory,
    update_memory,
    delete_memory,
    # Notification
    send_notification,
]

_TOOLS_BY_TYPE = {
    "monitoring": _MONITORING_TOOLS,
    "task": _TASK_TOOLS,
}


def create_spawn_agent(
    spawn: SpawnRecord,
    *,
    model_override: str | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    backend: BackendProtocol | None = None,
    memory_sources: list[str] | None = None,
    skills_sources: list[str] | None = None,
) -> CompiledStateGraph:
    """Create a restricted agent for autonomous spawn execution.

    Args:
        spawn: The spawn record with type, model, and config.
        model_override: Override the spawn's model setting.
        checkpointer: Optional checkpointer. Defaults to InMemorySaver.
        backend: Optional filesystem backend. Defaults to FilesystemBackend.
        memory_sources: Optional memory source paths for MemoryMiddleware.
        skills_sources: Optional skill source paths for SkillsMiddleware.

    Returns:
        A compiled agent graph ready for single-run execution.
    """
    # Resolve model
    model_name = model_override or spawn.model
    model = create_model(model_name)

    # Resolve tools by spawn type
    tools = list(_TOOLS_BY_TYPE.get(spawn.spawn_type, _TASK_TOOLS))

    # System prompt
    system_prompt = get_spawn_prompt(spawn.spawn_type)

    # Backend
    fs_backend = backend if backend is not None else FilesystemBackend()

    # Built-in skills
    built_in_skills_dir = str(Path(__file__).parent.parent / "built_in_skills")
    all_skills = [built_in_skills_dir, *list(skills_sources or [])]

    # Build middleware stack (simplified: no SubAgent, no HITL, no TodoList)
    middleware: list[AgentMiddleware] = [
        ToolErrorHandlingMiddleware(),
        SummarizationMiddleware(
            model=model,
            backend=fs_backend,
            trigger=("tokens", 80000),
            keep=("messages", 15),
            truncate_args_settings={
                "trigger": ("messages", 15),
                "keep": ("messages", 15),
                "max_length": 2000,
            },
        ),
    ]

    if memory_sources:
        middleware.append(MemoryMiddleware(sources=memory_sources, backend=fs_backend))

    if all_skills:
        middleware.append(SkillsMiddleware(sources=all_skills, backend=fs_backend))

    middleware.extend(
        [
            FilesystemMiddleware(backend=fs_backend),
            PatchToolCallsMiddleware(),
        ]
    )

    # Checkpointer
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    logger.info(
        f"Creating spawn agent: type={spawn.spawn_type}, model={model_name}, "
        f"tools={len(tools)}, middleware={len(middleware)}"
    )

    return create_agent(
        model,
        system_prompt=system_prompt,
        tools=tools,
        middleware=middleware,
        checkpointer=final_checkpointer,
    ).with_config({"recursion_limit": 50})
