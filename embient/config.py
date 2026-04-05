"""Configuration, constants, and model creation for the CLI."""

import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import dotenv
from rich.console import Console

from embient._version import __version__

dotenv.load_dotenv()
# Also load user-global keys from ~/.embient/.env (does not override project .env values)
dotenv.load_dotenv(Path.home() / ".embient" / ".env")

# CRITICAL: Override LANGSMITH_PROJECT to route agent traces to separate project
# LangSmith reads LANGSMITH_PROJECT at invocation time, so we override it here
# and preserve the user's original value for shell commands
_embient_project = os.environ.get("EMBIENT_LANGSMITH_PROJECT")
_original_langsmith_project = os.environ.get("LANGSMITH_PROJECT")
if _embient_project:
    # Override LANGSMITH_PROJECT for agent traces
    os.environ["LANGSMITH_PROJECT"] = _embient_project

# Now safe to import LangChain modules
from langchain_core.language_models import BaseChatModel

# Color scheme — monochrome black & white
COLORS = {
    "primary": "#e2e8f0",
    "dim": "#6b7280",
    "user": "#ffffff",
    "agent": "#e2e8f0",
    "thinking": "#94a3b8",
    "tool": "#94a3b8",
}

# ASCII art banner

EMBIENT_ASCII = f"""
 ███████╗ ███╗   ███╗ ██████╗  ██╗ ███████╗ ███╗   ██╗ ████████╗
 ██╔════╝ ████╗ ████║ ██╔══██╗ ██║ ██╔════╝ ████╗  ██║ ╚══██╔══╝
 █████╗   ██╔████╔██║ ██████╔╝ ██║ █████╗   ██╔██╗ ██║    ██║
 ██╔══╝   ██║╚██╔╝██║ ██╔══██╗ ██║ ██╔══╝   ██║╚██╗██║    ██║
 ███████╗ ██║ ╚═╝ ██║ ██████╔╝ ██║ ███████╗ ██║ ╚████║    ██║
 ╚══════╝ ╚═╝     ╚═╝ ╚═════╝  ╚═╝ ╚══════╝ ╚═╝  ╚═══╝    ╚═╝
                                                      v{__version__}
"""


# Interactive commands
COMMANDS = {
    "clear": "Clear screen and reset conversation",
    "help": "Show help information",
    "model": "Switch LLM model",
    "remember": "Review conversation and update memory/skills",
    "threads": "Browse and switch threads",
    "tokens": "Show token usage for current session",
    "quit": "Exit the CLI",
    "exit": "Exit the CLI",
}


# Maximum argument length for display
MAX_ARG_LENGTH = 150

# Agent configuration
config = {"recursion_limit": 1000}

# Rich console instance
console = Console(highlight=False)


def _find_project_root(start_path: Path | None = None) -> Path | None:
    """Find the project root by looking for .git directory.

    Walks up the directory tree from start_path (or cwd) looking for a .git
    directory, which indicates the project root.

    Args:
        start_path: Directory to start searching from. Defaults to current working directory.

    Returns:
        Path to the project root if found, None otherwise.
    """
    current = Path(start_path or Path.cwd()).resolve()

    # Walk up the directory tree
    for parent in [current, *list(current.parents)]:
        git_dir = parent / ".git"
        if git_dir.exists():
            return parent

    return None


def _find_project_agent_md(project_root: Path) -> list[Path]:
    """Find project-specific AGENTS.md file(s).

    Checks two locations and returns ALL that exist:
    1. project_root/.embient/AGENTS.md
    2. project_root/AGENTS.md

    Both files will be loaded and combined if both exist.

    Args:
        project_root: Path to the project root directory.

    Returns:
        List of paths to project AGENTS.md files (may contain 0, 1, or 2 paths).
    """
    paths = []

    # Check .embient/AGENTS.md (preferred)
    embient_md = project_root / ".embient" / "AGENTS.md"
    if embient_md.exists():
        paths.append(embient_md)

    # Check root AGENTS.md (fallback, but also include if both exist)
    root_md = project_root / "AGENTS.md"
    if root_md.exists():
        paths.append(root_md)

    return paths


@dataclass
class Settings:
    """Global settings and environment detection for Embient CLI.

    This class is initialized once at startup and provides access to:
    - Available models and API keys
    - Current project information
    - Tool availability (e.g., Tavily)
    - File system paths

    Attributes:
        project_root: Current project root directory (if in a git project)

        openai_api_key: OpenAI API key if available
        anthropic_api_key: Anthropic API key if available
        tavily_api_key: Tavily API key if available
        embient_langchain_project: LangSmith project name for Embient agent tracing
        user_langchain_project: Original LANGSMITH_PROJECT from environment (for user code)
    """

    # API keys (BYOK)
    openai_api_key: str | None
    anthropic_api_key: str | None
    google_api_key: str | None
    zai_api_key: str | None
    alibaba_api_key: str | None
    minimax_api_key: str | None
    synthetic_api_key: str | None
    chutes_api_key: str | None
    tavily_api_key: str | None

    # LangSmith configuration
    embient_langchain_project: str | None  # For Embient agent tracing
    user_langchain_project: str | None  # Original LANGSMITH_PROJECT for user code

    # Fields with defaults must come after fields without defaults
    copilot_authenticated: bool = False
    codex_authenticated: bool = False
    gemini_cli_authenticated: bool = False
    model_name: str | None = None
    model_provider: str | None = None
    project_root: Path | None = None

    @classmethod
    def from_environment(cls, *, start_path: Path | None = None) -> "Settings":
        """Create settings by detecting the current environment.

        Args:
            start_path: Directory to start project detection from (defaults to cwd)

        Returns:
            Settings instance with detected configuration
        """
        # Detect API keys
        openai_key = os.environ.get("OPENAI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        google_key = os.environ.get("GOOGLE_API_KEY")
        zai_key = os.environ.get("ZAI_API_KEY")
        alibaba_key = os.environ.get("ALIBABA_API_KEY")
        minimax_key = os.environ.get("MINIMAX_API_KEY")
        synthetic_key = os.environ.get("SYNTHETIC_API_KEY")
        chutes_key = os.environ.get("CHUTES_API_KEY")
        tavily_key = os.environ.get("TAVILY_API_KEY")

        # Detect LangSmith configuration
        embient_langchain_project = os.environ.get("EMBIENT_LANGSMITH_PROJECT")
        # Use saved original LANGSMITH_PROJECT (before override at module import time)
        user_langchain_project = _original_langsmith_project

        # Detect project
        project_root = _find_project_root(start_path)

        # Detect subscription providers (file-based credentials)
        copilot_auth = codex_auth = gemini_cli_auth = False
        try:
            from embient.providers.copilot import CopilotCredentialStore

            copilot_auth = CopilotCredentialStore().has_github_token()
        except Exception:
            pass
        try:
            from embient.providers.codex import CodexCredentialStore

            codex_auth = CodexCredentialStore().has_credentials()
        except Exception:
            pass
        try:
            from embient.providers.gemini import GeminiCredentialStore

            gemini_cli_auth = GeminiCredentialStore().has_credentials()
        except Exception:
            pass

        return cls(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            google_api_key=google_key,
            zai_api_key=zai_key,
            alibaba_api_key=alibaba_key,
            minimax_api_key=minimax_key,
            synthetic_api_key=synthetic_key,
            chutes_api_key=chutes_key,
            tavily_api_key=tavily_key,
            copilot_authenticated=copilot_auth,
            codex_authenticated=codex_auth,
            gemini_cli_authenticated=gemini_cli_auth,
            embient_langchain_project=embient_langchain_project,
            user_langchain_project=user_langchain_project,
            project_root=project_root,
        )

    @property
    def has_openai(self) -> bool:
        """Check if OpenAI API key is configured."""
        return self.openai_api_key is not None

    @property
    def has_anthropic(self) -> bool:
        """Check if Anthropic API key is configured."""
        return self.anthropic_api_key is not None

    @property
    def has_google(self) -> bool:
        """Check if Google API key is configured."""
        return self.google_api_key is not None

    @property
    def has_zai(self) -> bool:
        """Check if Z.AI API key is configured."""
        return self.zai_api_key is not None

    @property
    def has_alibaba(self) -> bool:
        return self.alibaba_api_key is not None

    @property
    def has_minimax(self) -> bool:
        return self.minimax_api_key is not None

    @property
    def has_synthetic(self) -> bool:
        return self.synthetic_api_key is not None

    @property
    def has_chutes(self) -> bool:
        return self.chutes_api_key is not None

    @property
    def has_copilot(self) -> bool:
        return self.copilot_authenticated

    @property
    def has_codex(self) -> bool:
        return self.codex_authenticated

    @property
    def has_gemini_cli(self) -> bool:
        return self.gemini_cli_authenticated

    @property
    def has_tavily(self) -> bool:
        """Check if Tavily API key is configured."""
        return self.tavily_api_key is not None

    @property
    def has_embient_langchain_project(self) -> bool:
        """Check if Embient LangChain project name is configured."""
        return self.embient_langchain_project is not None

    @property
    def has_project(self) -> bool:
        """Check if currently in a git project."""
        return self.project_root is not None

    @property
    def user_embient_dir(self) -> Path:
        """Get the base user-level .embient directory.

        Returns:
            Path to ~/.embient
        """
        return Path.home() / ".embient"

    def get_user_agent_md_path(self, agent_name: str) -> Path:
        """Get user-level AGENTS.md path for a specific agent.

        Returns path regardless of whether the file exists.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.embient/{agent_name}/AGENTS.md
        """
        return Path.home() / ".embient" / agent_name / "AGENTS.md"

    def get_project_agent_md_path(self) -> Path | None:
        """Get project-level AGENTS.md path.

        Returns path regardless of whether the file exists.

        Returns:
            Path to {project_root}/.embient/AGENTS.md, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".embient" / "AGENTS.md"

    @staticmethod
    def _is_valid_agent_name(agent_name: str) -> bool:
        """Validate prevent invalid filesystem paths and security issues."""
        if not agent_name or not agent_name.strip():
            return False
        # Allow only alphanumeric, hyphens, underscores, and whitespace
        return bool(re.match(r"^[a-zA-Z0-9_\-\s]+$", agent_name))

    def get_agent_dir(self, agent_name: str) -> Path:
        """Get the global agent directory path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.embient/{agent_name}
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. "
                "Agent names can only contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        return Path.home() / ".embient" / agent_name

    def ensure_agent_dir(self, agent_name: str) -> Path:
        """Ensure the global agent directory exists and return its path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.embient/{agent_name}
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. "
                "Agent names can only contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        agent_dir = self.get_agent_dir(agent_name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir

    def ensure_project_embient_dir(self) -> Path | None:
        """Ensure the project .embient directory exists and return its path.

        Returns:
            Path to project .embient directory, or None if not in a project
        """
        if not self.project_root:
            return None

        project_embient_dir = self.project_root / ".embient"
        project_embient_dir.mkdir(parents=True, exist_ok=True)
        return project_embient_dir

    def get_user_skills_dir(self, agent_name: str) -> Path:
        """Get user-level skills directory path for a specific agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.embient/{agent_name}/skills/
        """
        return self.get_agent_dir(agent_name) / "skills"

    def ensure_user_skills_dir(self, agent_name: str) -> Path:
        """Ensure user-level skills directory exists and return its path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.embient/{agent_name}/skills/
        """
        skills_dir = self.get_user_skills_dir(agent_name)
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir

    def get_project_skills_dir(self) -> Path | None:
        """Get project-level skills directory path.

        Returns:
            Path to {project_root}/.embient/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".embient" / "skills"

    def ensure_project_skills_dir(self) -> Path | None:
        """Ensure project-level skills directory exists and return its path.

        Returns:
            Path to {project_root}/.embient/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        skills_dir = self.get_project_skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir


# Global settings instance (initialized once)
settings = Settings.from_environment()


class SessionState:
    """Holds mutable session state (auto-approve mode, etc)."""

    def __init__(self, auto_approve: bool = False, no_splash: bool = False) -> None:
        self.auto_approve = auto_approve
        self.no_splash = no_splash
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None
        self.thread_id = str(uuid.uuid4())

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve


def get_agent_context_info(assistant_id: str | None = None) -> dict[str, int]:
    """Count AGENTS.md files and skills available for the current agent.

    Args:
        assistant_id: Agent identifier (defaults to "agent")

    Returns:
        Dictionary with 'agents_md_count' and 'skills_count' keys.
    """
    agent_name = assistant_id or "agent"
    agents_md_count = 0
    skills_count = 0

    # Count user-level AGENTS.md
    user_md = settings.get_user_agent_md_path(agent_name)
    if user_md.exists():
        agents_md_count += 1

    # Count project-level AGENTS.md files
    if settings.project_root:
        project_mds = _find_project_agent_md(settings.project_root)
        agents_md_count += len(project_mds)

    # Count skills
    try:
        from embient.skills.load import list_skills

        user_skills_dir = settings.get_user_skills_dir(agent_name)
        project_skills_dir = settings.get_project_skills_dir()
        skills = list_skills(
            user_skills_dir=user_skills_dir,
            project_skills_dir=project_skills_dir,
        )
        skills_count = len(skills)
    except Exception:
        pass

    return {"agents_md_count": agents_md_count, "skills_count": skills_count}


def get_default_coding_instructions() -> str:
    """Get the default coding agent instructions.

    These are the immutable base instructions that cannot be modified by the agent.
    Long-term memory (AGENTS.md) is handled separately by the middleware.
    """
    default_prompt_path = Path(__file__).parent / "default_agent_prompt.md"
    return default_prompt_path.read_text()


def _detect_provider(model_name: str) -> str | None:
    """Auto-detect provider from model name.

    Args:
        model_name: Model name to detect provider from

    Returns:
        Provider name or None if can't detect.
    """
    # Explicit provider/ prefix routing
    for prefix in ("copilot/", "codex/"):
        if model_name.startswith(prefix):
            return prefix.rstrip("/")

    model_lower = model_name.lower()
    if any(x in model_lower for x in ["gpt", "o1", "o3", "o4"]):
        return "openai"
    if "claude" in model_lower:
        return "anthropic"
    if "gemini" in model_lower:
        return "google"
    if model_lower.startswith("glm"):
        return "zai"
    if model_lower.startswith("qwen"):
        return "alibaba"
    if model_lower.startswith("minimax"):
        return "minimax"
    if "codex" in model_lower:
        return "codex"
    if "deepseek" in model_lower:
        return "chutes"
    return None


def create_model(
    model_name_override: str | None = None,
    provider_override: str | None = None,
) -> BaseChatModel:
    """Create the appropriate model based on available API keys.

    Uses the global settings instance to determine which model to create.

    Args:
        model_name_override: Optional model name to use instead of environment variable
        provider_override: Force a specific provider (skips auto-detection)

    Returns:
        ChatModel instance (OpenAI, Anthropic, Google, Copilot, or Z.AI)

    Raises:
        SystemExit if no API key is configured or model provider can't be determined
    """
    # Determine provider and model
    if provider_override:
        provider = provider_override
        if model_name_override:
            model_name = model_name_override
        else:
            from embient.model_config import get_available_models

            models = get_available_models()
            if models.get(provider):
                model_name = models[provider][0]
            else:
                console.print(f"[bold red]Error:[/bold red] Unknown provider: {provider}")
                sys.exit(1)
    elif model_name_override:
        provider = _detect_provider(model_name_override)
        if not provider:
            console.print(
                f"[bold red]Error:[/bold red] Could not detect provider from model name: {model_name_override}"
            )
            console.print("\nSupported: gpt-*/o*-* (openai), claude-* (anthropic), gemini-* (google),")
            console.print("  copilot/<model>, codex/<model>, glm-* (zai), qwen* (alibaba),")
            console.print("  MiniMax-* (minimax), *codex* (codex), deepseek* (chutes)")
            sys.exit(1)

        # Check credentials
        _check: dict[str, tuple[bool, str | None]] = {
            "openai": (settings.has_openai, "OPENAI_API_KEY"),
            "anthropic": (settings.has_anthropic, "ANTHROPIC_API_KEY"),
            "google": (settings.has_google, "GOOGLE_API_KEY"),
            "zai": (settings.has_zai, "ZAI_API_KEY"),
            "alibaba": (settings.has_alibaba, "ALIBABA_API_KEY"),
            "minimax": (settings.has_minimax, "MINIMAX_API_KEY"),
            "synthetic": (settings.has_synthetic, "SYNTHETIC_API_KEY"),
            "chutes": (settings.has_chutes, "CHUTES_API_KEY"),
            "copilot": (settings.has_copilot, None),
            "codex": (settings.has_codex, None),
            "gemini-cli": (settings.has_gemini_cli, None),
        }
        has_creds, env_hint = _check.get(provider, (True, None))
        if not has_creds:
            if env_hint is None:
                console.print(f"[bold red]Error:[/bold red] Model '{model_name_override}' requires auth.")
                console.print(f"Run: [cyan]embient auth {provider}[/cyan]")
            else:
                console.print(f"[bold red]Error:[/bold red] Model '{model_name_override}' requires {env_hint}")
            sys.exit(1)

        model_name = model_name_override
    # Use environment variable defaults, detect provider by API key priority
    # BYOK providers first, then subscription providers
    elif settings.has_openai:
        provider = "openai"
        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    elif settings.has_anthropic:
        provider = "anthropic"
        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    elif settings.has_google:
        provider = "google"
        model_name = os.environ.get("GOOGLE_MODEL", "gemini-3-flash-preview")
    elif settings.has_copilot:
        provider = "copilot"
        model_name = os.environ.get("COPILOT_MODEL", "claude-sonnet-4-5-20250929")
    elif settings.has_codex:
        provider = "codex"
        model_name = os.environ.get("CODEX_MODEL", "gpt-5.3-codex")
    elif settings.has_gemini_cli:
        provider = "gemini-cli"
        model_name = os.environ.get("GEMINI_CLI_MODEL", "gemini-3-pro-preview")
    elif settings.has_zai:
        from embient.providers.zai import DEFAULT_ZAI_MODEL

        provider = "zai"
        model_name = os.environ.get("ZAI_MODEL", DEFAULT_ZAI_MODEL)
    elif settings.has_alibaba:
        provider = "alibaba"
        model_name = os.environ.get("ALIBABA_MODEL", "qwen3.5-plus")
    elif settings.has_minimax:
        provider = "minimax"
        model_name = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
    elif settings.has_synthetic:
        provider = "synthetic"
        model_name = os.environ.get("SYNTHETIC_MODEL", "qwen3-coder-480b")
    elif settings.has_chutes:
        provider = "chutes"
        model_name = os.environ.get("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3-0324")
    else:
        console.print("[bold red]Error:[/bold red] No LLM credentials found.")
        console.print()
        console.print("[bold]API keys[/bold] — set one of:")
        console.print("  [cyan]export OPENAI_API_KEY=...[/cyan]     [cyan]export ALIBABA_API_KEY=...[/cyan]")
        console.print("  [cyan]export ANTHROPIC_API_KEY=...[/cyan]  [cyan]export MINIMAX_API_KEY=...[/cyan]")
        console.print("  [cyan]export GOOGLE_API_KEY=...[/cyan]     [cyan]export SYNTHETIC_API_KEY=...[/cyan]")
        console.print("  [cyan]export ZAI_API_KEY=...[/cyan]        [cyan]export CHUTES_API_KEY=...[/cyan]")
        console.print()
        console.print("[bold]Subscriptions[/bold] — authenticate with:")
        console.print("  [cyan]embient auth copilot[/cyan]    # GitHub Copilot")
        console.print("  [cyan]embient auth codex[/cyan]      # ChatGPT Plus/Pro")
        console.print("  [cyan]embient auth gemini[/cyan]     # Google AI Pro/Ultra")
        console.print()
        console.print("[dim]Or add the key to a .env file in your project.[/dim]")
        sys.exit(1)

    # Store model info in settings for display
    settings.model_name = model_name
    settings.model_provider = provider

    # Create and return the model
    return _instantiate_model(provider, model_name)


def _instantiate_model(provider: str, model_name: str) -> BaseChatModel:
    """Create the LangChain model instance for a given provider."""
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=model_name,
            max_tokens=20_000,  # type: ignore[arg-type]
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        # Workaround for google-genai SDK bug where HttpResponse.json property
        # assumes response_stream is a list, but it can be a raw ClientResponse
        # when an API error occurs.
        try:
            from google.genai._api_client import HttpResponse

            _original_json_fget = HttpResponse.json.fget

            @property  # type: ignore[misc]
            def _safe_json(self: HttpResponse):  # type: ignore[no-redef]
                if not isinstance(self.response_stream, list):
                    return ""
                return _original_json_fget(self)

            HttpResponse.json = _safe_json  # type: ignore[assignment]
        except Exception:
            pass

        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
        )

    if provider == "copilot":
        import httpx
        from langchain_openai import ChatOpenAI

        from embient.providers.copilot import CopilotAuth, CopilotTokenManager

        manager = CopilotTokenManager()
        _token, base_url = manager.get_token_sync()
        actual_model = model_name.removeprefix("copilot/")
        auth = CopilotAuth(manager)
        return ChatOpenAI(
            model=actual_model,
            base_url=f"{base_url}/v1",
            api_key="copilot",  # placeholder — overridden by CopilotAuth per-request
            http_client=httpx.Client(auth=auth),
            http_async_client=httpx.AsyncClient(auth=auth),
        )

    if provider == "codex":
        import httpx
        from langchain_openai import ChatOpenAI

        from embient.providers.codex import CodexAuth, CodexTokenManager

        manager = CodexTokenManager()
        actual_model = model_name.removeprefix("codex/")
        auth = CodexAuth(manager)
        return ChatOpenAI(
            model=actual_model,
            base_url="https://chatgpt.com/backend-api/codex",
            api_key="codex",  # placeholder — overridden by CodexAuth per-request
            http_client=httpx.Client(auth=auth),
            http_async_client=httpx.AsyncClient(auth=auth),
        )

    if provider == "gemini-cli":
        from langchain_google_genai import ChatGoogleGenerativeAI

        from embient.providers.gemini import GeminiTokenManager

        manager = GeminiTokenManager()
        token = manager.get_token_sync()
        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=token,
            temperature=0,
            max_tokens=None,
        )

    # All remaining providers use ChatOpenAI with a custom base_url
    return _create_apikey_provider(provider, model_name)


def _create_apikey_provider(provider: str, model_name: str) -> BaseChatModel:
    """Create a ChatOpenAI instance for simple API-key-based subscription providers."""
    from langchain_openai import ChatOpenAI

    _configs: dict[str, tuple[str, ...]] = {
        # provider: (module_path, get_config_func)
        "zai": ("embient.providers.zai", "get_zai_config"),
        "alibaba": ("embient.providers.alibaba", "get_alibaba_config"),
        "minimax": ("embient.providers.minimax", "get_minimax_config"),
        "synthetic": ("embient.providers.synthetic", "get_synthetic_config"),
        "chutes": ("embient.providers.chutes", "get_chutes_config"),
    }

    entry = _configs.get(provider)
    if not entry:
        console.print(f"[bold red]Error:[/bold red] Unknown provider: {provider}")
        sys.exit(1)

    import importlib

    mod = importlib.import_module(entry[0])
    get_config = getattr(mod, entry[1])
    config = get_config()
    if not config:
        console.print(f"[bold red]Error:[/bold red] {provider} API key is not set.")
        sys.exit(1)

    api_key, base_url, _default_model = config
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
    )


def validate_model_capabilities(model: BaseChatModel, model_name: str) -> None:
    """Validate that the model has required capabilities for Embient.

    Checks the model's profile (if available) to ensure it supports tool calling, which
    is required for agent functionality. Issues warnings for models without profiles or
    with limited context windows.

    Args:
        model: The instantiated model to validate.
        model_name: Model name for error/warning messages.

    Raises:
        SystemExit: If model profile explicitly indicates `tool_calling=False`.

    Note:
        This validation is best-effort. Models without profiles will pass with a warning.
    """
    profile = getattr(model, "profile", None)

    if profile is None:
        # Model doesn't have profile data - warn but allow
        console.print(
            f"[dim][yellow]Note:[/yellow] No capability profile for '{model_name}'. "
            "Cannot verify tool calling support.[/dim]"
        )
        return

    if not isinstance(profile, dict):
        return

    # Check required capability: tool_calling
    tool_calling = profile.get("tool_calling")
    if tool_calling is False:
        console.print(f"[bold red]Error:[/bold red] Model '{model_name}' does not support tool calling.")
        console.print(
            "\nEmbient requires tool calling for agent functionality. Please choose a model that supports tool calling."
        )
        console.print("\nSee MODELS.md for supported models.")
        sys.exit(1)

    # Warn about potentially limited context (< 8k tokens)
    max_input_tokens = profile.get("max_input_tokens")
    if max_input_tokens and max_input_tokens < 8000:
        console.print(
            f"[dim][yellow]Warning:[/yellow] Model '{model_name}' has limited context "
            f"({max_input_tokens:,} tokens). Agent performance may be affected.[/dim]"
        )
