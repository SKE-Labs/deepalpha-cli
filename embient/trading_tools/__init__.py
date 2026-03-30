"""Trading tools for Embient CLI.

All tools use the Basement API for data access.
"""

from embient.trading_tools.market_data import (
    generate_chart,
    get_candles_around_date,
    get_indicator,
    get_latest_candle,
)
from embient.trading_tools.memory import (
    create_memory,
    delete_memory,
    list_memories,
    update_memory,
)
from embient.trading_tools.research import (
    get_economics_calendar,
    get_financial_news,
    get_fundamentals,
    get_user_watchlist,
    web_search,
)
from embient.trading_tools.signals import (
    calculate_position_size,
    cancel_signal,
    close_position,
    create_trading_insight,
    get_portfolio_summary,
    get_user_trading_insights,
    send_notification,
    update_trading_insight,
)

__all__ = [
    # Market Data
    "generate_chart",
    "get_latest_candle",
    "get_candles_around_date",
    "get_indicator",
    # Research
    "web_search",
    "get_financial_news",
    "get_fundamentals",
    "get_economics_calendar",
    "get_user_watchlist",
    # Signals
    "get_user_trading_insights",
    "create_trading_insight",
    "update_trading_insight",
    "calculate_position_size",
    # Position Management
    "close_position",
    "cancel_signal",
    "send_notification",
    "get_portfolio_summary",
    # Memory
    "list_memories",
    "create_memory",
    "update_memory",
    "delete_memory",
]
