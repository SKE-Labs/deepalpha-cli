"""Park API client for Embient CLI.

Manages interactions with the Park API for:
- Web search (Brave Search)
- Financial news search
- Stock fundamentals (TwelveData)

Usage:
    from embient.clients import park_client

    token = get_cli_token()
    results = await park_client.web_search(token, "AAPL earnings")
"""

import logging
import os

import httpx

from embient.clients.basement import AuthenticationError

logger = logging.getLogger(__name__)

# Default Park API URL
PARK_API_URL = os.environ.get("PARK_API", "https://park.embient.ai")


class ParkClient:
    """Client for the Park API."""

    def __init__(self, base_url: str = PARK_API_URL, timeout: float = 60.0):
        """Initialize the Park client.

        Args:
            base_url: Base URL for the Park API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, token: str) -> dict:
        """Build request headers with authentication."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def web_search(
        self,
        token: str,
        query: str,
        max_results: int = 10,
    ) -> list[dict] | None:
        """Perform a general web search.

        Args:
            token: Authentication token
            query: Search query string
            max_results: Maximum number of results

        Returns:
            List of search result dicts or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/search",
                    json={"query": query, "max_results": max_results},
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'embient login' to re-authenticate.")
                logger.error(f"Failed to web search: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout during web search")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error during web search: {e}")
            return None

    async def get_financial_news(
        self,
        token: str,
        topic: str,
        time_range: str | None = None,
        max_results: int = 10,
        use_trusted_sources: bool = True,
        fetch_content: bool = False,
    ) -> list[dict] | None:
        """Search for financial news.

        Args:
            token: Authentication token
            topic: News search topic (ticker, company, event)
            time_range: Time filter (day, week, month)
            max_results: Maximum number of results
            use_trusted_sources: Restrict to trusted financial sources
            fetch_content: Fetch full article content

        Returns:
            List of news article dicts or None on failure
        """
        try:
            payload: dict = {
                "topic": topic,
                "max_results": max_results,
                "use_trusted_sources": use_trusted_sources,
                "fetch_content": fetch_content,
            }
            if time_range:
                payload["time_range"] = time_range

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/search/news",
                    json=payload,
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", [])
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'embient login' to re-authenticate.")
                logger.error(f"Failed to get financial news: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout during financial news search")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error during financial news search: {e}")
            return None

    async def get_fundamentals(
        self,
        token: str,
        ticker: str,
        data_type: str = "overview",
    ) -> dict | None:
        """Retrieve fundamental data for a stock ticker.

        Args:
            token: Authentication token
            ticker: Stock ticker symbol (e.g., AAPL)
            data_type: Type of data (overview, valuation, financials, etc.)

        Returns:
            Fundamental data dict or None on failure
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/fundamentals/{ticker}",
                    params={"data_type": data_type},
                    headers=self._headers(token),
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", {})
                if response.status_code in (401, 403):
                    raise AuthenticationError("Session expired or invalid. Run 'embient login' to re-authenticate.")
                logger.error(f"Failed to get fundamentals: {response.status_code} - {response.text}")
                return None

        except httpx.TimeoutException:
            logger.error("Timeout during fundamentals fetch")
            return None
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Error during fundamentals fetch: {e}")
            return None


# Singleton instance
park_client = ParkClient()
