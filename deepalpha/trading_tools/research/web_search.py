"""Web search tool via Park API."""

import logging

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import park_client
from deepalpha.context import get_jwt_token

logger = logging.getLogger(__name__)


class WebSearchSchema(BaseModel):
    """Arguments for web_search tool."""

    query: str = Field(description="Search query string")
    max_results: int = Field(default=5, description="Maximum number of results (1-20)")


@tool(args_schema=WebSearchSchema)
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information and documentation.

    Usage:
    - Use for general web search queries
    - Returns titles, links, and snippets from search results
    - Use get_financial_news for finance-specific news instead

    IMPORTANT: After using this tool:
    1. Read through the results
    2. Extract relevant information that answers the user's question
    3. Synthesize into a clear, natural language response
    4. Cite sources by mentioning page titles or URLs

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    logger.info(f"Performing web search: {query}")

    try:
        results = await park_client.web_search(token, query, max_results)

        if results is None:
            raise ToolException(f"Web search failed for query: {query}")

        if not results:
            return f"No results found for: {query}"

    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        raise ToolException(f"Web search failed: {error_msg}") from e

    # Format results
    lines = [f"Web search results for: {query}\n"]
    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        link = result.get("link", "")
        snippet = result.get("snippet", "No description")
        lines.append(f"{i}. **{title}**")
        lines.append(f"   {link}")
        lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines)
