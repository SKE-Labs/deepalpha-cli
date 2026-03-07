"""Stock fundamentals tool via Park API."""

import json
import logging
from typing import Literal

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from embient.clients import park_client
from embient.context import get_jwt_token

logger = logging.getLogger(__name__)


class FundamentalsSchema(BaseModel):
    """Arguments for get_fundamentals tool."""

    ticker: str = Field(description="Stock ticker symbol (e.g., 'AAPL', 'MSFT')")
    data_type: Literal[
        "overview",
        "valuation",
        "financials",
        "growth",
        "dividends",
        "analyst_ratings",
        "insider_activity",
        "institutional_holders",
        "earnings_calendar",
        "price_target",
        "recommendations",
        "earning_estimate",
        "revenue_estimate",
        "eps_trend",
        "eps_revisions",
        "growth_estimates",
        "dividends_calendar",
        "splits_calendar",
        "ipo_calendar",
    ] = Field(default="overview", description="Type of fundamental data to retrieve")


@tool(args_schema=FundamentalsSchema)
async def get_fundamentals(
    ticker: str,
    data_type: str = "overview",
) -> str:
    """Fetches fundamental data for a stock ticker via TwelveData.

    Usage:
    - Start with 'overview' for key metrics and valuation
    - Use specific data_type for deep dives
    - Combine with get_financial_news for catalyst research

    Data types:
    - overview: Key company info, P/E, margins, growth (default)
    - valuation: P/E, P/B, EV/EBITDA, P/S ratios
    - financials: Income statement, balance sheet, cash flow
    - growth: Revenue/EPS growth, PEG ratio
    - dividends: Yield, payout ratio, ex-dividend date
    - analyst_ratings: Buy/hold/sell, price targets
    - insider_activity: Recent insider transactions
    - institutional_holders: Major institutional investors
    - earnings_calendar: Next earnings date and estimates
    - price_target: Analyst price targets
    - recommendations: Buy/sell/hold consensus
    - earning_estimate: Analyst earnings forecasts
    - revenue_estimate: Revenue projections
    - eps_trend: EPS trend analysis
    - eps_revisions: Changes to EPS estimates
    - growth_estimates: Growth rate forecasts
    - dividends_calendar: Upcoming dividend dates
    - splits_calendar: Upcoming stock splits
    - ipo_calendar: Upcoming IPOs

    IMPORTANT: Only works for stocks (not crypto). Use get_financial_news for crypto.
    IMPORTANT: Requires authentication. Run 'embient login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'embient login' first.")

    ticker = ticker.upper().strip()
    logger.info(f"Fetching {data_type} fundamentals for {ticker}")

    try:
        result = await park_client.get_fundamentals(token, ticker, data_type)

        if result is None:
            raise ToolException(f"Failed to fetch fundamentals for {ticker}")

        if isinstance(result, dict) and result.get("error"):
            raise ToolException(f"Error fetching fundamentals: {result['error']}")

    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'embient login' to re-authenticate.") from e
        raise ToolException(f"Failed to fetch fundamentals for {ticker}: {error_msg}") from e

    # Format output
    lines = [f"Fundamentals for {ticker} ({data_type}):\n"]

    if isinstance(result, dict):
        for key, value in result.items():
            if value is not None:
                # Format nested dicts/lists as indented JSON
                if isinstance(value, (dict, list)):
                    formatted = json.dumps(value, indent=2, default=str)
                    lines.append(f"**{key}**:")
                    lines.append(formatted)
                else:
                    lines.append(f"- **{key}**: {value}")
    else:
        lines.append(str(result))

    return "\n".join(lines)
