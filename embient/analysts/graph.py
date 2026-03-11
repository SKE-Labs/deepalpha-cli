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
    create_memory,
    create_trading_signal,
    delete_memory,
    get_active_trading_signals,
    get_latest_candle,
    list_memories,
    update_memory,
    update_trading_signal,
)

SUPERVISOR_PROMPT = """# Embient AI Trading Analyst

You orchestrate specialized analysts to answer trading questions. Handle quick queries directly and delegate deep analysis to experts.

NEVER:
- Delegate signal creation, position sizing, or signal updates to analysts — handle these yourself
- Invent price levels or position sizes — always get data from tools or analyst findings

## When to Act Directly vs Delegate

**Handle directly** (no delegation needed):
- Quick price checks → `get_latest_candle`
- Viewing signals → `get_active_trading_signals`
- Updating signals → `update_trading_signal` (HITL approval)
- Signal creation → `calculate_position_size` → `create_trading_signal` (HITL approval)

**Delegate to specialists**:
- **technical_analyst** — Multi-timeframe chart analysis (macro, swing, scalp). Analyzes 1d (macro), 1h (swing), and 15m (scalp) in a single comprehensive analysis.
- **fundamental_analyst** — Deep research combining news, sentiment, and market events.

## Workflow Rules

- **Full analysis** → technical_analyst (all timeframes) → respond
- **Signal creation** → technical_analyst → `get_latest_candle` → `calculate_position_size` → `create_trading_signal` → respond
- **Signal update** → `update_trading_signal` directly
- **News/fundamentals** → fundamental_analyst

## Signal Creation

After analyst returns findings:
1. `get_latest_candle` → suggestion_price
2. `calculate_position_size` → quantity, leverage, capital_allocated
3. `create_trading_signal` → uses analysis context (entry, SL, TP, rationale, invalid_condition, confidence)

Use exact price levels from analyst findings. See `create_trading_signal` tool docs for field quality standards.

**confidence_score** — Use the confidence score from the technical analyst based on timeframe confluence.

## Professional Objectivity

Prioritize accuracy over validating the user's expectations. If the chart contradicts their thesis, say so directly. If signals are mixed or confidence is low, be clear about it. Objective guidance is more valuable than false agreement.

## Response Style

Keep responses concise:
- **Summary**: 1-2 sentences on what you found
- **Key Findings**: 3-5 bullets with the most important insights
- **Action**: Next steps if applicable

Use markdown formatting. End trading recommendations with:
> **Disclaimer**: Educational purposes only. Not financial advice. DYOR.
"""

# Signal tools for orchestrator (handles signal management directly)
_SIGNAL_TOOLS = [
    get_latest_candle,
    get_active_trading_signals,
    calculate_position_size,
    create_trading_signal,
    update_trading_signal,
]

# Memory tools for orchestrator (manages user memories directly)
_MEMORY_TOOLS = [
    list_memories,
    create_memory,
    update_memory,
    delete_memory,
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
            # HITL for signal creation/updates (orchestrator handles these directly)
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "create_trading_signal": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                    "update_trading_signal": {
                        "allowed_decisions": ["approve", "reject"],
                    },
                }
            ),
        ]
    )

    # Combine signal tools, memory tools, and any additional tools passed in
    all_tools = list(_SIGNAL_TOOLS) + list(_MEMORY_TOOLS) + list(tools or [])

    return create_agent(
        model,
        system_prompt=system_prompt or SUPERVISOR_PROMPT,
        tools=all_tools,
        middleware=middleware,
        checkpointer=checkpointer,
        debug=debug,
    ).with_config({"recursion_limit": 100})
