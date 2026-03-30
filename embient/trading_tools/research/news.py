"""Financial news search tool via Park API."""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from embient.clients import park_client
from embient.context import get_jwt_token

logger = logging.getLogger(__name__)


class FinancialNewsSchema(BaseModel):
    """Arguments for get_financial_news tool."""

    topic: str = Field(description="News search topic (ticker, company name, or financial event)")
    time_range: str = Field(default="", description="Time filter for recency: 'day', 'week', 'month', or empty for all")
    max_results: int = Field(default=10, description="Maximum number of results")
    use_trusted_sources: bool = Field(default=True, description="Restrict to trusted financial sources")
    fetch_content: bool = Field(default=False, description="Fetch full article content (slower)")


@tool(args_schema=FinancialNewsSchema)
async def get_financial_news(
    topic: str,
    time_range: str = "",
    max_results: int = 10,
    use_trusted_sources: bool = True,
    fetch_content: bool = False,
) -> str:
    """Fetches financial news from trusted sources via Google Search.

    Usage:
    - Search by ticker, company name, or financial event
    - Use time_range for recency filtering (day, week, month)
    - Set fetch_content=True to get full article text (slower)

    Trusted sources (when use_trusted_sources=True):
    Reuters, Bloomberg, WSJ, CNBC, Yahoo Finance, MarketWatch

    IMPORTANT:
    - Works for both stocks and crypto
    - Use get_fundamentals for stock financial data (not news)
    - Combine with technical analysis for catalyst identification

    IMPORTANT: Requires authentication. Run 'embient login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'embient login' first.")

    logger.info(f"Fetching financial news for: {topic}")

    try:
        results = await park_client.get_financial_news(
            token, topic, time_range or None, max_results, use_trusted_sources, fetch_content
        )

        if results is None:
            raise ToolException(f"Financial news search failed for: {topic}")

        if not results:
            return f"No financial news found for: {topic}"

    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'embient login' to re-authenticate.") from e
        raise ToolException(f"Financial news search failed: {error_msg}") from e

    # Format results
    lines = [f"Financial news for: {topic}\n"]
    for i, article in enumerate(results, 1):
        title = article.get("title", "No title")
        link = article.get("link", "")
        snippet = article.get("snippet", "No description")
        source = article.get("source", "general")
        source_tag = " [trusted]" if source == "trusted" else ""

        lines.append(f"{i}. **{title}**{source_tag}")
        lines.append(f"   {link}")
        lines.append(f"   {snippet}")

        content = article.get("content", "")
        if content:
            # Truncate long content
            preview = content[:500] + "..." if len(content) > 500 else content
            lines.append(f"   Content: {preview}")

        lines.append("")

    return "\n".join(lines)
