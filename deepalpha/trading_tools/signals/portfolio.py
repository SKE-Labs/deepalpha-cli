"""Portfolio summary tool for viewing account balance and open positions."""

import logging

from langchain_core.tools import ToolException, tool

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)


@tool
async def get_portfolio_summary() -> str:
    """Retrieve the user's portfolio summary including account balance, open positions, and performance metrics.

    ## When to Use

    - User asks about their portfolio, account balance, or overall performance
    - Before making trading recommendations to understand current exposure
    - To check available capital before suggesting new positions

    ## When NOT to Use

    - To check individual signal details — use `get_user_trading_insights`
    - To get current price — use `get_latest_candle`

    Returns: Formatted portfolio summary with balance, positions, P&L, and win rate.

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Run 'deepalpha login' first.")

    try:
        summary = await basement_client.get_portfolio_summary(token)

        if summary is None:
            raise ToolException("Failed to fetch portfolio summary. Please try again later.")

        lines = ["**Portfolio Summary**", ""]

        # Account info
        account_balance = summary.get("account_balance")
        available_balance = summary.get("available_balance")
        margin_used = summary.get("margin_used")

        if account_balance is not None:
            lines.append(f"- Account Balance: **${account_balance:,.2f}**")
        if available_balance is not None:
            lines.append(f"- Available Balance: **${available_balance:,.2f}**")
        if margin_used is not None:
            lines.append(f"- Margin Used: ${margin_used:,.2f}")

        # Performance metrics
        total_unrealized = summary.get("total_unrealized_pnl")
        total_realized = summary.get("total_realized_pnl")
        total_roi = summary.get("total_roi_percentage")
        win_rate = summary.get("win_rate")
        total_closed = summary.get("total_closed_trades")
        avg_rr = summary.get("avg_risk_reward")

        if any(v is not None for v in [total_unrealized, total_realized, win_rate]):
            lines.append("")
            lines.append("**Performance**")
            if total_unrealized is not None:
                lines.append(f"- Unrealized P&L: ${total_unrealized:,.2f}")
            if total_realized is not None:
                lines.append(f"- Realized P&L: ${total_realized:,.2f}")
            if total_roi is not None:
                lines.append(f"- Total ROI: {total_roi:.2f}%")
            if win_rate is not None:
                lines.append(f"- Win Rate: {win_rate:.1f}%")
            if total_closed is not None:
                lines.append(f"- Closed Trades: {total_closed}")
            if avg_rr is not None:
                lines.append(f"- Avg Risk/Reward: {avg_rr:.2f}")

        # Open positions
        open_positions = summary.get("open_positions", [])
        total_positions = summary.get("total_positions", len(open_positions))

        if open_positions:
            lines.append("")
            lines.append(f"**Open Positions ({total_positions})**")
            for pos in open_positions:
                symbol = pos.get("symbol", "?")
                position = pos.get("position", "?")
                entry = pos.get("entry_price")
                pnl = pos.get("unrealized_pnl")
                parts = [f"- {symbol} ({position})"]
                if entry:
                    parts.append(f"entry: ${entry:,.2f}")
                if pnl is not None:
                    parts.append(f"P&L: ${pnl:,.2f}")
                lines.append(" | ".join(parts))
        elif total_positions == 0:
            lines.append("")
            lines.append("No open positions.")

        return "\n".join(lines)

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"get_portfolio_summary failed: {e}")
        raise ToolException(f"Error fetching portfolio summary: {e}") from e
