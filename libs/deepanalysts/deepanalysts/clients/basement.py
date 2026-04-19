"""Basement API client for skills and memories.

This provides a generic client interface that can be configured for either
cloud (park) or local (deepalpha-cli) usage.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

# Default API endpoint (can be overridden via BASEMENT_API env var)
DEFAULT_BASEMENT_API = os.environ.get("BASEMENT_API", "https://basement.deepalpha.mn")


@runtime_checkable
class TokenProvider(Protocol):
    """Protocol for getting JWT tokens."""

    def get_token(self) -> str | None:
        """Get the current JWT token."""
        ...


class BasementClient:
    """Generic Basement API client.

    Can be initialized with a base URL and token provider for flexibility.

    Example:
        ```python
        # With explicit token
        client = BasementClient(token="jwt-token")

        # With token provider function
        client = BasementClient(token_provider=lambda: get_jwt_from_context())
        ```
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        token_provider: TokenProvider | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: API base URL (defaults to basement.deepalpha.mn)
            token: Static JWT token to use
            token_provider: Callable that returns JWT token dynamically
            timeout: Request timeout in seconds
        """
        self.base_url = (base_url or DEFAULT_BASEMENT_API).rstrip("/")
        self._token = token
        self._token_provider = token_provider
        self._timeout = timeout

    def _get_token(self) -> str | None:
        """Get JWT token from static value or provider."""
        if self._token:
            return self._token
        if self._token_provider:
            return self._token_provider.get_token()
        return None

    def _get_headers(self, token: str | None = None) -> dict[str, str]:
        """Build request headers with authentication."""
        jwt = token or self._get_token()
        headers = {"Content-Type": "application/json"}
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        return headers

    async def get_active_memories(self, token: str | None = None) -> list[dict[str, Any]]:
        """Fetch active memories for user.

        Args:
            token: Optional JWT token (uses configured token if not provided)

        Returns:
            List of memory dicts with 'name' and 'content' fields.
        """
        url = f"{self.base_url}/api/v1/memories/active"
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    return data.get("response", data.get("memories", []))
                return data
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch memories: {e}")
            return []

    async def get_active_skills(self, token: str | None = None) -> list[dict[str, Any]]:
        """Fetch active skills for user.

        Args:
            token: Optional JWT token (uses configured token if not provided)

        Returns:
            List of skill dicts with 'name', 'description', 'path', 'content',
            'target_agents', and 'assets' fields.
        """
        url = f"{self.base_url}/api/v1/skills/active"
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                # API returns {"response": [...]} format
                if isinstance(data, dict):
                    return data.get("response", data.get("skills", []))
                return data
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch skills: {e}")
            return []

    async def sync_memory(
        self,
        name: str,
        content: str,
        token: str | None = None,
    ) -> bool:
        """Sync a memory to the Basement API.

        Args:
            name: Memory name/identifier
            content: Memory content
            token: Optional JWT token

        Returns:
            True if sync successful, False otherwise.
        """
        url = f"{self.base_url}/api/v1/memories"
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={"name": name, "content": content},
                )
                response.raise_for_status()
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to sync memory: {e}")
            return False

    async def sync_skill(
        self,
        name: str,
        description: str,
        content: str,
        path: str | None = None,
        token: str | None = None,
    ) -> bool:
        """Sync a skill to the Basement API.

        Args:
            name: Skill name
            description: Skill description
            content: SKILL.md content
            path: Optional path for the skill
            token: Optional JWT token

        Returns:
            True if sync successful, False otherwise.
        """
        url = f"{self.base_url}/api/v1/skills"
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "name": name,
                        "description": description,
                        "content": content,
                        "path": path,
                    },
                )
                response.raise_for_status()
                return True
        except httpx.HTTPError as e:
            logger.error(f"Failed to sync skill: {e}")
            return False


# Default client instance (can be configured at startup)
basement_client = BasementClient()
