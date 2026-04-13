"""Basement API loaders for skills and memory.

Provides loader classes that fetch skills and memories from the Basement API
instead of file-based backends. These loaders can be passed to the
MemoryMiddleware and SkillsMiddleware for API-based loading.

Note: These loaders require a token provider to be configured. The token
provider can be a static token, a callable, or a context variable getter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from deepanalysts.clients.basement import BasementClient, basement_client
from deepanalysts.middleware.skills import SkillMetadata

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenProvider(Protocol):
    """Protocol for getting JWT tokens."""

    def __call__(self) -> str | None:
        """Get the current JWT token."""
        ...


class BasementMemoryLoader:
    """Loads user memories from Basement API.

    Fetches active memories via GET /api/v1/memories/active and returns them
    in the format expected by MemoryMiddleware.

    Example:
        ```python
        # With token provider function
        loader = BasementMemoryLoader(token_provider=get_jwt_from_context)
        middleware = MemoryMiddleware(loader=loader)

        # With client that has token configured
        client = BasementClient(token="jwt-token")
        loader = BasementMemoryLoader(client=client)
        ```
    """

    def __init__(
        self,
        *,
        client: BasementClient | None = None,
        token_provider: Callable[[], str | None] | None = None,
    ) -> None:
        """Initialize the memory loader.

        Args:
            client: BasementClient instance to use. Defaults to global basement_client.
            token_provider: Callable that returns JWT token. Used when calling API.
        """
        self._client = client or basement_client
        self._token_provider = token_provider
        self._cache: dict[str, dict[str, str]] = {}

    def _get_token(self) -> str | None:
        """Get JWT token from provider."""
        if self._token_provider:
            return self._token_provider()
        return None

    async def load_memories(self) -> dict[str, str]:
        """Load active memories for user.

        Returns:
            Dict mapping memory name to content, compatible with MemoryMiddleware.
        """
        jwt_token = self._get_token()
        if not jwt_token:
            logger.warning("No JWT token available, skipping memory loading")
            return {}

        # Check cache (keyed by JWT to support multiple users)
        if jwt_token in self._cache:
            return self._cache[jwt_token]

        memories = await self._client.get_active_memories(jwt_token)

        # Convert to dict format expected by MemoryMiddleware
        contents: dict[str, str] = {}
        for mem in memories:
            name = mem.get("name", "")
            content = mem.get("content", "")
            if name and content:
                contents[name] = content

        self._cache[jwt_token] = contents
        logger.debug(f"Loaded {len(contents)} memories from Basement API")
        return contents

    def clear_cache(self) -> None:
        """Clear the memory cache."""
        self._cache.clear()


class BasementSkillsLoader:
    """Loads user skills from Basement API with agent filtering.

    Fetches active skills via GET /api/v1/skills/active and filters them
    based on target_agents to ensure each subagent only sees relevant skills.

    Optionally writes skill content to a LangGraph Store so the `read_file` tool
    can access skill files during conversations.

    Filtering logic:
    - Empty target_agents = load for all agents
    - "*" in target_agents = load for all agents
    - Otherwise, agent_name must be in target_agents

    Example:
        ```python
        loader = BasementSkillsLoader(
            token_provider=get_jwt_from_context,
            store=app.state.store,
        )

        # For orchestrator (all skills without specific targeting)
        orchestrator_skills = await loader.load_skills(user_id="user-123", agent_name="orchestrator")

        # For technical analyst (only skills targeting technical_analyst)
        ta_skills = await loader.load_skills(user_id="user-123", agent_name="technical_analyst")
        ```
    """

    def __init__(
        self,
        *,
        client: BasementClient | None = None,
        token_provider: Callable[[], str | None] | None = None,
        store: BaseStore | None = None,
        store_namespace: str = "filesystem",
        supabase_url: str | None = None,
        built_in_dirs: list[str] | None = None,
    ) -> None:
        """Initialize loader with optional store for caching.

        Args:
            client: BasementClient instance to use. Defaults to global basement_client.
            token_provider: Callable that returns JWT token.
            store: LangGraph Store instance for writing skill content.
                   If None, skills won't be available via read_file.
            store_namespace: Second element of the store namespace tuple.
                   Skills are written to ``(user_id, store_namespace)``.
                   Defaults to ``"filesystem"`` for backward compatibility.
            supabase_url: Supabase URL for asset downloads. Required if store is provided.
            built_in_dirs: Directories containing built-in skills (SKILL.md files).
                          These are loaded from the filesystem and merged with API skills.
        """
        self._client = client or basement_client
        self._token_provider = token_provider
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._store = store
        self._store_namespace = store_namespace
        self._supabase_url = supabase_url
        self._written_skills: set[str] = set()  # Track which skills already written
        self._built_in_dirs = built_in_dirs or []
        self._built_in_cache: list[dict[str, Any]] | None = None

    def _get_token(self) -> str | None:
        """Get JWT token from provider."""
        if self._token_provider:
            return self._token_provider()
        return None

    def _load_built_in_skills(self) -> list[dict[str, Any]]:
        """Load built-in skills from filesystem directories.

        Scans each built-in directory for subdirectories containing SKILL.md,
        parses YAML frontmatter, and returns skill dicts in the same format
        as the Basement API response.

        Returns:
            List of skill dicts with name, description, content, path fields.
        """
        if self._built_in_cache is not None:
            return self._built_in_cache

        skills: list[dict[str, Any]] = []
        frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

        for built_in_dir in self._built_in_dirs:
            dir_path = Path(built_in_dir)
            if not dir_path.is_dir():
                logger.warning(f"Built-in skills directory not found: {built_in_dir}")
                continue

            for skill_dir in sorted(dir_path.iterdir()):
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                try:
                    content = skill_md.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Error reading {skill_md}: {e}")
                    continue

                # Parse YAML frontmatter
                match = frontmatter_pattern.match(content)
                if not match:
                    logger.warning(f"No valid frontmatter in {skill_md}")
                    continue

                import yaml

                try:
                    frontmatter = yaml.safe_load(match.group(1))
                except yaml.YAMLError as e:
                    logger.warning(f"Invalid YAML in {skill_md}: {e}")
                    continue

                if not isinstance(frontmatter, dict):
                    continue

                name = frontmatter.get("name", "")
                description = frontmatter.get("description", "")
                if not name or not description:
                    continue

                skills.append(
                    {
                        "name": name,
                        "description": description,
                        "content": content,
                        "path": f"/skills/{name}",
                        "target_agents": [],  # Built-in skills available to all agents
                        "metadata": frontmatter.get("metadata", {}),
                        "assets": [],
                    }
                )

        self._built_in_cache = skills
        logger.debug(f"Loaded {len(skills)} built-in skills from filesystem")
        return skills

    async def load_skills(
        self,
        agent_name: str = "orchestrator",
        user_id: str | None = None,
    ) -> list[SkillMetadata]:
        """Load skills filtered for specific agent.

        Writes skill content to store for read_file access if store is configured.

        Args:
            agent_name: Agent to filter skills for (e.g., 'technical_analyst').
            user_id: User ID for store namespace (multi-tenant isolation).

        Returns:
            List of SkillMetadata dicts filtered by target_agents.
        """
        jwt_token = self._get_token()
        if not jwt_token:
            logger.warning("No JWT token available, skipping skill loading")
            return []

        # Load from cache or API
        if jwt_token not in self._cache:
            skills = await self._client.get_active_skills(jwt_token)
            self._cache[jwt_token] = skills
            logger.debug(f"Loaded {len(skills)} skills from Basement API")
        else:
            skills = self._cache[jwt_token]
            logger.debug("Using cached skills from Basement API")

        # Merge built-in skills with API skills (API takes precedence)
        built_in = self._load_built_in_skills()
        api_names = {s.get("name") for s in skills}
        all_skills = list(skills)
        for bi_skill in built_in:
            if bi_skill["name"] not in api_names:
                all_skills.append(bi_skill)

        # Write skills to store for read_file access (only on first load per user)
        if self._store and user_id:
            needs_write = any(
                f"{user_id}:{self._get_store_path(skill)}/SKILL.md" not in self._written_skills
                for skill in all_skills
                if skill.get("path")
            )
            if needs_write:
                await self._write_skills_to_store(all_skills, user_id)
        elif not user_id and self._store:
            logger.warning("No user_id provided to load_skills, skipping store write")

        # Filter by target_agents and convert to SkillMetadata
        filtered: list[SkillMetadata] = []
        for skill in all_skills:
            if self._skill_matches_agent(skill, agent_name):
                filtered.append(self._to_skill_metadata(skill))

        logger.debug(f"Filtered {len(filtered)}/{len(all_skills)} skills for agent '{agent_name}'")
        return filtered

    async def _write_skills_to_store(self, skills: list[dict[str, Any]], user_id: str) -> None:
        """Write skill content and assets to Store for read_file access.

        Args:
            skills: List of skill dicts from Basement API.
            user_id: User ID for store namespace.
        """
        import asyncio

        from langgraph.store.base import PutOp

        from deepanalysts.backends.utils import create_file_data

        namespace = (user_id, self._store_namespace)

        # Collect all put operations for batch execution
        put_ops: list[PutOp] = []
        cache_keys_to_add: list[str] = []

        # Collect asset download tasks for parallel execution
        asset_download_tasks: list[tuple[str, str, str, str]] = []

        for skill in skills:
            skill_path = skill.get("path", "")
            content = skill.get("content", "")

            if not skill_path:
                continue

            # Strip /skills/ prefix for store
            store_skill_path = self._get_store_path(skill)

            # Queue SKILL.md write
            if content:
                file_path = store_skill_path.rstrip("/") + "/SKILL.md"
                cache_key = f"{user_id}:{file_path}"

                if cache_key not in self._written_skills:
                    file_data = create_file_data(content)
                    store_value = {
                        "content": file_data["content"],
                        "created_at": file_data["created_at"],
                        "modified_at": file_data["modified_at"],
                    }
                    put_ops.append(PutOp(namespace=namespace, key=file_path, value=store_value))
                    cache_keys_to_add.append(cache_key)

            # Process assets
            assets = skill.get("assets", []) or skill.get("skill_assets", []) or []
            for asset in assets:
                asset_path = asset.get("path", "")
                asset_type = asset.get("type", "")
                storage_path = asset.get("storage_path", "")

                if not asset_path or not storage_path:
                    continue

                full_path = store_skill_path.rstrip("/") + "/" + asset_path.lstrip("/")
                cache_key = f"{user_id}:{full_path}"

                if cache_key in self._written_skills:
                    continue

                # Queue text asset downloads for parallel execution
                if asset_type in ("script", "markdown"):
                    asset_download_tasks.append((full_path, cache_key, storage_path, asset_type))
                # For images, create reference file immediately (no download needed)
                elif asset_type == "image" and self._supabase_url:
                    supabase_url = self._supabase_url.rstrip("/")
                    public_url = f"{supabase_url}/storage/v1/object/public/skill-assets/{storage_path}"
                    ref_content = f"# Image Asset Reference\n\nURL: {public_url}\nType: {asset.get('mime_type', 'image')}\nSize: {asset.get('size_bytes', 0)} bytes"
                    file_data = create_file_data(ref_content)
                    store_value = {
                        "content": file_data["content"],
                        "created_at": file_data["created_at"],
                        "modified_at": file_data["modified_at"],
                    }
                    put_ops.append(
                        PutOp(
                            namespace=namespace,
                            key=full_path + ".ref",
                            value=store_value,
                        )
                    )
                    cache_keys_to_add.append(cache_key)

        # Download text assets in parallel
        if asset_download_tasks:
            download_results = await asyncio.gather(
                *[self._download_asset(task[2]) for task in asset_download_tasks],
                return_exceptions=True,
            )

            for (full_path, cache_key, storage_path, _), result in zip(
                asset_download_tasks, download_results, strict=False
            ):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to download asset {storage_path}: {result}")
                    continue
                if result:
                    file_data = create_file_data(result)
                    store_value = {
                        "content": file_data["content"],
                        "created_at": file_data["created_at"],
                        "modified_at": file_data["modified_at"],
                    }
                    put_ops.append(PutOp(namespace=namespace, key=full_path, value=store_value))
                    cache_keys_to_add.append(cache_key)

        # Execute all writes in a single batch
        if put_ops:
            await self._store.abatch(put_ops)
            # Update cache after successful batch write
            self._written_skills.update(cache_keys_to_add)
            logger.debug(f"Wrote {len(put_ops)} skill files to store for user {user_id}")

    async def _download_asset(self, storage_path: str) -> str | None:
        """Download text asset from Supabase storage.

        Args:
            storage_path: Path in Supabase storage bucket.

        Returns:
            Asset content as string, or None on failure.
        """
        if not self._supabase_url:
            logger.warning("No Supabase URL configured, cannot download asset")
            return None

        import httpx

        try:
            supabase_url = self._supabase_url.rstrip("/")
            url = f"{supabase_url}/storage/v1/object/public/skill-assets/{storage_path}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
                else:
                    logger.warning(f"Failed to download asset: {response.status_code}")
                    return None
        except Exception as e:
            logger.warning(f"Error downloading asset: {e}")
            return None

    def _get_store_path(self, skill: dict[str, Any]) -> str:
        """Get the store path for a skill (without /skills/ prefix).

        Args:
            skill: Skill dict from API.

        Returns:
            Store path for the skill.
        """
        skill_path = skill.get("path", "")
        if skill_path.startswith("/skills/"):
            return skill_path[len("/skills/") - 1 :]  # Keep leading /
        return skill_path

    def _skill_matches_agent(self, skill: dict[str, Any], agent_name: str) -> bool:
        """Check if skill should be loaded for given agent.

        Args:
            skill: Skill dict from API.
            agent_name: Agent name to check against.

        Returns:
            True if skill should be loaded for this agent.
        """
        target_agents = skill.get("target_agents", [])

        # Empty target_agents = load for all agents
        if not target_agents:
            return True

        # Wildcard = load for all agents
        if "*" in target_agents:
            return True

        # Check if agent is in target list
        return agent_name in target_agents

    def _to_skill_metadata(self, skill: dict[str, Any]) -> SkillMetadata:
        """Convert API skill dict to SkillMetadata format.

        Args:
            skill: Skill dict from Basement API.

        Returns:
            SkillMetadata TypedDict compatible with SkillsMiddleware.
        """
        # Extract allowed_tools from metadata if present
        metadata = skill.get("metadata", {}) or {}
        allowed_tools = metadata.get("allowed_tools", [])
        if isinstance(allowed_tools, str):
            allowed_tools = allowed_tools.split(" ") if allowed_tools else []

        # API returns path as skill directory (e.g., "/skills/cup-and-handle").
        # SkillMetadata.path should point to SKILL.md for consistency with
        # file-based loading, so _format_skills_list can derive the directory.
        skill_path = skill.get("path", "")
        if skill_path and not skill_path.endswith("/SKILL.md"):
            skill_path = skill_path.rstrip("/") + "/SKILL.md"

        return SkillMetadata(
            name=skill.get("name", ""),
            description=skill.get("description", ""),
            path=skill_path,
            license=skill.get("license"),
            compatibility=skill.get("compatibility"),
            metadata=metadata,
            allowed_tools=allowed_tools,
        )

    def clear_cache(self) -> None:
        """Clear the skills cache and written tracking."""
        self._cache.clear()
        self._written_skills.clear()
        self._built_in_cache = None


__all__ = ["BasementMemoryLoader", "BasementSkillsLoader"]
