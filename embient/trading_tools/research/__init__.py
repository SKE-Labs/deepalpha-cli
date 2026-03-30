"""Research tools for fundamental analysis and market research."""

from embient.trading_tools.research.economics import get_economics_calendar
from embient.trading_tools.research.fundamentals import get_fundamentals
from embient.trading_tools.research.news import get_financial_news
from embient.trading_tools.research.watchlist import get_user_watchlist
from embient.trading_tools.research.web_search import web_search

__all__ = [
    "web_search",
    "get_financial_news",
    "get_fundamentals",
    "get_economics_calendar",
    "get_user_watchlist",
]
