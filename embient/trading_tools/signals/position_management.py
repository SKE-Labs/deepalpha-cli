"""Position management tools for closing positions, cancelling signals, and notifications."""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from embient.clients import basement_client
from embient.context import get_jwt_token

logger = logging.getLogger(__name__)


class CancelSignalArgs(BaseModel):
    """Arguments for cancel_signal tool."""

    signal_id: int = Field(..., description="The trading insight ID to cancel")
    reason: str = Field(
        ...,
        description='Why the insight is being cancelled (e.g., "Pattern invalidated — key support at $180 broken before entry")',
    )


@tool(args_schema=CancelSignalArgs)
async def cancel_signal(
    signal_id: int,
    reason: str,
) -> str:
    """Cancel a trading insight that has NOT been executed yet.

    ## When to Use

    Use when an insight's thesis is invalidated BEFORE the user has entered the trade:
    - The pattern or setup that triggered the insight has broken down
    - Key support/resistance level was lost before entry
    - Market conditions changed making the thesis invalid
    - The entry window has passed without triggering

    ## How to Know if an Insight is Unexecuted

    Check the insight's `entry_price` field:
    - `entry_price` is **null/missing** → the user has NOT entered → use THIS tool
    - `entry_price` is **set** → the user HAS entered → use `close_position` instead

    ## When NOT to Use

    - The insight has been executed (has `entry_price`) — use `close_position` instead
    - You only need to adjust risk on an open position — use `update_trading_insight`
    - The insight is already closed or cancelled

    IMPORTANT:
    - This action is irreversible — a cancelled insight cannot be reactivated
    - Always provide a clear `reason` — it is shown to the user as the reflection

    Tool references:
    - Use `get_user_trading_insights` to check insight status and whether `entry_price` exists
    - Use `close_position` if the insight has already been executed
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Run 'embient login' first.")

    try:
        result = await basement_client.update_trading_signal(
            token=token,
            signal_id=signal_id,
            status="cancelled",
            reflection=reason,
        )

        if result is None:
            raise ToolException(f"Failed to cancel insight #{signal_id}.")

        return f"Insight #{signal_id} cancelled.\nReason: {reason}"

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"cancel_signal failed: {e}")
        raise ToolException(f"Error cancelling insight: {e}") from e


class ClosePositionArgs(BaseModel):
    """Arguments for close_position tool."""

    signal_id: int = Field(
        ...,
        description="The trading insight ID to close (must be an executed position with `entry_price`)",
    )
    exit_price: float = Field(
        ...,
        description="Current market price for the exit. Fetch via `get_latest_candle` — do not estimate.",
    )
    reason: str = Field(
        ...,
        description="Detailed reason for closing (shown to the user as trade reflection)",
    )


@tool(args_schema=ClosePositionArgs)
async def close_position(
    signal_id: int,
    exit_price: float,
    reason: str,
) -> str:
    """Close an executed trading position — calculates P&L and releases capital.

    ## When to Use

    Use when an EXECUTED position (user has entered, `entry_price` is set) must be fully exited:
    - Stop loss has been breached
    - Market structure has broken down
    - Risk/reward is no longer favorable
    - All take profit targets have been hit

    ## How to Know if a Position is Executed

    Check the insight's `entry_price` field:
    - `entry_price` is **set** → the user HAS entered → use THIS tool
    - `entry_price` is **null/missing** → the user has NOT entered → use `cancel_signal` instead

    ## When NOT to Use

    - The insight has NOT been executed (no `entry_price`) — use `cancel_signal` instead
    - You only need to modify the signal — use `update_trading_insight` instead
    - The position is already closed

    IMPORTANT:
    - This action is irreversible — a closed position cannot be reopened
    - This calculates realized P&L, releases locked capital, and updates the user's balance
    - Always provide a clear `reason` — it is shown to the user as the trade reflection
    - Use `get_latest_candle` to get the current price for `exit_price` — do not guess

    NEVER:
    - Close a position without checking the current price first
    - Use a stale or estimated price for `exit_price`
    - Use this on an unexecuted insight — use `cancel_signal` for those

    Tool references:
    - Use `get_latest_candle` to fetch current price before closing
    - Use `get_user_trading_insights` to check insight status
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Run 'embient login' first.")

    try:
        result = await basement_client.close_trading_signal(
            token=token,
            signal_id=signal_id,
            exit_price=exit_price,
            reflection=reason,
        )

        if result is None:
            raise ToolException(f"Failed to close position for insight #{signal_id}.")

        return f"Position closed for insight #{signal_id}.\nExit price: ${exit_price}\nReason: {reason}"

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"close_position failed: {e}")
        raise ToolException(f"Error closing position: {e}") from e


class SendNotificationArgs(BaseModel):
    """Arguments for send_notification tool."""

    title: str = Field(..., description="Notification title (keep under ~60 chars for mobile)")
    body: str = Field(..., description="Notification body text")
    priority: int = Field(default=5, description="Priority level 1-10 (default 5)")
    data: dict | None = Field(
        default=None,
        description='Optional additional data payload (e.g., {"signal_id": 123})',
    )


@tool(args_schema=SendNotificationArgs)
async def send_notification(
    title: str,
    body: str,
    priority: int = 5,
    data: dict | None = None,
) -> str:
    """Send a push notification to the user via web and mobile.

    Use this tool sparingly — only for genuinely important updates.

    ## When to Use (send at most ONE notification per run)

    - Task spawn completed: brief summary of what was accomplished
    - Urgent market condition requiring user's manual action
    - A key finding the user specifically asked to be alerted about

    ## When NOT to Use

    - You are in a live conversation — the user already sees your responses
    - Routine or incremental updates (price moved a little, indicator unchanged)
    - You just used `close_position`, `cancel_signal`, or `update_trading_insight`
      — the server sends notifications for these automatically
    - You have nothing new or actionable to report

    Keep `title` under ~60 characters for mobile display.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Run 'embient login' first.")

    try:
        result = await basement_client.send_notification(
            token=token,
            title=title,
            body=body,
            priority=priority,
            data=data,
        )

        if result is None:
            raise ToolException("Failed to send notification.")

        return f"Notification sent: {title}"

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"send_notification failed: {e}")
        raise ToolException(f"Error sending notification: {e}") from e
