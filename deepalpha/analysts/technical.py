"""Technical analyst subagent definition.

A single technical_analyst that performs comprehensive multi-timeframe analysis
(macro, swing, scalp) in one pass.
"""

from deepanalysts import SubAgent
from langchain_core.language_models import BaseChatModel

from deepalpha.trading_tools import (
    analyze_chart,
    get_candles_around_date,
    get_indicator,
    get_latest_candle,
)
from deepalpha.utils.prompt_loader import load_prompt

_TECHNICAL_TOOLS = [
    analyze_chart,
    get_latest_candle,
    get_indicator,
    get_candles_around_date,
]

TECHNICAL_ANALYST_PROMPT = load_prompt("analysts/technical_analyst.md")


def get_technical_analyst(model: BaseChatModel) -> SubAgent:
    """Get technical analyst subagent.

    Performs comprehensive multi-timeframe analysis (macro, swing, scalp)
    in a single pass.
    """
    return {
        "name": "technical_analyst",
        "description": (
            "Technical analyst for comprehensive multi-timeframe chart analysis. "
            "Analyzes macro (1d), swing (1h), and scalp (15m) in a single top-down analysis."
        ),
        "system_prompt": TECHNICAL_ANALYST_PROMPT,
        "tools": _TECHNICAL_TOOLS,
        "model": model,
    }
