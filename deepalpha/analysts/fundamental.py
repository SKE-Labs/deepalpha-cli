"""Fundamental analyst subagent definition."""

from deepanalysts import SubAgent
from langchain_core.language_models import BaseChatModel

from deepalpha.trading_tools.research import (
    get_economics_calendar,
    get_financial_news,
    get_fundamentals,
)
from deepalpha.utils.prompt_loader import load_prompt

FUNDAMENTAL_ANALYST_PROMPT = load_prompt("analysts/fundamental_analyst.md")


def get_fundamental_analyst(model: BaseChatModel) -> SubAgent:
    """Get fundamental analyst subagent definition."""
    return {
        "name": "fundamental_analyst",
        "description": (
            "Fundamental analysis expert: financial statements, valuation ratios, "
            "earnings, dividends, analyst ratings, news, and market events. "
            "Use for researching fundamentals, financial health, and investment thesis."
        ),
        "system_prompt": FUNDAMENTAL_ANALYST_PROMPT,
        "tools": [get_financial_news, get_fundamentals, get_economics_calendar],
        "model": model,
    }
