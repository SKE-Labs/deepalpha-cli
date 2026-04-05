"""Modal screen for entering an API key when switching to a provider without credentials."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

from embient.model_config import _PROVIDER_ENV_VARS

# Placeholder hints per provider
_PLACEHOLDER: dict[str, str] = {
    "openai": "sk-...",
    "anthropic": "sk-ant-...",
    "google": "AIza...",
    "zai": "paste Z.AI API key",
    "alibaba": "sk-sp-...",
    "minimax": "paste MiniMax API key",
    "synthetic": "paste Synthetic API key",
    "chutes": "paste Chutes API key",
}


class ApiKeyInputScreen(ModalScreen[str | None]):
    """Modal that prompts the user to paste an API key for a provider.

    Returns the API key string on submit, or None on cancel.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    CSS = """
    ApiKeyInputScreen {
        align: center middle;
    }

    ApiKeyInputScreen > Vertical {
        width: 72;
        max-width: 90%;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ApiKeyInputScreen .api-key-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    ApiKeyInputScreen .api-key-hint {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
    }

    ApiKeyInputScreen #api-key-input {
        margin-bottom: 1;
    }

    ApiKeyInputScreen .api-key-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        text-align: center;
    }
    """

    def __init__(self, provider: str) -> None:
        super().__init__()
        self._provider = provider
        self._env_var = _PROVIDER_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")

    def compose(self) -> ComposeResult:
        placeholder = _PLACEHOLDER.get(self._provider, "paste your API key")
        with Vertical():
            yield Static(
                f"API key required for [bold]{self._provider}[/bold]",
                classes="api-key-title",
            )
            yield Static(
                f"Set [bold]{self._env_var}[/bold] — saved to ~/.embient/.env",
                classes="api-key-hint",
            )
            yield Input(
                placeholder=placeholder,
                password=True,
                id="api-key-input",
            )
            yield Static("Enter submit · Esc cancel", classes="api-key-help")

    def on_mount(self) -> None:
        self.query_one("#api-key-input", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        key = event.value.strip()
        if not key:
            return
        _save_api_key(self._env_var, key)
        self.dismiss(key)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _save_api_key(env_var: str, value: str) -> None:
    """Set the key in os.environ and persist to ~/.embient/.env."""
    os.environ[env_var] = value

    env_path = Path.home() / ".embient" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content, replace or append
    lines: list[str] = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{env_var}="):
                lines.append(f"{env_var}={value}")
                replaced = True
            else:
                lines.append(line)

    if not replaced:
        lines.append(f"{env_var}={value}")

    env_path.write_text("\n".join(lines) + "\n")
    env_path.chmod(0o600)
