# DeepAlpha CLI — Terminal AI Trading Assistant

Python + Textual terminal app. Deep Analysts multi-agent orchestration with BYOK LLM keys (OpenAI, Anthropic, Google, plus GitHub Copilot / Codex / Gemini CLI routing). Connects to Basement (market data, signals, memories) and Park (search, news, fundamentals).

## Commands

```bash
uv sync                             # Install
uv run deepalpha                    # Interactive mode
uv run deepalpha login              # Browser OAuth via Basement
uv run deepalpha --model <name>     # Override model (provider auto-detected)
uv run deepalpha -r [<thread_id>]   # Resume most recent / specific thread
uv run deepalpha -m "…"             # Auto-submit a prompt
uv run deepalpha --pipe -m "…"      # Non-interactive, stream to stdout
uv run deepalpha --auto-approve     # Skip HITL prompts
uv run deepalpha --sandbox modal|daytona|runloop
uv run deepalpha threads list|delete
uv run deepalpha skills
uv run deepalpha auth copilot|codex|gemini
make test && make lint              # Pytest (--disable-socket) + Ruff
```

## Architecture

### Agent system

`create_cli_agent()` in `deepalpha/agent.py` → `create_deep_analysts()` in `deepalpha/analysts/graph.py`.

Orchestrator middleware (order matters):
1. `ToolErrorHandlingMiddleware`
2. `TodoListMiddleware`
3. `SummarizationMiddleware` — trigger `("tokens", 100_000)`, keep `("messages", 20)`, arg-truncation over 20-message window at 2000 chars
4. `MemoryMiddleware` *(if memory configured)*
5. `SkillsMiddleware` *(if skills configured)*
6. `FilesystemMiddleware`
7. `SubAgentMiddleware` (technical / fundamental subagents)
8. `PatchToolCallsMiddleware`
9. `HumanInTheLoopMiddleware` — interrupts on signal CRUD and spawn creation (see HITL below)

Subagent middleware: `ToolErrorHandling → Skills? → Filesystem → PatchToolCalls`.

**Subagents** live in `deepalpha/analysts/` (`technical_analyst`, `fundamental_analyst`). Signal management tools stay on the orchestrator, not delegated.

Middleware library: `deepanalysts >= 0.2.0` (PyPI). Local dev path in `libs/deepanalysts/` — uncomment the `[tool.uv.sources]` block in `pyproject.toml` to use it.

### BYOK models

Provider auto-detected by which API key is set, with priority `OPENAI_API_KEY → ANTHROPIC_API_KEY → GOOGLE_API_KEY`. Override via `--model <name>` (provider inferred from name) or `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `GOOGLE_MODEL`.

Defaults: `gpt-5-mini` (OpenAI), `claude-sonnet-4-5-20250929` (Anthropic), `gemini-3-flash-preview` (Google).

### Auth flow

1. `deepalpha login` opens a browser to Basement's OAuth device flow.
2. CLI receives the auth code, persists the session token to `~/.deepalpha/credentials.json` (mode `0o600`).
3. Every Basement/Park call attaches the token; Park validates it against Basement with a 5-minute cache.

### HITL

`HumanInTheLoopMiddleware` interrupts on: `create_trading_insight`, `update_trading_insight`, `close_position`, `cancel_signal`, `create_spawn`. The `ApprovalMenu` widget renders the decision. `--auto-approve` bypasses — don't enable unattended unless you trust the prompt.

### Local spawns (BYOK background agents)

Spawns are autonomous agents that run locally with the user's own API keys — everything in `deepalpha/spawns/`:

- `manager.py` — top-level lifecycle + CRUD.
- `store.py` — SQLite persistence at `~/.deepalpha/sessions.db`.
- `scheduler.py` — asyncio polling loop (30s tick).
- `executor.py` — agent creation with timeout/backoff.
- `agent_factory.py` — restricted agent per spawn type.

Spawn types: `monitoring` (position management) and `task` (analysis/research). Schedule types: `once`, `interval` (minutes), `cron` (5-field; requires `croniter`). Spawn agents have **no HITL**, **no SubAgent delegation**, and filtered tool access.

### Tools

Under `deepalpha/trading_tools/` grouped by `market_data/`, `research/`, `signals/`, `memory.py`, `spawns.py`. General HTTP helpers in `deepalpha/tools.py`. Each `@tool` uses a Pydantic schema and pulls the session token from `context.py` ContextVars.

## Interactive slash-commands

`/clear`, `/help`, `/remember`, `/tokens`, `/threads`, `/model`, `/spawns`, `/quit`.

## Environment

```bash
# LLM keys (at least one)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# API URLs (default to production)
BASEMENT_API=https://basement.deepalpha.mn
PARK_API=https://park.deepalpha.mn

# Optional
DEEPALPHA_DEFAULT_SYMBOL=BTC/USDT
DEEPALPHA_DEFAULT_EXCHANGE=binance
DEEPALPHA_DEFAULT_INTERVAL=4h
DEEPALPHA_LANGSMITH_PROJECT=deepalpha-cli
LANGCHAIN_API_KEY=...
```

## Adding a tool

1. Create it in `deepalpha/trading_tools/<group>/` with `@tool` + Pydantic schema.
2. Pull the session token: `token = get_jwt_token(); if not token: raise ToolException(...)`.
3. Export from the group's `__init__.py`.
4. Wire it into the appropriate tool list in `deepalpha/analysts/graph.py` (orchestrator vs subagent).
