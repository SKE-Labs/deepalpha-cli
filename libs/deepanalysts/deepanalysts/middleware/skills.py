"""Skills middleware for loading and exposing agent skills to the system prompt.

This module implements Anthropic's agent skills pattern with progressive disclosure,
loading skills from backend storage via configurable sources.

## Architecture

Skills are loaded from one or more **sources** - paths in a backend where skills are
organized. Sources are loaded in order, with later sources overriding earlier ones
when skills have the same name (last one wins). This enables layering: base -> user
-> project -> team skills.

## Skill Structure

Each skill is a directory containing a SKILL.md file with YAML frontmatter:

```
/skills/user/web-research/
├── SKILL.md          # Required: YAML frontmatter + markdown instructions
└── helper.py         # Optional: supporting files
```

SKILL.md format:
```markdown
---
name: web-research
description: Structured approach to conducting thorough web research
license: MIT
---

# Web Research Skill

## When to Use
- User asks you to research a topic
...
```

## Skill Metadata (SkillMetadata)

Parsed from YAML frontmatter per Agent Skills specification:
- `name`: Skill identifier (max 64 chars, lowercase alphanumeric and hyphens)
- `description`: What the skill does (max 1024 chars)
- `path`: Backend path to the SKILL.md file
- Optional: `license`, `compatibility`, `metadata`, `allowed_tools`
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Annotated, NotRequired, Protocol, TypedDict

import yaml
from langchain.agents.middleware.types import PrivateStateAttr

if TYPE_CHECKING:
    from deepanalysts.backends.protocol import (
        BACKEND_TYPES,
        BackendProtocol,
    )

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime

from deepanalysts.middleware._utils import append_to_system_message

logger = logging.getLogger(__name__)

# Security: Maximum size for SKILL.md files to prevent DoS attacks (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024

# Agent Skills specification constraints (https://agentskills.io/specification)
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 1024


class SkillMetadata(TypedDict):
    """Metadata for a skill per Agent Skills specification (https://agentskills.io/specification)."""

    name: str
    """Skill identifier (max 64 chars, lowercase alphanumeric and hyphens)."""

    description: str
    """What the skill does (max 1024 chars)."""

    path: str
    """Path to the SKILL.md file."""

    license: str | None
    """License name or reference to bundled license file."""

    compatibility: str | None
    """Environment requirements (max 500 chars)."""

    metadata: dict[str, str]
    """Arbitrary key-value mapping for additional metadata."""

    allowed_tools: list[str]
    """Space-delimited list of pre-approved tools. (Experimental)"""


class SkillsLoaderProtocol(Protocol):
    """Protocol for skills loaders."""

    async def load_skills(
        self,
        agent_name: str = "orchestrator",
        user_id: str | None = None,
    ) -> list[SkillMetadata]:
        """Load skills filtered for specific agent."""
        ...


class SkillsState(AgentState):
    """State for the skills middleware."""

    skills_metadata: NotRequired[Annotated[list[SkillMetadata], PrivateStateAttr]]
    """List of loaded skill metadata from all configured sources."""


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""

    skills_metadata: list[SkillMetadata]
    """List of loaded skill metadata to merge into state."""


def _validate_skill_name(name: str, directory_name: str) -> tuple[bool, str]:
    """Validate skill name per Agent Skills specification.

    Requirements per spec:
    - Max 64 characters
    - Lowercase alphanumeric and hyphens only (a-z, 0-9, -)
    - Cannot start or end with hyphen
    - No consecutive hyphens
    - Must match parent directory name

    Args:
        name: Skill name from YAML frontmatter
        directory_name: Parent directory name

    Returns:
        (is_valid, error_message) tuple. Error message is empty if valid.
    """
    if not name:
        return False, "name is required"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return False, "name exceeds 64 characters"
    # Pattern: lowercase alphanumeric, single hyphens between segments, no start/end hyphen
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name):
        return False, "name must be lowercase alphanumeric with single hyphens only"
    if name != directory_name:
        return False, f"name '{name}' must match directory name '{directory_name}'"
    return True, ""


def _parse_skill_metadata(
    content: str,
    skill_path: str,
    directory_name: str,
) -> SkillMetadata | None:
    """Parse YAML frontmatter from SKILL.md content.

    Extracts metadata per Agent Skills specification from YAML frontmatter delimited
    by --- markers at the start of the content.

    Args:
        content: Content of the SKILL.md file
        skill_path: Path to the SKILL.md file (for error messages and metadata)
        directory_name: Name of the parent directory containing the skill

    Returns:
        SkillMetadata if parsing succeeds, None if parsing fails or validation errors occur
    """
    if len(content) > MAX_SKILL_FILE_SIZE:
        logger.warning("Skipping %s: content too large (%d bytes)", skill_path, len(content))
        return None

    # Match YAML frontmatter between --- delimiters
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if not match:
        logger.warning("Skipping %s: no valid YAML frontmatter found", skill_path)
        return None

    frontmatter_str = match.group(1)

    # Parse YAML using safe_load for proper nested structure support
    try:
        frontmatter_data = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", skill_path, e)
        return None

    if not isinstance(frontmatter_data, dict):
        logger.warning("Skipping %s: frontmatter is not a mapping", skill_path)
        return None

    # Validate required fields
    name = frontmatter_data.get("name")
    description = frontmatter_data.get("description")

    if not name or not description:
        logger.warning("Skipping %s: missing required 'name' or 'description'", skill_path)
        return None

    # Validate name format per spec (warn but continue loading for backwards compatibility)
    is_valid, error = _validate_skill_name(str(name), directory_name)
    if not is_valid:
        logger.warning(
            "Skill '%s' in %s does not follow Agent Skills specification: %s. Consider renaming for spec compliance.",
            name,
            skill_path,
            error,
        )

    # Validate description length per spec (max 1024 chars)
    description_str = str(description).strip()
    if len(description_str) > MAX_SKILL_DESCRIPTION_LENGTH:
        logger.warning(
            "Description exceeds %d characters in %s, truncating",
            MAX_SKILL_DESCRIPTION_LENGTH,
            skill_path,
        )
        description_str = description_str[:MAX_SKILL_DESCRIPTION_LENGTH]

    if frontmatter_data.get("allowed-tools"):
        allowed_tools = frontmatter_data.get("allowed-tools").split(" ")
    else:
        allowed_tools = []

    return SkillMetadata(
        name=str(name),
        description=description_str,
        path=skill_path,
        metadata=frontmatter_data.get("metadata", {}),
        license=frontmatter_data.get("license", "").strip() or None,
        compatibility=frontmatter_data.get("compatibility", "").strip() or None,
        allowed_tools=allowed_tools,
    )


def _list_skills(backend: BackendProtocol, source_path: str) -> list[SkillMetadata]:
    """List all skills from a backend source.

    Scans backend for subdirectories containing SKILL.md files, downloads their content,
    parses YAML frontmatter, and returns skill metadata.

    Expected structure:
        source_path/
        ├── skill-name/
        │   ├── SKILL.md        # Required
        │   └── helper.py       # Optional

    Args:
        backend: Backend instance to use for file operations
        source_path: Path to the skills directory in the backend

    Returns:
        List of skill metadata from successfully parsed SKILL.md files
    """
    base_path = source_path

    skills: list[SkillMetadata] = []
    items = backend.ls_info(base_path)
    # Find all skill directories (directories containing SKILL.md)
    skill_dirs = []
    for item in items:
        if not item.get("is_dir"):
            continue
        skill_dirs.append(item["path"])

    if not skill_dirs:
        return []

    # For each skill directory, check if SKILL.md exists and download it
    skill_md_paths = []
    for skill_dir_path in skill_dirs:
        # Construct SKILL.md path using PurePosixPath for safe, standardized path operations
        skill_dir = PurePosixPath(skill_dir_path)
        skill_md_path = str(skill_dir / "SKILL.md")
        skill_md_paths.append((skill_dir_path, skill_md_path))

    paths_to_download = [skill_md_path for _, skill_md_path in skill_md_paths]
    responses = backend.download_files(paths_to_download)

    # Parse each downloaded SKILL.md
    for (skill_dir_path, skill_md_path), response in zip(skill_md_paths, responses, strict=True):
        if response.error:
            # Skill doesn't have a SKILL.md, skip it
            continue

        if response.content is None:
            logger.warning("Downloaded skill file %s has no content", skill_md_path)
            continue

        try:
            content = response.content.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning("Error decoding %s: %s", skill_md_path, e)
            continue

        # Extract directory name from path using PurePosixPath
        directory_name = PurePosixPath(skill_dir_path).name

        # Parse metadata
        skill_metadata = _parse_skill_metadata(
            content=content,
            skill_path=skill_md_path,
            directory_name=directory_name,
        )
        if skill_metadata:
            skills.append(skill_metadata)

    return skills


async def _alist_skills(backend: BackendProtocol, source_path: str) -> list[SkillMetadata]:
    """List all skills from a backend source (async version).

    Scans backend for subdirectories containing SKILL.md files, downloads their content,
    parses YAML frontmatter, and returns skill metadata.

    Expected structure:
        source_path/
        ├── skill-name/
        │   ├── SKILL.md        # Required
        │   └── helper.py       # Optional

    Args:
        backend: Backend instance to use for file operations
        source_path: Path to the skills directory in the backend

    Returns:
        List of skill metadata from successfully parsed SKILL.md files
    """
    base_path = source_path

    skills: list[SkillMetadata] = []
    items = await backend.als_info(base_path)
    # Find all skill directories (directories containing SKILL.md)
    skill_dirs = []
    for item in items:
        if not item.get("is_dir"):
            continue
        skill_dirs.append(item["path"])

    if not skill_dirs:
        return []

    # For each skill directory, check if SKILL.md exists and download it
    skill_md_paths = []
    for skill_dir_path in skill_dirs:
        # Construct SKILL.md path using PurePosixPath for safe, standardized path operations
        skill_dir = PurePosixPath(skill_dir_path)
        skill_md_path = str(skill_dir / "SKILL.md")
        skill_md_paths.append((skill_dir_path, skill_md_path))

    paths_to_download = [skill_md_path for _, skill_md_path in skill_md_paths]
    responses = await backend.adownload_files(paths_to_download)

    # Parse each downloaded SKILL.md
    for (skill_dir_path, skill_md_path), response in zip(skill_md_paths, responses, strict=True):
        if response.error:
            # Skill doesn't have a SKILL.md, skip it
            continue

        if response.content is None:
            logger.warning("Downloaded skill file %s has no content", skill_md_path)
            continue

        try:
            content = response.content.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning("Error decoding %s: %s", skill_md_path, e)
            continue

        # Extract directory name from path using PurePosixPath
        directory_name = PurePosixPath(skill_dir_path).name

        # Parse metadata
        skill_metadata = _parse_skill_metadata(
            content=content,
            skill_path=skill_md_path,
            directory_name=directory_name,
        )
        if skill_metadata:
            skills.append(skill_metadata)

    return skills


SKILLS_SYSTEM_PROMPT = """
# Available Skills

The following skills are specialized workflows available to you. When the user's request matches a skill's domain, read the SKILL.md for full instructions before proceeding. Each skill is a directory that may contain helper scripts, images, and other supporting files — use absolute paths when referencing them.

{skills_list}
"""


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills to the system prompt.

    Loads skills from API or backend sources and injects them into the system prompt
    using progressive disclosure (metadata first, full content on demand).

    Two loading modes are supported:
    1. **Loader mode**: Use a loader to fetch from API with agent filtering
    2. **Backend mode**: Use a Backend + sources to load from file paths

    Loader mode takes precedence when configured.

    Example:
        ```python
        # Loader mode (API)
        loader = BasementSkillsLoader()
        middleware = SkillsMiddleware(loader=loader, agent_name="technical_analyst")

        # Backend mode (file-based)
        middleware = SkillsMiddleware(
            backend=lambda rt: StoreBackend(rt),
            sources=["/skills/user/", "/skills/project/"],
        )
        ```

    Args:
        backend: Backend instance for file operations. Optional if using loader.
        sources: List of skill source paths. Optional if using loader.
        loader: Optional loader for API-based loading.
        agent_name: Agent name for skill filtering (default: "orchestrator").
    """

    state_schema = SkillsState

    def __init__(
        self,
        *,
        backend: BACKEND_TYPES | None = None,
        sources: list[str] | None = None,
        loader: SkillsLoaderProtocol | None = None,
        agent_name: str = "orchestrator",
    ) -> None:
        """Initialize the skills middleware.

        Args:
            backend: Backend instance or factory function that takes runtime and returns a backend.
                     Use a factory for StateBackend: `lambda rt: StateBackend(rt)`
                     Optional if using loader mode.
            sources: List of skill source paths (e.g., ["/skills/user/", "/skills/project/"]).
                     Optional if using loader mode.
            loader: Optional loader for API-based skill loading.
                    When provided, takes precedence over backend/sources.
            agent_name: Agent name for filtering skills by target_agents (default: "orchestrator").
        """
        self._backend = backend
        self.sources = sources or []
        self.loader = loader
        self.agent_name = agent_name
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

    def _get_backend(self, state: SkillsState, runtime: Runtime, config: RunnableConfig) -> BackendProtocol:
        """Resolve backend from instance or factory.

        Args:
            state: Current agent state.
            runtime: Runtime context for factory functions.
            config: Runnable config to pass to backend factory.

        Returns:
            Resolved backend instance
        """
        if callable(self._backend):
            # Construct an artificial tool runtime to resolve backend factory
            tool_runtime = ToolRuntime(
                state=state,
                context=runtime.context,
                stream_writer=runtime.stream_writer,
                store=runtime.store,
                config=config,
                tool_call_id=None,
            )
            backend = self._backend(tool_runtime)
            if backend is None:
                raise AssertionError("SkillsMiddleware requires a valid backend instance")
            return backend

        return self._backend

    def _format_skills_locations(self) -> str:
        """Format skills locations for display in system prompt."""
        locations = []
        for i, source_path in enumerate(self.sources):
            name = PurePosixPath(source_path.rstrip("/")).name.capitalize()
            suffix = " (higher priority)" if i == len(self.sources) - 1 else ""
            locations.append(f"**{name} Skills**: `{source_path}`{suffix}")
        return "\n".join(locations)

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            return ""

        lines = []
        for skill in skills:
            skill_dir = str(PurePosixPath(skill["path"]).parent)
            lines.append(f"- **{skill['name']}**: {skill['description']}")
            if skill.get("allowed_tools"):
                lines.append(f"  -> Allowed tools: {', '.join(skill['allowed_tools'])}")
            lines.append(f"  -> `{skill_dir}/` (read SKILL.md for full instructions)")

        return "\n".join(lines)

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject skills documentation into a model request's system prompt.

        Uses append_to_system_message to properly handle content blocks
        instead of just string concatenation. Skips injection entirely
        when no skills are available.

        Args:
            request: Model request to modify

        Returns:
            New model request with skills documentation injected into system prompt
        """
        skills_metadata = request.state.get("skills_metadata", [])
        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        if not skills_list:
            return request

        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        system_message = append_to_system_message(request.system_message, skills_section)
        return request.override(system_message=system_message)

    def before_agent(self, state: SkillsState, runtime: Runtime, config: RunnableConfig) -> SkillsStateUpdate | None:
        """Load skills metadata before agent execution (synchronous).

        Runs before each agent interaction to discover available skills from all
        configured sources. Re-loads on every call to capture any changes.

        Skills are loaded in source order with later sources overriding
        earlier ones if they contain skills with the same name (last one wins).

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            State update with skills_metadata populated, or None if already present
        """
        # Skip if skills_metadata is already present in state (even if empty)
        if "skills_metadata" in state:
            return None

        # Resolve backend (supports both direct instances and factory functions)
        if not self._backend or not self.sources:
            return SkillsStateUpdate(skills_metadata=[])

        backend = self._get_backend(state, runtime, config)
        all_skills: dict[str, SkillMetadata] = {}

        # Load skills from each source in order
        # Later sources override earlier ones (last one wins)
        for source_path in self.sources:
            source_skills = _list_skills(backend, source_path)
            for skill in source_skills:
                all_skills[skill["name"]] = skill

        skills = list(all_skills.values())
        return SkillsStateUpdate(skills_metadata=skills)

    async def abefore_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:
        """Load skills metadata before agent execution (async).

        Loads skills from API (if loader configured) and/or from backend sources.
        When both are configured, results are merged with API-loaded skills taking
        precedence (backend skills are added only if not already loaded from API).

        Only loads if not already present in state.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            State update with skills_metadata populated, or None if already present
        """
        # Skip if skills_metadata is already present in state (even if empty)
        if "skills_metadata" in state:
            return None

        skills_metadata: list[SkillMetadata] = []

        # Load from API loader if configured
        if self.loader:
            # Get user_id for store namespace (multi-tenant isolation)
            user_id = config.get("configurable", {}).get("user_id")
            skills_metadata = await self.loader.load_skills(agent_name=self.agent_name, user_id=user_id)
            if skills_metadata:
                logger.debug(f"Loaded {len(skills_metadata)} skills from API for agent '{self.agent_name}'")

        # Also load from backend/sources (for built-in skills and file-based skills)
        if self._backend and self.sources:
            backend = self._get_backend(state, runtime, config)
            all_backend_skills: dict[str, SkillMetadata] = {}

            for source_path in self.sources:
                source_skills = await _alist_skills(backend, source_path)
                for skill in source_skills:
                    all_backend_skills[skill["name"]] = skill

            # API-loaded skills take precedence — don't override them
            loaded_names = {s["name"] for s in skills_metadata}
            for skill in all_backend_skills.values():
                if skill["name"] not in loaded_names:
                    skills_metadata.append(skill)

        return SkillsStateUpdate(skills_metadata=skills_metadata)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject skills documentation into the system prompt.

        Args:
            request: Model request being processed
            handler: Handler function to call with modified request

        Returns:
            Model response from handler
        """
        modified_request = self.modify_request(request)
        return handler(modified_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject skills documentation into the system prompt (async version).

        Args:
            request: Model request being processed
            handler: Async handler function to call with modified request

        Returns:
            Model response from handler
        """
        modified_request = self.modify_request(request)
        return await handler(modified_request)


__all__ = ["SkillMetadata", "SkillsMiddleware", "SkillsLoaderProtocol", "_list_skills"]
