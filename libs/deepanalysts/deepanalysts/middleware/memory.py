"""Middleware for loading agent memory/context from AGENTS.md files.

This module implements support for the AGENTS.md specification (https://agents.md/),
loading memory/context from configurable sources and injecting into the system prompt.

## Overview

AGENTS.md files provide project-specific context and instructions to help AI agents
work effectively. Unlike skills (which are on-demand workflows), memory is always
loaded and provides persistent context.

## Usage

```python
from deepanalysts.middleware import MemoryMiddleware
from deepanalysts.backends import CompositeBackend

middleware = MemoryMiddleware(
    backend=backend,
    sources=[
        "~/.deepalpha/AGENTS.md",
        "./.deepalpha/AGENTS.md",
    ],
)

agent = create_deep_agent(middleware=[middleware])
```

## Memory Sources

Sources are simply paths to AGENTS.md files that are loaded in order and combined.
Multiple sources are concatenated in order, with all content included.
Later sources appear after earlier ones in the combined prompt.

## File Format

AGENTS.md files are standard Markdown with no required structure.
Common sections include:
- Project overview
- Build/test commands
- Code style guidelines
- Architecture notes
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, NotRequired, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig

from deepanalysts.middleware._utils import append_to_system_message, insert_after_section

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
    PrivateStateAttr,
)
from langchain.tools import ToolRuntime
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class MemoryLoaderProtocol(Protocol):
    """Protocol for memory loaders."""

    async def load_memories(self) -> dict[str, str]:
        """Load memories and return dict mapping name to content."""
        ...


class MemoryState(AgentState):
    """State schema for MemoryMiddleware.

    Attributes:
        memory_contents: Dict mapping source paths to their loaded content.
            Marked as private so it's not included in the final agent state.
    """

    memory_contents: NotRequired[Annotated[dict[str, str], PrivateStateAttr]]


class MemoryStateUpdate(TypedDict):
    """State update for MemoryMiddleware."""

    memory_contents: dict[str, str]


# Default system prompt template for memory
MEMORY_SYSTEM_PROMPT = """
# User Preferences & Instructions

The user's personal preferences and instructions are shown below. They reflect the user's trading style, risk management rules, research methodology, and other guidelines.

IMPORTANT: You MUST follow these instructions exactly as written — they override default behavior. Any specific numbers, ratios, or thresholds (e.g., risk:reward ratios, position sizes, stop loss rules) are strict constraints, not suggestions. Never deviate from them unless the user explicitly asks you to in the current conversation.

{memory_contents}
"""


class MemoryMiddleware(AgentMiddleware):
    """Middleware for loading agent memory from AGENTS.md files or API.

    Loads memory content from configured sources and injects into the system prompt.
    Supports multiple sources that are combined together.

    Two loading modes are supported:
    1. **Loader mode**: Use a loader to fetch from API (e.g., Basement)
    2. **Backend mode**: Use a Backend + sources to load from file paths

    Loader mode takes precedence when configured.

    Args:
        backend: Backend instance or factory function for file operations.
        sources: List of memory file paths to load.
        loader: Optional loader for API-based loading.
    """

    state_schema = MemoryState

    def __init__(
        self,
        *,
        backend: BACKEND_TYPES | None = None,
        sources: list[str] | None = None,
        loader: MemoryLoaderProtocol | None = None,
        insert_after: str | None = None,
    ) -> None:
        """Initialize the memory middleware.

        Args:
            backend: Backend instance or factory function that takes runtime
                     and returns a backend. Use a factory for StateBackend.
                     Optional if using loader mode.
            sources: List of memory file paths to load (e.g., ["~/.deepalpha/AGENTS.md",
                     "./.deepalpha/AGENTS.md"]). Display names are automatically derived
                     from the paths. Sources are loaded in order. Optional if using loader.
            loader: Optional loader for API-based memory loading.
                    When provided, takes precedence over backend/sources.
            insert_after: If set, insert the memory section after this named prompt
                         section instead of appending at the end.  Section names are
                         tracked via ``additional_kwargs["_prompt_sections"]`` on the
                         ``SystemMessage``.  Falls back to append if not found.
        """
        self._backend = backend
        self.sources = sources or []
        self.loader = loader
        self.insert_after = insert_after
        self.system_prompt_template = MEMORY_SYSTEM_PROMPT

    def _get_backend(self, state: MemoryState, runtime: Runtime, config: RunnableConfig) -> BackendProtocol:
        """Resolve backend from instance or factory.

        Args:
            state: Current agent state.
            runtime: Runtime context for factory functions.
            config: Runnable config to pass to backend factory.

        Returns:
            Resolved backend instance.
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
            return self._backend(tool_runtime)
        return self._backend

    def _format_memory_locations(self, contents: dict[str, str] | None = None) -> str:
        """Format memory source locations for display.

        Args:
            contents: Optional dict of loaded contents (used for loader mode).

        Returns:
            Formatted string listing memory sources.
        """
        # When using loader mode, show memory names from contents
        # When using backend mode, show configured source paths
        sources = self.sources if self.sources else list((contents or {}).keys())

        if not sources:
            return "**Memory Sources:** None configured"

        lines = ["**Memory Sources:**"]
        for source in sources:
            lines.append(f"- `{source}`")
        return "\n".join(lines)

    def _format_memory_contents(self, contents: dict[str, str]) -> str:
        """Format loaded memory contents for injection into prompt.

        Each source is labeled with its name/path, similar to how project
        instructions are presented in development tools.

        Args:
            contents: Dict mapping source paths/names to content.

        Returns:
            Formatted string with labeled memory contents.
        """
        if not contents:
            return ""

        sections = []

        # When using loader mode, self.sources is empty - iterate over contents keys
        # When using backend mode, iterate over self.sources to preserve order
        keys = self.sources if self.sources else list(contents.keys())

        for key in keys:
            if contents.get(key):
                sections.append(f"Contents of {key}:\n\n{contents[key]}")

        if not sections:
            return ""

        return "\n\n".join(sections)

    async def _load_memory_from_backend(
        self,
        backend: BackendProtocol,
        path: str,
    ) -> str | None:
        """Load memory content from a backend path.

        Args:
            backend: Backend to load from.
            path: Path to the AGENTS.md file.

        Returns:
            File content if found, None otherwise.
        """
        results = await backend.adownload_files([path])
        # Should get exactly one response for one path
        if len(results) != 1:
            raise AssertionError(f"Expected 1 response for path {path}, got {len(results)}")
        response = results[0]

        if response.error is not None:
            raise ValueError(f"Failed to download {path}: {response.error}")

        if response.content is not None:
            return response.content.decode("utf-8")

        return None

    def _load_memory_from_backend_sync(
        self,
        backend: BackendProtocol,
        path: str,
    ) -> str | None:
        """Load memory content from a backend path synchronously.

        Args:
            backend: Backend to load from.
            path: Path to the AGENTS.md file.

        Returns:
            File content if found, None otherwise.
        """
        results = backend.download_files([path])
        # Should get exactly one response for one path
        if len(results) != 1:
            raise AssertionError(f"Expected 1 response for path {path}, got {len(results)}")
        response = results[0]

        if response.error is not None:
            raise ValueError(f"Failed to download {path}: {response.error}")

        if response.content is not None:
            return response.content.decode("utf-8")

        return None

    def before_agent(self, state: MemoryState, runtime: Runtime, config: RunnableConfig) -> MemoryStateUpdate | None:
        """Load memory content before agent execution (synchronous).

        Loads memory from all configured sources and stores in state.
        Only loads if not already present in state.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            State update with memory_contents populated.
        """
        # Skip if already loaded
        if "memory_contents" in state:
            return None

        backend = self._get_backend(state, runtime, config)
        contents: dict[str, str] = {}

        for path in self.sources:
            content = self._load_memory_from_backend_sync(backend, path)
            if content:
                contents[path] = content
                logger.debug(f"Loaded memory from: {path}")

        return MemoryStateUpdate(memory_contents=contents)

    async def abefore_agent(
        self, state: MemoryState, runtime: Runtime, config: RunnableConfig
    ) -> MemoryStateUpdate | None:
        """Load memory content before agent execution.

        Loads memory from API (if loader configured) or from backend sources.
        Only loads if not already present in state.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            State update with memory_contents populated.
        """
        # Skip if already loaded
        if "memory_contents" in state:
            return None

        contents: dict[str, str] = {}

        # Priority 1: Use loader if configured (API)
        if self.loader:
            contents = await self.loader.load_memories()
            if contents:
                logger.debug(f"Loaded {len(contents)} memories from API")

        # Priority 2: Fall back to backend/sources
        elif self._backend and self.sources:
            backend = self._get_backend(state, runtime, config)
            for path in self.sources:
                content = await self._load_memory_from_backend(backend, path)
                if content:
                    contents[path] = content
                    logger.debug(f"Loaded memory from: {path}")

        return MemoryStateUpdate(memory_contents=contents)

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject memory content into the system prompt.

        Uses append_to_system_message to properly handle content blocks
        instead of just string concatenation. Skips injection entirely
        when no memory content is loaded.

        When ``insert_after`` is set, the memory section is inserted after
        the named prompt section rather than appended at the end.

        Args:
            request: Model request to modify.

        Returns:
            Modified request with memory injected into system prompt.
        """
        contents = request.state.get("memory_contents", {})
        memory_locations = self._format_memory_locations(contents)
        memory_contents = self._format_memory_contents(contents)

        if not memory_contents:
            return request

        memory_section = self.system_prompt_template.format(
            memory_locations=memory_locations,
            memory_contents=memory_contents,
        )

        if self.insert_after:
            system_message = insert_after_section(
                request.system_message, memory_section, self.insert_after
            )
        else:
            system_message = append_to_system_message(request.system_message, memory_section)
        return request.override(system_message=system_message)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Wrap model call to inject memory into system prompt.

        Args:
            request: Model request being processed.
            handler: Handler function to call with modified request.

        Returns:
            Model response from handler.
        """
        modified_request = self.modify_request(request)
        return handler(modified_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async wrap model call to inject memory into system prompt.

        Args:
            request: Model request being processed.
            handler: Async handler function to call with modified request.

        Returns:
            Model response from handler.
        """
        modified_request = self.modify_request(request)
        return await handler(modified_request)
