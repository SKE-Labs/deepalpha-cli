# Embient CLI — Terminal AI Trading Assistant

Python + Textual terminal app. Deep Analysts multi-agent orchestration with BYOK model support (OpenAI, Anthropic, Google). Connects to Basement (market data, signals) and Park (search, news, fundamentals).

## Commands

```bash
uv sync                  # Install
uv run embient           # Interactive mode
uv run embient login     # Browser-based OAuth
uv run embient logout    # Clear credentials
uv run embient status    # Auth status

# Model override (auto-detects provider from name)
uv run embient --model gpt-5-mini
uv run embient --model claude-sonnet-4-5-20250929
uv run embient --model gemini-3-flash-preview

# Resume session
uv run embient -r              # Most recent thread
uv run embient -r <thread_id>  # Specific thread

# Auto-submit + non-interactive
uv run embient -m "Analyze BTC/USDT"
uv run embient --pipe -m "..."   # Stream to stdout
uv run embient --auto-approve    # Skip HITL prompts

# Remote sandbox
uv run embient --sandbox modal|daytona|runloop

# Agent/thread management
uv run embient list
uv run embient threads list [--agent NAME --limit N]
uv run embient threads delete <id>
uv run embient skills

# Testing & linting
make test          # Unit tests (--disable-socket)
make lint          # Ruff check + format diff
make format        # Auto-fix
make coverage      # Coverage report
```

## Architecture

### Agent System

`create_cli_agent()` in `embient/agent.py` builds the Deep Analysts supervisor via `create_deep_analysts()` in `embient/analysts/graph.py`.

**Orchestrator middleware stack** (order matters):
1. ToolErrorHandling → 2. TodoList → 3. Memory → 4. Skills → 5. Filesystem → 6. SubAgent → 7. PatchToolCalls → 8. HumanInTheLoop

**Subagents:**

| Agent | Tools | HITL |
|-------|-------|------|
| `technical_analyst` | generate_chart, get_latest_candle, get_indicator, get_candles_around_date | None |
| `fundamental_analyst` | get_financial_news, get_fundamentals, get_economics_calendar | None |

Signal management tools are on the supervisor (not a separate subagent).

**Subagent middleware:** ToolErrorHandling → Skills (filtered) → Filesystem → PatchToolCalls

**Middleware library:** `deepanalysts>=0.1.9` (PyPI, local dev in `libs/deepanalysts/`)

### BYOK Model Support

Auto-detected from API key priority: `OPENAI_API_KEY` → `ANTHROPIC_API_KEY` → `GOOGLE_API_KEY`.
Override: `--model NAME` or env vars `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GOOGLE_MODEL`.

Defaults: `gpt-5-mini` (OpenAI), `claude-sonnet-4-5-20250929` (Anthropic), `gemini-3-flash-preview` (Google).

### Auth Flow

1. `embient login` opens browser to Basement OAuth
2. User authenticates, CLI receives auth code
3. Token stored in `~/.embient/credentials.json` (mode 0o600)
4. All API calls include token in Authorization header

### HITL

Signal creation/update requires user approval via `ApprovalMenu` widget. Use `--auto-approve` to skip.

## Tools

**Trading Tools** (`embient/trading_tools/`):

| Tool | Source | Purpose |
|------|--------|---------|
| `get_latest_candle` | Basement | Current 5m price |
| `get_candles_around_date` | Basement | Historical candles |
| `get_indicator` | Basement | RSI, MACD, EMA, SMA, BB, etc. |
| `generate_chart` | Basement→Vermeer | Chart image |
| `web_search` | Park (Brave) | General web search |
| `get_financial_news` | Park | Trusted source news |
| `get_fundamentals` | Park (TwelveData) | Stock fundamentals |
| `get_economics_calendar` | Basement | Economic events |
| `get_active_trading_signals` | Basement | List signals |
| `create_trading_signal` | Basement | Create signal (HITL) |
| `update_trading_signal` | Basement | Update signal (HITL) |
| `calculate_position_size` | Local | Risk-based sizing |
| `list_memories` | Basement | List memories |
| `create_memory` | Basement | Create memory |
| `update_memory` | Basement | Update memory |
| `delete_memory` | Basement | Delete memory |

**General Tools** (`embient/tools.py`): `http_request`, `fetch_url`

## Key Files

```
embient/
├── main.py              # CLI entry point, argument parsing
├── agent.py             # Agent factory (create_cli_agent)
├── auth.py              # OAuth login/logout/status
├── context.py           # ContextVars (auth_token, thread_id, user_profile, images)
├── config.py            # Settings, model creation, color scheme
├── model_config.py      # Model discovery by provider
├── trading_config.py    # TradingConfig (exchange, interval, position size, leverage)
├── sessions.py          # SQLite checkpointer (~/.embient/sessions.db)
├── app.py               # Textual UI application
├── non_interactive.py   # Pipe mode (--pipe, --quiet)
├── analysts/
│   ├── graph.py         # create_deep_analysts() + middleware stack
│   ├── technical.py     # Technical analyst subagent
│   └── fundamental.py   # Fundamental analyst subagent
├── clients/
│   ├── basement.py      # Basement API (market data, signals, memories, charts)
│   └── park.py          # Park API (search, news, fundamentals)
├── trading_tools/       # @tool decorated LangChain tools
│   ├── market_data/     # Candles, indicators, charts
│   ├── research/        # News, fundamentals, economics
│   ├── signals/         # Signal CRUD, position sizing
│   └── memory.py        # Memory CRUD
├── integrations/        # Sandbox providers (modal, daytona, runloop)
├── skills/              # Skills loading + CLI commands
├── widgets/             # Textual UI components (14 widgets)
└── utils/
libs/deepanalysts/       # Middleware & backend library (v0.1.10, PyPI)
```

## Interactive Commands

`/clear`, `/help`, `/remember`, `/tokens`, `/quit`

## Environment

```bash
# LLM keys (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

# API URLs (optional, defaults to production)
BASEMENT_API=https://basement.embient.ai
PARK_API=https://park.embient.ai

# Trading defaults (optional)
EMBIENT_DEFAULT_SYMBOL=BTC/USDT
EMBIENT_DEFAULT_EXCHANGE=binance
EMBIENT_DEFAULT_INTERVAL=4h

# LangSmith (optional)
EMBIENT_LANGSMITH_PROJECT=embient-cli
LANGCHAIN_API_KEY=...
```

## Adding a New Tool

1. Create in `embient/trading_tools/` with `@tool` + Pydantic schema
2. Require auth: `token = get_jwt_token(); if not token: raise ToolException(...)`
3. Export from `__init__.py`
4. Add to appropriate tool list in `embient/analysts/graph.py`
