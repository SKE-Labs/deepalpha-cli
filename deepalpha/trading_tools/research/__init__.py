"""Research tools for fundamental analysis and market research."""

from deepalpha.trading_tools.research.economics import get_economics_calendar
from deepalpha.trading_tools.research.fundamentals import get_fundamentals
from deepalpha.trading_tools.research.news import get_financial_news
from deepalpha.trading_tools.research.watchlist import get_user_watchlist
from deepalpha.trading_tools.research.web_search import web_search

__all__ = [
    "web_search",
    "get_financial_news",
    "get_fundamentals",
    "get_economics_calendar",
    "get_user_watchlist",
]
