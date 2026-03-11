"""Adapted SubAgentMiddleware for middleware-based subagent orchestration.

Provides the `task` tool for delegating work to specialized subagents.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import BaseTool, ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from langgraph.config import get_stream_writer
from langgraph.types import Command

from deepanalysts.middleware._utils import append_to_system_message
from deepanalysts.utils.retry import create_async_retry

logger = logging.getLogger(__name__)


class SubAgent(TypedDict):
    """Specification for an analyst subagent."""

    name: str
    """The name of the agent (e.g., 'technical_analyst')."""

    description: str
    """Description used by supervisor to decide when to call this agent."""

    system_prompt: str
    """The system prompt for this agent."""

    tools: NotRequired[Sequence[BaseTool | Callable | dict[str, Any]]]
    """Tools available to this agent. If not specified, inherits from default_tools."""

    model: NotRequired[str | BaseChatModel]
    """Model for this agent. Defaults to default_model."""

    middleware: NotRequired[list[AgentMiddleware]]
    """Additional middleware to apply."""

    interrupt_on: NotRequired[dict[str, bool | InterruptOnConfig]]
    """Tool interrupt configurations."""

    skills: NotRequired[list[str]]
    """Skill source paths for SkillsMiddleware."""


class CompiledSubAgent(TypedDict):
    """A pre-compiled agent spec."""

    name: str
    description: str
    runnable: Runnable


DEFAULT_SUBAGENT_PROMPT = "Complete the task given to you using the available tools."

# State keys that are excluded when passing state to subagents and when returning
# updates from subagents.
# When returning updates:
# 1. The messages key is handled explicitly to ensure only the final message is included
# 2. The todos and structured_response keys are excluded as they do not have a defined reducer
#    and no clear meaning for returning them from a subagent to the main agent.
_EXCLUDED_STATE_KEYS = {"messages", "todos", "structured_response", "skills_metadata", "memory_contents"}


TASK_TOOL_DESCRIPTION = """Launch a specialized analyst subagent for trading tasks.

Available analysts:
{available_agents}

## When to Use

- Complex multi-step analysis requiring focused reasoning
- Independent research that can run in parallel
- Tasks requiring specialized tools (chart analysis, signal creation)

## When NOT to Use

- Simple price checks (use tools directly)
- Redundant calls - if subagent already analyzed same asset/timeframe, reuse the result
- Follow-up questions where analysis already exists in conversation

## Task Description Format

Always include asset context:
```
Analyze [SYMBOL] on [EXCHANGE] with [INTERVAL] timeframe.
[Specific task or question]
[Note: User has uploaded images - use get_user_images tool]
```

## Workflow Rules

- **Sequential**: Run dependent analyses in order (e.g., analysis first, then act on findings)
- **Parallel**: Run independent analyses simultaneously for speed

<good-example>
# Parallel: independent analyses
task(subagent="technical_analyst", description="Analyze BTC/USD on Binance H4...")
task(subagent="fundamental_analyst", description="Research BTC/USD news and earnings...")
</good-example>

<bad-example>
# Wrong: vague task without context
task(subagent="technical_analyst", description="Analyze BTC/USD")
# MUST include full context (symbol, exchange, timeframe, specific question) in description
</bad-example>

## Important

- Subagent results are invisible to user - YOU must synthesize and present
- Trust subagent outputs - they are specialized experts
- After subagents return, act on findings using your own tools
- Parallelize independent analyses for speed
"""


TASK_SYSTEM_PROMPT = """## Subagent Delegation

Use `task` tool to spawn specialized analysts. Subagent results are invisible to user.

After subagents return:
- Synthesize findings into clear response
- Act on findings using your own tools (only use tools available to you)
- Present to user with disclaimer

Note: Include user images in task description when available.
"""


def _create_subagents(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    default_middleware_factory: Callable[[str], list[AgentMiddleware]] | None,
    default_interrupt_on: dict[str, bool | InterruptOnConfig] | None,
    subagents: list[SubAgent | CompiledSubAgent],
) -> tuple[dict[str, Any], list[str]]:
    """Create subagent instances from specifications."""
    default_subagent_middleware = default_middleware or []

    agents: dict[str, Any] = {}
    subagent_descriptions = []

    for agent_spec in subagents:
        subagent_descriptions.append(f"- {agent_spec['name']}: {agent_spec['description']}")

        if "runnable" in agent_spec:
            # Pre-compiled agent
            compiled = cast("CompiledSubAgent", agent_spec)
            agents[compiled["name"]] = compiled["runnable"]
            continue

        # Build agent from spec
        _tools = agent_spec.get("tools", list(default_tools))
        _model = agent_spec.get("model", default_model)
        agent_name = agent_spec["name"]

        # Use factory for per-subagent middleware if provided, otherwise use default
        if default_middleware_factory:
            _middleware = default_middleware_factory(agent_name)
        else:
            _middleware = [*default_subagent_middleware]

        if "middleware" in agent_spec:
            _middleware.extend(agent_spec["middleware"])

        interrupt_on = agent_spec.get("interrupt_on", default_interrupt_on)
        if interrupt_on:
            _middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))

        # Bind tags to model for streaming identification
        if hasattr(_model, "bind_config"):
            _model = _model.bind_config(tags=[agent_name])

        agents[agent_name] = create_agent(
            _model,
            system_prompt=agent_spec["system_prompt"],
            tools=_tools,
            middleware=_middleware,
        )

    return agents, subagent_descriptions


def _create_task_tool(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    default_middleware_factory: Callable[[str], list[AgentMiddleware]] | None,
    default_interrupt_on: dict[str, bool | InterruptOnConfig] | None,
    subagents: list[SubAgent | CompiledSubAgent],
    task_description: str | None = None,
) -> BaseTool:
    """Create the task tool for invoking subagents."""
    subagent_graphs, subagent_descriptions = _create_subagents(
        default_model=default_model,
        default_tools=default_tools,
        default_middleware=default_middleware,
        default_middleware_factory=default_middleware_factory,
        default_interrupt_on=default_interrupt_on,
        subagents=subagents,
    )
    subagent_description_str = "\n".join(subagent_descriptions)

    if task_description is None:
        task_description = TASK_TOOL_DESCRIPTION.format(available_agents=subagent_description_str)
    elif "{available_agents}" in task_description:
        task_description = task_description.format(available_agents=subagent_description_str)

    def _return_command_with_state_update(result: dict, tool_call_id: str) -> Command:
        # Validate that the result contains a 'messages' key
        if "messages" not in result:
            error_msg = (
                "CompiledSubAgent must return a state containing a 'messages' key. "
                "Custom StateGraphs used with CompiledSubAgent should include 'messages' "
                "in their state schema to communicate results back to the main agent."
            )
            raise ValueError(error_msg)

        state_update = {k: v for k, v in result.items() if k not in _EXCLUDED_STATE_KEYS}
        # Strip trailing whitespace to prevent API errors with Anthropic
        message_text = result["messages"][-1].text.rstrip() if result["messages"][-1].text else ""
        return Command(
            update={
                **state_update,
                "messages": [ToolMessage(message_text, tool_call_id=tool_call_id)],
            }
        )

    def _validate_and_prepare_state(
        subagent_type: str, description: str, runtime: ToolRuntime
    ) -> tuple[Runnable, dict]:
        """Prepare state for invocation.

        Injects session context from config.configurable into the task
        description so subagents have the necessary context.
        """
        subagent = subagent_graphs[subagent_type]
        # Create a new state dict to avoid mutating the original
        subagent_state = {k: v for k, v in runtime.state.items() if k not in _EXCLUDED_STATE_KEYS}

        # Build session context from config
        configurable = (runtime.config or {}).get("configurable", {})
        symbol = configurable.get("symbol")
        exchange = configurable.get("exchange")
        interval = configurable.get("interval")
        current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        context_parts = ["## Session Context"]
        if symbol and exchange and interval:
            context_parts.append(
                f"User is currently viewing the **{symbol}** chart on the **{interval}** interval on **{exchange}**."
            )
            context_parts.append(f"All chart drawings and annotations must use the **{interval}** interval.")
        context_parts.append(f"Current time is **{current_time}**.")

        context_block = "\n".join(context_parts)
        task_content = f"{context_block}\n\n## Task\n{description}"

        subagent_state["messages"] = [HumanMessage(content=task_content)]
        return subagent, subagent_state

    def task(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        """Invoke a subagent with the given task description."""
        if subagent_type not in subagent_graphs:
            allowed = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"Unknown subagent '{subagent_type}'. Available: {allowed}"

        subagent, subagent_state = _validate_and_prepare_state(subagent_type, description, runtime)
        result = subagent.invoke(subagent_state, runtime.config)

        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for subagent invocation")

        return _return_command_with_state_update(result, runtime.tool_call_id)

    async def atask(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        """Async invoke a subagent.

        Uses ainvoke() with tags for subagent identification in streams.
        Includes retry logic for transient API errors using centralized retry utility.
        """
        if subagent_type not in subagent_graphs:
            allowed = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"Unknown subagent '{subagent_type}'. Available: {allowed}"

        subagent, subagent_state = _validate_and_prepare_state(subagent_type, description, runtime)
        # Create unique tag using tool_call_id to distinguish parallel instances.
        # Format: "technical_analyst:abc12345" allows streaming to identify which
        # parallel subagent is emitting events.
        instance_id = runtime.tool_call_id[:8] if runtime.tool_call_id else ""
        task_tag = f"{subagent_type}:{instance_id}" if instance_id else subagent_type

        # Merge runtime config with tags for subagent identification in streams
        config = {**runtime.config, "tags": [task_tag]} if runtime.config else {"tags": [task_tag]}

        writer = get_stream_writer()
        if writer:
            writer(
                {
                    "type": "task_spawned",
                    "data": {
                        "subagent_type": subagent_type,
                        "instance_id": instance_id,
                        "description": description,
                    },
                }
            )

        # Retry logic for transient API errors (5 attempts, exponential backoff 2s-16s)
        async for attempt in create_async_retry(max_attempts=5, min_wait=2.0, max_wait=16.0):
            with attempt:
                result = await subagent.ainvoke(subagent_state, config)

        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for subagent invocation")

        return _return_command_with_state_update(result, runtime.tool_call_id)

    return StructuredTool.from_function(
        name="task",
        func=task,
        coroutine=atask,
        description=task_description,
    )


class SubAgentMiddleware(AgentMiddleware):
    """Middleware that adds a `task` tool for invoking specialized analyst subagents.

    Args:
        default_model: Model for subagents that don't specify one.
        default_tools: Default tools for subagents.
        default_middleware: Middleware to apply to all subagents (static list).
        default_middleware_factory: Factory function to create per-subagent middleware.
                                    Takes subagent name and returns middleware list.
                                    Takes precedence over default_middleware if provided.
        default_interrupt_on: Default interrupt configurations.
        subagents: List of SubAgent definitions.
        system_prompt: Additional system prompt instructions.
        task_description: Custom description for the task tool.
    """

    def __init__(
        self,
        *,
        default_model: str | BaseChatModel,
        default_tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
        default_middleware: list[AgentMiddleware] | None = None,
        default_middleware_factory: Callable[[str], list[AgentMiddleware]] | None = None,
        default_interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        system_prompt: str | None = TASK_SYSTEM_PROMPT,
        task_description: str | None = None,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt

        task_tool = _create_task_tool(
            default_model=default_model,
            default_tools=default_tools or [],
            default_middleware=default_middleware,
            default_middleware_factory=default_middleware_factory,
            default_interrupt_on=default_interrupt_on,
            subagents=subagents or [],
            task_description=task_description,
        )
        self.tools = [task_tool]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Add analyst task instructions to system prompt."""
        if self.system_prompt is not None:
            system_message = append_to_system_message(request.system_message, self.system_prompt)
            return handler(request.override(system_message=system_message))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async: Add analyst task instructions to system prompt."""
        if self.system_prompt is not None:
            system_message = append_to_system_message(request.system_message, self.system_prompt)
            return await handler(request.override(system_message=system_message))
        return await handler(request)


__all__ = [
    "SubAgent",
    "CompiledSubAgent",
    "SubAgentMiddleware",
    "TASK_TOOL_DESCRIPTION",
    "TASK_SYSTEM_PROMPT",
]
