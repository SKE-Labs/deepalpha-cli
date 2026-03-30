"""Middleware to patch dangling tool calls in the messages history.

This middleware handles cases where an AIMessage has tool calls but no corresponding
ToolMessage responses. This can happen when:
- The agent is interrupted before completing a tool call
- An error occurs during tool execution
- A message comes in before tool calls complete

Without this middleware, dangling tool calls can cause API errors since most LLM
APIs require tool calls to have corresponding tool messages.
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Overwrite


class PatchToolCallsMiddleware(AgentMiddleware):
    """Middleware to patch dangling tool calls in the messages history.

    Iterates through messages and adds synthetic ToolMessage responses for any
    tool calls that don't have corresponding ToolMessages. The synthetic response
    indicates the tool call was cancelled.
    """

    def before_agent(
        self,
        state: AgentState,
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        """Before the agent runs, handle dangling tool calls from any AIMessage."""
        messages = state["messages"]
        if not messages or len(messages) == 0:
            return None

        patched_messages = []
        # Iterate over the messages and add any dangling tool calls
        for i, msg in enumerate(messages):
            patched_messages.append(msg)
            if msg.type == "ai" and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    corresponding_tool_msg = next(
                        (m for m in messages[i:] if m.type == "tool" and m.tool_call_id == tool_call["id"]),
                        None,
                    )
                    if corresponding_tool_msg is None:
                        # We have a dangling tool call which needs a ToolMessage
                        tool_msg = (
                            f"Tool call {tool_call['name']} with id {tool_call['id']} was "
                            "cancelled - another message came in before it could be completed."
                        )
                        patched_messages.append(
                            ToolMessage(
                                content=tool_msg,
                                name=tool_call["name"],
                                tool_call_id=tool_call["id"],
                            )
                        )

        return {"messages": Overwrite(patched_messages)}
