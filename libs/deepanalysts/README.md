# Deep Analysts

LangChain/LangGraph middleware for building AI agents with memory, skills, filesystem support, and subagent orchestration.

## Installation

```bash
pip install deepanalysts
```

Or with uv:

```bash
uv add deepanalysts
```

## Overview

Deep Analysts provides a complete middleware stack for LangChain agents:

- **Middleware**: Memory, Skills, Filesystem, Subagents, Summarization, Tool Error Handling
- **Backends**: Store (LangGraph BaseStore), Sandbox (subprocess execution), Composite (path-based routing)
- **API Integration**: Basement client for syncing skills/memories to cloud

Uses only langchain, langgraph, and standard libraries (no external deepalpha dependencies).

## Usage

### SubAgent Middleware (Orchestration)

```python
from deepanalysts.middleware import SubAgentMiddleware, SubAgent

# Define subagents
technical_analyst = SubAgent(
    name="technical_analyst",
    description="Analyzes charts and technical indicators",
    system_prompt="You are a technical analyst...",
    tools=[get_indicator, get_candles],
)

# Create middleware with subagent delegation
middleware = SubAgentMiddleware(
    default_model=model,
    default_tools=[],
    subagents=[technical_analyst, signal_manager],
)
```

### Memory Middleware

```python
from deepanalysts.middleware import MemoryMiddleware
from deepanalysts.backends import StoreBackend

# With backend (file-based)
middleware = MemoryMiddleware(
    backend=lambda rt: StoreBackend(rt),
    sources=[
        "~/.config/myapp/AGENTS.md",
        "./.myapp/AGENTS.md",
    ],
)

# With API loader
from deepanalysts.backends import BasementMemoryLoader

loader = BasementMemoryLoader(token_provider=get_jwt_token)
middleware = MemoryMiddleware(loader=loader)
```

### Skills Middleware

```python
from deepanalysts.middleware import SkillsMiddleware
from deepanalysts.backends import BasementSkillsLoader

# API mode with agent filtering
loader = BasementSkillsLoader(
    token_provider=get_jwt_token,
    store=app.state.store,  # For read_file access
)
middleware = SkillsMiddleware(
    loader=loader,
    agent_name="technical_analyst",  # Filter skills by target_agents
)

# Backend mode
middleware = SkillsMiddleware(
    backend=my_backend,
    sources=["/skills/user/", "/skills/project/"],
)
```

### Filesystem Middleware

```python
from deepanalysts.middleware import FilesystemMiddleware
from deepanalysts.backends import CompositeBackend, StoreBackend, RestrictedSubprocessBackend

# Create backends
store_backend = lambda rt: StoreBackend(rt)
sandbox = RestrictedSubprocessBackend(timeout=30)

# Composite routing
backend = CompositeBackend(
    default=sandbox,
    routes={
        "/skills/": store_backend,
        "/memories/": store_backend,
    }
)

middleware = FilesystemMiddleware(backend=backend)
```

### Summarization Middleware

```python
from deepanalysts.middleware import SummarizationMiddleware

middleware = SummarizationMiddleware(
    model=model,
    backend=backend_factory,
    trigger=("tokens", 100000),  # Trigger at 100k tokens
    keep=("messages", 20),       # Keep last 20 messages
    history_path_prefix="/conversation_history",
)
```

### Tool Error Handling

```python
from deepanalysts.middleware import ToolErrorHandlingMiddleware

# Place first in middleware stack to catch all tool errors
middleware_stack = [
    ToolErrorHandlingMiddleware(),  # First!
    MemoryMiddleware(...),
    SkillsMiddleware(...),
    FilesystemMiddleware(...),
    SubAgentMiddleware(...),
]
```

### Patch Tool Calls (Dangling Tool Calls)

```python
from deepanalysts.middleware import PatchToolCallsMiddleware

# Handles cases where AIMessage has tool calls but no ToolMessage response
middleware_stack = [
    PatchToolCallsMiddleware(),
    # ... other middleware
]
```

### Basement Client

```python
from deepanalysts.clients import BasementClient

client = BasementClient(
    base_url="https://basement.deepalpha.mn",
    token="jwt-token",
)

# Fetch data
memories = await client.get_active_memories()
skills = await client.get_active_skills()

# Sync data back
await client.sync_memory("my-memory", "content")
await client.sync_skill("my-skill", "description", "SKILL.md content")
```

## Package Structure

```
deepanalysts/
├── __init__.py           # Main exports
├── middleware/
│   ├── memory.py         # MemoryMiddleware (loader + backend modes)
│   ├── skills.py         # SkillsMiddleware (loader + backend modes)
│   ├── tool_errors.py    # ToolErrorHandlingMiddleware
│   ├── patch_tool_calls.py # PatchToolCallsMiddleware
│   ├── subagents.py      # SubAgentMiddleware with task tool
│   ├── filesystem.py     # FilesystemMiddleware with file tools
│   ├── summarization.py  # SummarizationMiddleware with backend offloading
│   └── _utils.py         # Internal utilities
├── backends/
│   ├── protocol.py       # BackendProtocol, SandboxBackendProtocol
│   ├── store.py          # StoreBackend (LangGraph BaseStore)
│   ├── sandbox.py        # BaseSandbox, RestrictedSubprocessBackend
│   ├── composite.py      # CompositeBackend (path-based routing)
│   ├── basement.py       # BasementMemoryLoader, BasementSkillsLoader
│   └── utils.py          # Shared utilities (formatting, grep, glob)
├── clients/
│   └── basement.py       # BasementClient (API client)
└── utils/
    └── retry.py          # Retry utilities for transient errors
```

## License

MIT
