"""Signal manager subagent definition."""

from deepanalysts import SubAgent
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain_core.language_models import BaseChatModel
from langgraph.runtime import Runtime

from deepalpha.trading_tools import (
    calculate_position_size,
    create_trading_insight,
    get_latest_candle,
    get_user_trading_insights,
    update_trading_insight,
)
from deepalpha.utils.prompt_loader import load_prompt

SIGNAL_MANAGER_PROMPT = load_prompt("analysts/signal_manager.md")


def _format_create_signal_description(tool_call: ToolCall, _state: AgentState, _runtime: Runtime) -> str:
    """Format create_trading_insight tool call for HITL approval prompt."""
    args = tool_call.get("args", {})
    symbol = args.get("symbol", "Unknown")
    position = args.get("position", "Unknown")
    entry_price = args.get("suggestion_price", "N/A")
    stop_loss = args.get("stop_loss", "N/A")
    take_profits = args.get("take_profit_levels", [])
    confidence = args.get("confidence_score", "N/A")
    quantity = args.get("quantity", "N/A")
    leverage = args.get("leverage", "N/A")
    capital = args.get("capital_allocated", "N/A")

    tp_str = ", ".join([f"${tp}" for tp in take_profits]) if take_profits else "N/A"

    return f"""Trading Signal Creation Requires Approval

**{position} {symbol}**

Trade Details:
- Entry Price: ${entry_price}
- Stop Loss: ${stop_loss}
- Take Profit: {tp_str}
- Confidence: {confidence}%

Position Sizing:
- Quantity: {quantity}
- Leverage: {leverage}x
- Capital: ${capital}

Review carefully before approving."""


def _format_update_signal_description(tool_call: ToolCall, _state: AgentState, _runtime: Runtime) -> str:
    """Format update_trading_insight tool call for HITL approval prompt."""
    args = tool_call.get("args", {})
    signal_id = args.get("signal_id", "Unknown")
    status = args.get("status")
    entry_price = args.get("entry_price")
    exit_price = args.get("exit_price")
    profit_loss = args.get("profit_loss")
    reflection = args.get("reflection")

    updates = []
    if status:
        updates.append(f"- Status -> {status}")
    if entry_price:
        updates.append(f"- Entry Price -> ${entry_price}")
    if exit_price:
        updates.append(f"- Exit Price -> ${exit_price}")
    if profit_loss is not None:
        updates.append(f"- P/L -> ${profit_loss:+.2f}")
    if reflection:
        updates.append(f"- Reflection: {reflection[:100]}...")

    updates_str = "\n".join(updates) if updates else "No changes specified"

    return f"""Trading Signal Update Requires Approval

**Signal #{signal_id}**

Updates:
{updates_str}

Review carefully before approving."""


def get_signal_manager(model: BaseChatModel) -> SubAgent:
    """Get signal manager subagent definition."""
    return {
        "name": "signal_manager",
        "description": (
            "Trading signal manager: create, update, and list trading signals. "
            "Use ONLY after technical_analyst has provided analysis. "
            "Handles position sizing, entry/exit levels, and signal lifecycle."
        ),
        "system_prompt": SIGNAL_MANAGER_PROMPT,
        "tools": [
            get_user_trading_insights,
            calculate_position_size,
            create_trading_insight,
            update_trading_insight,
            get_latest_candle,
        ],
        "model": model,
        "interrupt_on": {
            "create_trading_insight": {
                "allowed_decisions": ["approve", "reject"],
                "description": _format_create_signal_description,
            },
            "update_trading_insight": {
                "allowed_decisions": ["approve", "reject"],
                "description": _format_update_signal_description,
            },
        },
    }
