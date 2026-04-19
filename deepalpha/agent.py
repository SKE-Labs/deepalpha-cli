"""Agent management and creation for the CLI."""

import shutil
import tempfile
from pathlib import Path

from deepanalysts.backends import CompositeBackend, FilesystemBackend, SandboxBackendProtocol
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from deepalpha.config import COLORS, config, console, get_default_coding_instructions, settings
from deepalpha.integrations.sandbox_factory import get_default_working_dir
from deepalpha.utils.prompt_loader import load_prompt


def list_agents() -> None:
    """List all available agents."""
    agents_dir = settings.user_deepalpha_dir

    if not agents_dir.exists() or not any(agents_dir.iterdir()):
        console.print("[yellow]No agents found.[/yellow]")
        console.print(
            "[dim]Agents will be created in ~/.deepalpha/ when you first use them.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print("\n[bold]Available Agents:[/bold]\n", style=COLORS["primary"])

    for agent_path in sorted(agents_dir.iterdir()):
        if agent_path.is_dir():
            agent_name = agent_path.name
            agent_md = agent_path / "AGENTS.md"

            if agent_md.exists():
                console.print(f"  • [bold]{agent_name}[/bold]", style=COLORS["primary"])
                console.print(f"    {agent_path}", style=COLORS["dim"])
            else:
                console.print(f"  • [bold]{agent_name}[/bold] [dim](incomplete)[/dim]", style=COLORS["tool"])
                console.print(f"    {agent_path}", style=COLORS["dim"])

    console.print()


def reset_agent(agent_name: str, source_agent: str | None = None) -> None:
    """Reset an agent to default or copy from another agent."""
    agents_dir = settings.user_deepalpha_dir
    agent_dir = agents_dir / agent_name

    if source_agent:
        source_dir = agents_dir / source_agent
        source_md = source_dir / "AGENTS.md"

        if not source_md.exists():
            console.print(f"[bold red]Error:[/bold red] Source agent '{source_agent}' not found or has no AGENTS.md")
            return

        source_content = source_md.read_text()
        action_desc = f"contents of agent '{source_agent}'"
    else:
        source_content = get_default_coding_instructions()
        action_desc = "default"

    if agent_dir.exists():
        shutil.rmtree(agent_dir)
        console.print(f"Removed existing agent directory: {agent_dir}", style=COLORS["tool"])

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "AGENTS.md"
    agent_md.write_text(source_content)

    console.print(f"✓ Agent '{agent_name}' reset to {action_desc}", style=COLORS["primary"])
    console.print(f"Location: {agent_dir}\n", style=COLORS["dim"])


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the base system prompt for the trading analyst agent.

    Args:
        assistant_id: The agent identifier for path references
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     If None, agent is operating in local mode.

    Returns:
        The system prompt string providing environment context and guidelines
    """
    agent_dir_path = f"~/.deepalpha/{assistant_id}"

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
        env_section = load_prompt("system/env_sandbox.md", working_dir=working_dir)
    else:
        cwd = str(Path.cwd())
        env_section = load_prompt("system/env_local.md", cwd=cwd)

    body = load_prompt("system/system_prompt.md", agent_dir_path=agent_dir_path)
    return env_section + "\n\n" + body


def create_cli_agent(
    model: str | BaseChatModel,
    assistant_id: str,
    *,
    tools: list[BaseTool] | None = None,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    enable_memory: bool = True,
    enable_skills: bool = True,
    checkpointer: BaseCheckpointSaver | None = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create a CLI-configured agent with flexible options.

    This is the main entry point for creating an DeepAlpha CLI agent, usable both
    internally and from external code (e.g., benchmarking frameworks, Harbor).

    Uses Deep Analysts orchestrator with specialized subagents for research and analysis.

    Args:
        model: LLM model to use (e.g., "anthropic:claude-sonnet-4-5-20250929")
        assistant_id: Agent identifier for memory/state storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution (e.g., ModalBackend).
                 If None, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     Used for system prompt generation.
        system_prompt: Override the default system prompt. If None, generates one
                      based on sandbox_type and assistant_id.
        auto_approve: If True, automatically approves all tool calls without human
                     confirmation. Useful for automated workflows.
        enable_memory: Enable MemoryMiddleware for persistent memory
        enable_skills: Enable SkillsMiddleware for custom agent skills
        checkpointer: Optional checkpointer for session persistence. If None, uses
                     InMemorySaver (no persistence across CLI invocations).

    Returns:
        2-tuple of (agent_graph, backend)
        - agent_graph: Configured LangGraph Pregel instance ready for execution
        - composite_backend: CompositeBackend for file operations
    """
    tools = tools or []

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        backend = FilesystemBackend()
    else:
        # ========== REMOTE SANDBOX MODE ==========
        backend = sandbox  # Remote sandbox (ModalBackend, etc.)

    # Get or use custom system prompt
    if system_prompt is None:
        system_prompt = get_system_prompt(assistant_id=assistant_id, sandbox_type=sandbox_type)

    # Set up composite backend with routing
    # For local FilesystemBackend, route large tool results to /tmp to avoid polluting
    # the working directory. For sandbox backends, no special routing is needed.
    if sandbox is None:
        # Local mode: Route large results to a unique temp directory
        large_results_dir = tempfile.mkdtemp(prefix="deepalpha_large_results_")
        large_results_backend = FilesystemBackend(
            root_dir=large_results_dir,
            virtual_mode=True,
        )
        composite_backend = CompositeBackend(
            default=backend,
            routes={
                "/large_tool_results/": large_results_backend,
            },
        )
    else:
        # Sandbox mode: No special routing needed
        composite_backend = CompositeBackend(
            default=backend,
            routes={},
        )

    # Create the agent using Deep Analysts orchestrator
    # Use provided checkpointer or fallback to InMemorySaver
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    from deepalpha.analysts import create_deep_analysts

    # Collect memory and skills paths
    memory_sources: list[str] = []
    skills_sources: list[str] = []

    if enable_memory:
        # User's global AGENTS.md (ensure it exists)
        user_agent_md = settings.get_user_agent_md_path(assistant_id)
        if not user_agent_md.exists():
            # Create default AGENTS.md
            user_agent_md.parent.mkdir(parents=True, exist_ok=True)
            user_agent_md.write_text("# Agent Memory\n\nAdd your preferences and notes here.\n")
        memory_sources.append(str(user_agent_md))

        # Project-level AGENTS.md (only if it exists)
        project_agent_md = settings.get_project_agent_md_path()
        if project_agent_md and project_agent_md.exists():
            memory_sources.append(str(project_agent_md))

    if enable_skills:
        # Built-in skills (lowest priority)
        from deepalpha.skills.load import BUILT_IN_SKILLS_DIR

        if BUILT_IN_SKILLS_DIR.exists():
            skills_sources.append(str(BUILT_IN_SKILLS_DIR))

        # User's skills directory (ensure it exists)
        user_skills_dir = settings.ensure_user_skills_dir(assistant_id)
        skills_sources.append(str(user_skills_dir))

        # Project-level skills (only if directory exists, highest priority)
        project_skills_dir = settings.get_project_skills_dir()
        if project_skills_dir and project_skills_dir.exists():
            skills_sources.append(str(project_skills_dir))

    agent = create_deep_analysts(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=final_checkpointer,
        backend=composite_backend,
        skills=skills_sources if skills_sources else None,
        memory=memory_sources if memory_sources else None,
    ).with_config(config)

    return agent, composite_backend
