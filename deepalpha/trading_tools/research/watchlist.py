"""Watchlist tool for retrieving user's favorite tickers."""

import logging

from langchain_core.tools import ToolException, tool

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)


@tool
async def get_user_watchlist() -> str:
    """Fetch the user's watchlist — the tickers they have marked as favorites.

    ## When to Use

    - User asks about "my watchlist", "my favorites", or "which assets am I tracking"
    - Before suggesting analysis targets when no specific symbol is given
    - To understand the user's active trading universe for contextual recommendations

    ## When NOT to Use

    - To see open positions — use `get_user_trading_insights`
    - To get current price — use `get_latest_candle`

    Returns: Formatted list of watchlist tickers with symbol, name, and exchange.

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Run 'deepalpha login' first.")

    try:
        tickers = await basement_client.get_favorite_tickers(token)

        if tickers is None:
            raise ToolException("Failed to fetch watchlist. Please try again later.")

        if not tickers:
            return "The user's watchlist is empty."

        lines = [f"User's watchlist ({len(tickers)} tickers):"]
        lines.append(
            "NOTE: When calling tools (e.g. analyze_chart, get_latest_candle) for these "
            "tickers, use the **symbol** value as the symbol parameter. If an **exchange** "
            "is listed, pass it as the exchange parameter."
        )
        lines.append("")
        for t in tickers:
            symbol = t.get("ticker") or t.get("symbol") or "?"
            name = t.get("name", "")
            exchange = t.get("exchange", "")
            market = t.get("market", "")

            parts = [f"- symbol: **{symbol}**"]
            if name:
                parts.append(f"({name})")
            if exchange:
                parts.append(f"| exchange: **{exchange}**")
            if market:
                parts.append(f"[{market}]")
            lines.append(" ".join(parts))

        return "\n".join(lines)

    except ToolException:
        raise
    except Exception as e:
        logger.error(f"get_user_watchlist failed: {e}")
        raise ToolException(f"Error fetching watchlist: {e}") from e
