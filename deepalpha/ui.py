"""UI rendering and display utilities for the CLI."""

import json
from pathlib import Path
from typing import Any

from deepalpha.config import COLORS, DEEPALPHA_ASCII, MAX_ARG_LENGTH, console


def truncate_value(value: str, max_length: int = MAX_ARG_LENGTH) -> str:
    """Truncate a string value if it exceeds max_length."""
    if len(value) > max_length:
        return value[:max_length] + "..."
    return value


def format_tool_display(tool_name: str, tool_args: dict) -> str:
    """Format tool calls for display with tool-specific smart formatting.

    Shows the most relevant information for each tool type rather than all arguments.

    Args:
        tool_name: Name of the tool being called
        tool_args: Dictionary of tool arguments

    Returns:
        Formatted string for display (e.g., "read_file(config.py)")

    Examples:
        read_file(path="/long/path/file.py") → "read_file(file.py)"
        web_search(query="how to code", max_results=5) → 'web_search("how to code")'
        shell(command="pip install foo") → 'shell("pip install foo")'
    """

    def abbreviate_path(path_str: str, max_length: int = 60) -> str:
        """Abbreviate a file path intelligently - show basename or relative path."""
        try:
            path = Path(path_str)

            # If it's just a filename (no directory parts), return as-is
            if len(path.parts) == 1:
                return path_str

            # Try to get relative path from current working directory
            try:
                rel_path = path.relative_to(Path.cwd())
                rel_str = str(rel_path)
                # Use relative if it's shorter and not too long
                if len(rel_str) < len(path_str) and len(rel_str) <= max_length:
                    return rel_str
            except (ValueError, Exception):
                pass

            # If absolute path is reasonable length, use it
            if len(path_str) <= max_length:
                return path_str

            # Otherwise, just show basename (filename only)
            return path.name
        except Exception:
            # Fallback to original string if any error
            return truncate_value(path_str, max_length)

    # Tool-specific formatting - show the most important argument(s)
    if tool_name in ("read_file", "write_file", "edit_file"):
        # File operations: show the primary file path argument (file_path or path)
        path_value = tool_args.get("file_path")
        if path_value is None:
            path_value = tool_args.get("path")
        if path_value is not None:
            path = abbreviate_path(str(path_value))
            return f"{tool_name}({path})"

    elif tool_name == "web_search":
        # Web search: show the query string
        if "query" in tool_args:
            query = str(tool_args["query"])
            query = truncate_value(query, 100)
            return f'{tool_name}("{query}")'

    elif tool_name == "grep":
        # Grep: show the search pattern
        if "pattern" in tool_args:
            pattern = str(tool_args["pattern"])
            pattern = truncate_value(pattern, 70)
            return f'{tool_name}("{pattern}")'

    elif tool_name == "shell":
        # Shell: show the command being executed
        if "command" in tool_args:
            command = str(tool_args["command"])
            command = truncate_value(command, 120)
            return f'{tool_name}("{command}")'

    elif tool_name == "ls":
        # ls: show directory, or empty if current directory
        if tool_args.get("path"):
            path = abbreviate_path(str(tool_args["path"]))
            return f"{tool_name}({path})"
        return f"{tool_name}()"

    elif tool_name == "glob":
        # Glob: show the pattern
        if "pattern" in tool_args:
            pattern = str(tool_args["pattern"])
            pattern = truncate_value(pattern, 80)
            return f'{tool_name}("{pattern}")'

    elif tool_name == "http_request":
        # HTTP: show method and URL
        parts = []
        if "method" in tool_args:
            parts.append(str(tool_args["method"]).upper())
        if "url" in tool_args:
            url = str(tool_args["url"])
            url = truncate_value(url, 80)
            parts.append(url)
        if parts:
            return f"{tool_name}({' '.join(parts)})"

    elif tool_name == "fetch_url":
        # Fetch URL: show the URL being fetched
        if "url" in tool_args:
            url = str(tool_args["url"])
            url = truncate_value(url, 80)
            return f'{tool_name}("{url}")'

    elif tool_name == "task":
        # Task: show subagent name prominently
        subagent = tool_args.get("subagent_type", "")
        if subagent:
            agent_display = subagent.replace("_", " ").title()
            return f"task \u2192 {agent_display}"
        # Fallback: show truncated description
        if "description" in tool_args:
            desc = str(tool_args["description"])
            desc = truncate_value(desc, 80)
            return f'{tool_name}("{desc}")'
        return f"{tool_name}()"

    elif tool_name == "get_financial_news":
        # News: show the topic
        if "topic" in tool_args:
            topic = str(tool_args["topic"])
            topic = truncate_value(topic, 80)
            return f'{tool_name}("{topic}")'

    elif tool_name == "get_fundamentals":
        # Fundamentals: show ticker and data type
        parts = []
        if "ticker" in tool_args:
            parts.append(str(tool_args["ticker"]))
        if "data_type" in tool_args:
            parts.append(str(tool_args["data_type"]))
        if parts:
            return f"{tool_name}({', '.join(parts)})"

    elif tool_name == "get_latest_candle":
        # Latest candle: show symbol
        if "symbol" in tool_args:
            return f"{tool_name}({tool_args['symbol']})"

    elif tool_name == "get_candles_around_date":
        # Historical candles: show symbol and date
        parts = []
        if "symbol" in tool_args:
            parts.append(str(tool_args["symbol"]))
        if "date" in tool_args:
            parts.append(str(tool_args["date"]))
        if parts:
            return f"{tool_name}({', '.join(parts)})"

    elif tool_name == "get_indicator":
        # Indicator: show indicator name and symbol
        parts = []
        if "indicator" in tool_args:
            parts.append(str(tool_args["indicator"]))
        if "symbol" in tool_args:
            parts.append(str(tool_args["symbol"]))
        if parts:
            return f"{tool_name}({', '.join(parts)})"

    elif tool_name == "get_economics_calendar":
        # Economics calendar: show key filters
        parts = []
        if "impact" in tool_args:
            parts.append(str(tool_args["impact"]))
        if "country" in tool_args:
            parts.append(str(tool_args["country"]))
        if "from_date" in tool_args:
            date_range = str(tool_args["from_date"])
            if "to_date" in tool_args:
                date_range += f" to {tool_args['to_date']}"
            parts.append(date_range)
        if parts:
            return f"{tool_name}({', '.join(parts)})"
        return f"{tool_name}()"

    elif tool_name == "get_user_trading_insights":
        # Trading signals: show status/ticker filter
        parts = []
        if "status" in tool_args:
            parts.append(str(tool_args["status"]))
        if "ticker" in tool_args:
            parts.append(str(tool_args["ticker"]))
        if parts:
            return f"{tool_name}({', '.join(parts)})"
        return f"{tool_name}()"

    elif tool_name == "create_trading_insight":
        # Create signal: show symbol and position
        parts = []
        if "symbol" in tool_args:
            parts.append(str(tool_args["symbol"]))
        if "position" in tool_args:
            parts.append(str(tool_args["position"]).upper())
        if parts:
            return f"{tool_name}({' '.join(parts)})"

    elif tool_name == "update_trading_insight":
        # Update signal: show signal ID and status
        parts = []
        if "signal_id" in tool_args:
            parts.append(f"#{tool_args['signal_id']}")
        if "status" in tool_args:
            parts.append(str(tool_args["status"]))
        if parts:
            return f"{tool_name}({', '.join(parts)})"

    elif tool_name == "calculate_position_size":
        # Position sizing: show symbol
        if "symbol" in tool_args:
            return f"{tool_name}({tool_args['symbol']})"

    elif tool_name == "write_todos":
        # Todos: show count of items
        if "todos" in tool_args and isinstance(tool_args["todos"], list):
            count = len(tool_args["todos"])
            return f"{tool_name}({count} items)"

    # Fallback: generic formatting for unknown tools
    # Show all arguments in key=value format
    args_str = ", ".join(f"{k}={truncate_value(str(v), 50)}" for k, v in tool_args.items())
    return f"{tool_name}({args_str})"


def format_tool_message_content(content: Any) -> str:
    """Convert ToolMessage content into a printable string."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                try:
                    parts.append(json.dumps(item))
                except Exception:
                    parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def show_help() -> None:
    """Show help information."""
    console.print()
    console.print(DEEPALPHA_ASCII, style=f"bold {COLORS['primary']}")
    console.print()

    console.print("[bold]Usage:[/bold]", style=COLORS["primary"])
    console.print("  deepalpha [OPTIONS]                           Start interactive session")
    console.print("  deepalpha list                                List all available agents")
    console.print("  deepalpha reset --agent AGENT                 Reset agent to default prompt")
    console.print("  deepalpha reset --agent AGENT --target SOURCE Reset agent to copy of another agent")
    console.print("  deepalpha help                                Show this help message")
    console.print("  deepalpha --version                           Show deepalpha version")
    console.print()

    console.print("[bold]Options:[/bold]", style=COLORS["primary"])
    console.print("  --agent NAME                  Agent identifier (default: agent)")
    console.print("  --model MODEL                 Model to use (e.g., claude-sonnet-4-5-20250929, gpt-4o)")
    console.print("  --auto-approve                Auto-approve tool usage without prompting")
    console.print("  --sandbox TYPE                Remote sandbox for execution (modal, runloop, daytona)")
    console.print("  --sandbox-id ID               Reuse existing sandbox (skips creation/cleanup)")
    console.print("  -r, --resume [ID]             Resume thread: -r for most recent, -r <ID> for specific")
    console.print()

    console.print("[bold]Examples:[/bold]", style=COLORS["primary"])
    console.print("  deepalpha                              # Start with default agent", style=COLORS["dim"])
    console.print(
        "  deepalpha --agent mybot                # Start with agent named 'mybot'",
        style=COLORS["dim"],
    )
    console.print(
        "  deepalpha --model gpt-4o               # Use specific model (auto-detects provider)",
        style=COLORS["dim"],
    )
    console.print(
        "  deepalpha -r                           # Resume most recent session",
        style=COLORS["dim"],
    )
    console.print(
        "  deepalpha -r abc123                    # Resume specific thread",
        style=COLORS["dim"],
    )
    console.print(
        "  deepalpha --auto-approve               # Start with auto-approve enabled",
        style=COLORS["dim"],
    )
    console.print(
        "  deepalpha --sandbox runloop            # Execute code in Runloop sandbox",
        style=COLORS["dim"],
    )
    console.print()

    console.print("[bold]Authentication:[/bold]", style=COLORS["primary"])
    console.print("  deepalpha login                        # Authenticate with DeepAlpha")
    console.print("  deepalpha logout                       # Clear stored credentials")
    console.print("  deepalpha status                       # Show authentication status")
    console.print()

    console.print("[bold]Thread Management:[/bold]", style=COLORS["primary"])
    console.print("  deepalpha threads list                 # List all sessions", style=COLORS["dim"])
    console.print("  deepalpha threads delete <ID>          # Delete a session", style=COLORS["dim"])
    console.print()

    console.print("[bold]Interactive Features:[/bold]", style=COLORS["primary"])
    console.print("  Enter           Submit your message", style=COLORS["dim"])
    console.print("  Ctrl+J          Insert newline", style=COLORS["dim"])
    console.print("  Shift+Tab       Toggle auto-approve mode", style=COLORS["dim"])
    console.print("  @filename       Auto-complete files and inject content", style=COLORS["dim"])
    console.print("  /command        Slash commands (/help, /clear, /quit)", style=COLORS["dim"])
    console.print("  !command        Run bash commands directly", style=COLORS["dim"])
    console.print()
