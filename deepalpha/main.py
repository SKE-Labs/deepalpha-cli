"""Main entry point and CLI loop for DeepAlpha."""
# ruff: noqa: E402

# Suppress deprecation warnings from langchain_core (e.g., Pydantic V1 on Python 3.14+)
# ruff: noqa: E402
import warnings

warnings.filterwarnings("ignore", module="langchain_core._api.deprecation")

import argparse
import asyncio
import contextlib
import os
import sys
import warnings
from pathlib import Path

# Suppress Pydantic v1 compatibility warnings from langchain on Python 3.14+
warnings.filterwarnings("ignore", message=".*Pydantic V1.*", category=UserWarning)

from rich.text import Text

from deepalpha._version import __version__

# Now safe to import agent (which imports LangChain modules)
from deepalpha.agent import create_cli_agent, list_agents, reset_agent
from deepalpha.auth import get_cli_token, is_authenticated, login_command, logout_command, status_command

# CRITICAL: Import config FIRST to set LANGSMITH_PROJECT before LangChain loads
from deepalpha.config import (
    console,
    create_model,
)
from deepalpha.context import set_auth_token
from deepalpha.integrations.sandbox_factory import create_sandbox
from deepalpha.sessions import (
    delete_thread_command,
    generate_thread_id,
    get_checkpointer,
    get_most_recent,
    get_thread_agent,
    list_threads_command,
    thread_exists,
)
from deepalpha.skills import execute_skills_command, setup_skills_parser
from deepalpha.tools import fetch_url, http_request
from deepalpha.trading_tools.research import web_search as park_web_search
from deepalpha.ui import show_help


def check_cli_dependencies() -> None:
    """Check if CLI optional dependencies are installed."""
    missing = []

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append("python-dotenv")

    try:
        import textual  # noqa: F401
    except ImportError:
        missing.append("textual")

    if missing:
        print("\n❌ Missing required CLI dependencies!")
        print("\nThe following packages are required to use the deepalpha CLI:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nPlease install them with:")
        print("  pip install deepalpha[cli]")
        print("\nOr install all dependencies:")
        print("  pip install 'deepalpha[cli]'")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DeepAlpha - AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"deepalpha {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset an agent")
    reset_parser.add_argument("--agent", required=True, help="Name of agent to reset")
    reset_parser.add_argument("--target", dest="source_agent", help="Copy prompt from another agent")

    # Skills command - setup delegated to skills module
    setup_skills_parser(subparsers)

    # Auth commands (Basement)
    subparsers.add_parser("login", help="Authenticate with DeepAlpha")
    subparsers.add_parser("logout", help="Clear stored credentials")
    subparsers.add_parser("status", help="Show authentication status")

    # LLM provider auth commands
    auth_parser = subparsers.add_parser("auth", help="Manage LLM provider authentication")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")
    auth_sub.add_parser("copilot", help="Login with GitHub Copilot (device flow)")
    auth_sub.add_parser("codex", help="Login with OpenAI Codex (ChatGPT Plus/Pro)")
    auth_sub.add_parser("gemini", help="Login with Google Gemini CLI (Google AI Pro/Ultra)")
    auth_sub.add_parser("logout-copilot", help="Remove GitHub Copilot credentials")
    auth_sub.add_parser("logout-codex", help="Remove OpenAI Codex credentials")
    auth_sub.add_parser("logout-gemini", help="Remove Google Gemini credentials")
    auth_sub.add_parser("status", help="Show LLM provider auth status")

    # Threads command
    threads_parser = subparsers.add_parser("threads", help="Manage conversation threads")
    threads_sub = threads_parser.add_subparsers(dest="threads_command")

    # threads list
    threads_list = threads_sub.add_parser("list", help="List threads")
    threads_list.add_argument("--agent", default=None, help="Filter by agent name (default: show all)")
    threads_list.add_argument("--limit", type=int, default=20, help="Max threads (default: 20)")

    # threads delete
    threads_delete = threads_sub.add_parser("delete", help="Delete a thread")
    threads_delete.add_argument("thread_id", help="Thread ID to delete")

    # Spawns command
    spawns_parser = subparsers.add_parser("spawns", help="Manage local agent spawns")
    spawns_sub = spawns_parser.add_subparsers(dest="spawns_command")
    spawns_list = spawns_sub.add_parser("list", help="List spawns")
    spawns_list.add_argument(
        "--status", default=None, help="Filter by status (active, paused, completed, failed, cancelled)"
    )

    # Default interactive mode
    parser.add_argument(
        "--agent",
        default="agent",
        help="Agent identifier for separate memory stores (default: agent).",
    )

    # Thread resume argument - matches PR #638: -r for most recent, -r <ID> for specific
    parser.add_argument(
        "-r",
        "--resume",
        dest="resume_thread",
        nargs="?",
        const="__MOST_RECENT__",
        default=None,
        help="Resume thread: -r for most recent, -r <ID> for specific thread",
    )

    # Initial prompt - auto-submit when session starts
    parser.add_argument(
        "-m",
        "--message",
        dest="initial_prompt",
        help="Initial prompt to auto-submit when session starts",
    )

    parser.add_argument(
        "--model",
        help="Model to use (e.g., claude-sonnet-4-5-20250929, gpt-5-mini, copilot/gpt-4o). Provider is auto-detected from model name.",
    )
    parser.add_argument(
        "--provider",
        choices=[
            "openai",
            "anthropic",
            "google",
            "copilot",
            "codex",
            "gemini-cli",
            "zai",
            "alibaba",
            "minimax",
            "synthetic",
            "chutes",
        ],
        help="Force a specific LLM provider (overrides auto-detection)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables human-in-the-loop)",
    )
    parser.add_argument(
        "-p",
        "--pipe",
        action="store_true",
        help="Non-interactive pipe mode: run task, stream output to stdout, and exit",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Quiet mode (use with -p): only agent response text on stdout, status on stderr",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "modal", "daytona", "runloop"],
        default="none",
        help="Remote sandbox for code execution (default: none - local only)",
    )
    parser.add_argument(
        "--sandbox-id",
        help="Existing sandbox ID to reuse (skips creation and cleanup)",
    )
    parser.add_argument(
        "--sandbox-setup",
        help="Path to setup script to run in sandbox after creation",
    )
    return parser.parse_args()


async def run_textual_cli_async(
    assistant_id: str,
    *,
    auto_approve: bool = False,
    sandbox_type: str = "none",
    sandbox_id: str | None = None,
    model_name: str | None = None,
    provider_name: str | None = None,
    thread_id: str | None = None,
    is_resumed: bool = False,
    initial_prompt: str | None = None,
) -> None:
    """Run the Textual CLI interface (async version).

    Args:
        assistant_id: Agent identifier for memory storage
        auto_approve: Whether to auto-approve tool usage
        sandbox_type: Type of sandbox ("none", "modal", "runloop", "daytona")
        sandbox_id: Optional existing sandbox ID to reuse
        model_name: Optional model name to use
        provider_name: Optional provider override (copilot, zai, etc.)
        thread_id: Thread ID to use (new or resumed)
        is_resumed: Whether this is a resumed session
        initial_prompt: Optional prompt to auto-submit when session starts
    """
    from deepalpha.app import run_textual_app

    model = create_model(model_name, provider_override=provider_name)

    # Show thread info
    if is_resumed:
        console.print(f"[green]Resuming thread:[/green] {thread_id}")
    else:
        console.print(f"[dim]Thread: {thread_id}[/dim]")

    # Use async context manager for checkpointer
    async with get_checkpointer() as checkpointer:
        # Create agent with tools
        tools = [http_request, fetch_url, park_web_search]

        # Handle sandbox mode
        sandbox_backend = None
        sandbox_cm = None

        if sandbox_type != "none":
            try:
                # Create sandbox context manager but keep it open
                sandbox_cm = create_sandbox(sandbox_type, sandbox_id=sandbox_id)
                sandbox_backend = sandbox_cm.__enter__()
            except (ImportError, ValueError, RuntimeError, NotImplementedError) as e:
                console.print()
                console.print("[red]❌ Sandbox creation failed[/red]")
                console.print(Text(str(e), style="dim"))
                sys.exit(1)

        try:
            agent, composite_backend = create_cli_agent(
                model=model,
                assistant_id=assistant_id,
                tools=tools,
                sandbox=sandbox_backend,
                sandbox_type=sandbox_type if sandbox_type != "none" else None,
                auto_approve=auto_approve,
                checkpointer=checkpointer,
            )

            # Run Textual app
            await run_textual_app(
                agent=agent,
                assistant_id=assistant_id,
                backend=composite_backend,
                auto_approve=auto_approve,
                cwd=Path.cwd(),
                thread_id=thread_id,
                initial_prompt=initial_prompt,
            )
        except Exception as e:
            error_text = Text("❌ Failed to create agent: ", style="red")
            error_text.append(str(e))
            console.print(error_text)
            sys.exit(1)
        finally:
            # Clean up sandbox if we created one
            if sandbox_cm is not None:
                with contextlib.suppress(Exception):
                    sandbox_cm.__exit__(None, None, None)


async def _list_spawns_command(status: str | None = None) -> None:
    """List local spawns from the command line."""
    from deepalpha.spawns.store import SpawnStore

    store = SpawnStore()
    await store.initialize()
    spawns = await store.list_spawns(status=status)

    if not spawns:
        console.print("[dim]No spawns found.[/dim]")
        return

    from rich.table import Table

    table = Table(title=f"Spawns ({len(spawns)})")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Schedule")
    table.add_column("Runs")
    table.add_column("Next Run")

    for s in spawns:
        status_style = {
            "active": "green",
            "paused": "yellow",
            "completed": "dim",
            "failed": "red",
            "cancelled": "dim",
        }.get(s.status, "")

        table.add_row(
            s.id,
            s.name,
            s.spawn_type,
            f"[{status_style}]{s.status}[/{status_style}]",
            s.schedule_display,
            f"{s.run_count}/{s.max_runs}",
            s.next_run_at or "N/A",
        )

    console.print(table)


def _show_provider_auth_status() -> None:
    """Display authentication status for all LLM providers."""
    from deepalpha.config import settings

    console.print()
    console.print("[bold]LLM Provider Status[/bold]")
    console.print()

    console.print("  [bold]BYOK (API keys)[/bold]")
    byok = [
        ("OpenAI", "OPENAI_API_KEY", settings.has_openai),
        ("Anthropic", "ANTHROPIC_API_KEY", settings.has_anthropic),
        ("Google", "GOOGLE_API_KEY", settings.has_google),
        ("Z.AI", "ZAI_API_KEY", settings.has_zai),
        ("Alibaba", "ALIBABA_API_KEY", settings.has_alibaba),
        ("MiniMax", "MINIMAX_API_KEY", settings.has_minimax),
        ("Synthetic", "SYNTHETIC_API_KEY", settings.has_synthetic),
        ("Chutes", "CHUTES_API_KEY", settings.has_chutes),
    ]
    for name, hint, available in byok:
        status = "[green]configured[/green]" if available else "[dim]not configured[/dim]"
        console.print(f"    {name:16s} {status}  [dim]({hint})[/dim]")

    console.print()
    console.print("  [bold]Subscriptions (OAuth)[/bold]")
    subs = [
        ("GitHub Copilot", "deepalpha auth copilot", settings.has_copilot),
        ("OpenAI Codex", "deepalpha auth codex", settings.has_codex),
        ("Google Gemini", "deepalpha auth gemini", settings.has_gemini_cli),
    ]
    for name, hint, available in subs:
        status = "[green]configured[/green]" if available else "[dim]not configured[/dim]"
        console.print(f"    {name:16s} {status}  [dim]({hint})[/dim]")
    console.print()


def cli_main() -> None:
    """Entry point for console script."""
    # Fix for gRPC fork issue on macOS
    # https://github.com/grpc/grpc/issues/37642
    if sys.platform == "darwin":
        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    # Note: LANGSMITH_PROJECT is already overridden in config.py (before LangChain imports)
    # This ensures agent traces → DEEPALPHA_LANGSMITH_PROJECT
    # Shell commands → user's original LANGSMITH_PROJECT (via ShellMiddleware env)

    # Check dependencies first
    check_cli_dependencies()

    try:
        args = parse_args()

        if args.command == "help":
            show_help()
        elif args.command == "list":
            list_agents()
        elif args.command == "reset":
            reset_agent(args.agent, args.source_agent)
        elif args.command == "skills":
            execute_skills_command(args)
        elif args.command == "login":
            asyncio.run(login_command())
        elif args.command == "logout":
            asyncio.run(logout_command())
        elif args.command == "status":
            asyncio.run(status_command())
        elif args.command == "threads":
            if args.threads_command == "list":
                asyncio.run(
                    list_threads_command(
                        agent_name=getattr(args, "agent", None),
                        limit=getattr(args, "limit", 20),
                    )
                )
            elif args.threads_command == "delete":
                asyncio.run(delete_thread_command(args.thread_id))
            else:
                console.print("[yellow]Usage: deepalpha threads <list|delete>[/yellow]")
        elif args.command == "auth":
            if args.auth_command == "copilot":
                from deepalpha.providers.copilot import copilot_login_interactive

                copilot_login_interactive()
            elif args.auth_command == "codex":
                from deepalpha.providers.codex import codex_login_interactive

                codex_login_interactive()
            elif args.auth_command == "gemini":
                from deepalpha.providers.gemini import gemini_login_interactive

                gemini_login_interactive()
            elif args.auth_command == "logout-copilot":
                from deepalpha.providers.copilot import CopilotCredentialStore

                CopilotCredentialStore().clear()
                console.print("[green]Copilot credentials removed.[/green]")
            elif args.auth_command == "logout-codex":
                from deepalpha.providers.codex import CodexCredentialStore

                CodexCredentialStore().clear()
                console.print("[green]Codex credentials removed.[/green]")
            elif args.auth_command == "logout-gemini":
                from deepalpha.providers.gemini import GeminiCredentialStore

                GeminiCredentialStore().clear()
                console.print("[green]Gemini credentials removed.[/green]")
            elif args.auth_command == "status":
                _show_provider_auth_status()
            else:
                console.print("[yellow]Usage: deepalpha auth <copilot|codex|gemini|status|logout-*>[/yellow]")
        elif args.command == "spawns":
            if getattr(args, "spawns_command", None) == "list":
                asyncio.run(_list_spawns_command(getattr(args, "status", None)))
            else:
                console.print("[yellow]Usage: deepalpha spawns list [--status STATUS][/yellow]")
        else:
            # Interactive mode - check auth (required for Deep Analysts)
            if not is_authenticated():
                console.print("[yellow]Not authenticated.[/yellow]")
                console.print("[dim]DeepAlpha CLI requires authentication. Run 'deepalpha login' first.[/dim]")
                sys.exit(1)
            else:
                # Set auth token in context for tools
                cli_token = get_cli_token()
                if cli_token:
                    set_auth_token(cli_token)

            # Handle thread resume
            thread_id = None
            is_resumed = False

            if args.resume_thread == "__MOST_RECENT__":
                # -r (no ID): Get most recent thread
                # If --agent specified, filter by that agent; otherwise get most recent overall
                agent_filter = args.agent if args.agent != "agent" else None
                thread_id = asyncio.run(get_most_recent(agent_filter))
                if thread_id:
                    is_resumed = True
                    agent_name = asyncio.run(get_thread_agent(thread_id))
                    if agent_name:
                        args.agent = agent_name
                else:
                    if agent_filter:
                        msg = Text("No previous thread for '", style="yellow")
                        msg.append(args.agent)
                        msg.append("', starting new.", style="yellow")
                    else:
                        msg = Text("No previous threads, starting new.", style="yellow")
                    console.print(msg)

            elif args.resume_thread:
                # -r <ID>: Resume specific thread
                if asyncio.run(thread_exists(args.resume_thread)):
                    thread_id = args.resume_thread
                    is_resumed = True
                    if args.agent == "agent":
                        agent_name = asyncio.run(get_thread_agent(thread_id))
                        if agent_name:
                            args.agent = agent_name
                else:
                    error_msg = Text("Thread '", style="red")
                    error_msg.append(args.resume_thread)
                    error_msg.append("' not found.", style="red")
                    console.print(error_msg)
                    console.print("[dim]Use 'deepalpha threads list' to see available threads.[/dim]")
                    sys.exit(1)

            # Generate new thread ID if not resuming
            if thread_id is None:
                thread_id = generate_thread_id()

            # Non-interactive pipe mode
            pipe_mode = getattr(args, "pipe", False) or (not sys.stdin.isatty() and args.initial_prompt)

            if pipe_mode:
                if not args.initial_prompt:
                    console.print("[red]Error: -p/--pipe requires -m/--message[/red]")
                    sys.exit(1)

                from deepalpha.non_interactive import run_non_interactive

                exit_code = asyncio.run(
                    run_non_interactive(
                        message=args.initial_prompt,
                        assistant_id=args.agent,
                        model_name=getattr(args, "model", None),
                        provider_name=getattr(args, "provider", None),
                        quiet=getattr(args, "quiet", False),
                        auto_approve=True,
                    )
                )
                sys.exit(exit_code)

            # Run Textual CLI
            asyncio.run(
                run_textual_cli_async(
                    assistant_id=args.agent,
                    auto_approve=args.auto_approve,
                    sandbox_type=args.sandbox,
                    sandbox_id=args.sandbox_id,
                    model_name=getattr(args, "model", None),
                    provider_name=getattr(args, "provider", None),
                    thread_id=thread_id,
                    is_resumed=is_resumed,
                    initial_prompt=getattr(args, "initial_prompt", None),
                )
            )
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - suppress ugly traceback
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
