"""Model configuration and discovery for the CLI."""

from __future__ import annotations

import os
from collections import OrderedDict

# Default models per provider
_MODELS_BY_PROVIDER: dict[str, list[str]] = OrderedDict(
    [
        # --- BYOK providers (pay-per-use API keys) ---
        (
            "openai",
            [
                "gpt-5-mini",
                "gpt-5.2",
                "gpt-4.1-mini",
                "o4-mini",
            ],
        ),
        (
            "anthropic",
            [
                "claude-sonnet-4-5-20250929",
                "claude-opus-4-6",
                "claude-haiku-4-5-20251001",
            ],
        ),
        (
            "google",
            [
                "gemini-3-flash-preview",
                "gemini-2.5-pro-preview-05-06",
            ],
        ),
        # --- Subscription providers (OAuth / subscription API keys) ---
        (
            "copilot",
            [
                "claude-sonnet-4-5-20250929",
                "gpt-4o",
                "o4-mini",
            ],
        ),
        (
            "codex",
            [
                "gpt-5.3-codex",
                "gpt-5.4",
                "gpt-5.4-mini",
                "gpt-5.2-codex",
            ],
        ),
        (
            "gemini-cli",
            [
                "gemini-3-pro-preview",
                "gemini-3-flash-preview",
            ],
        ),
        (
            "zai",
            [
                "glm-5",
            ],
        ),
        (
            "alibaba",
            [
                "qwen3.5-plus",
                "kimi-k2.5",
                "glm-5",
                "MiniMax-M2.5",
            ],
        ),
        (
            "minimax",
            [
                "MiniMax-M2.5",
            ],
        ),
        (
            "synthetic",
            [
                "qwen3-coder-480b",
            ],
        ),
        (
            "chutes",
            [
                "deepseek-ai/DeepSeek-V3-0324",
            ],
        ),
    ]
)

_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "zai": "ZAI_API_KEY",
    "alibaba": "ALIBABA_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "synthetic": "SYNTHETIC_API_KEY",
    "chutes": "CHUTES_API_KEY",
    # copilot, codex, gemini-cli use file-based credentials — handled separately
}

# Providers that use file-based credential stores instead of env vars
_FILE_CREDENTIAL_PROVIDERS = ("copilot", "codex", "gemini-cli")


def get_available_models() -> dict[str, list[str]]:
    """Get models grouped by provider.

    Returns:
        OrderedDict mapping provider name to list of model names.
    """
    return dict(_MODELS_BY_PROVIDER)


def has_provider_credentials(provider: str) -> bool | None:
    """Check if a provider has valid credentials.

    Args:
        provider: Provider name.

    Returns:
        True if key is set, False if not, None if provider is unknown.
    """
    if provider == "copilot":
        from embient.providers.copilot import CopilotCredentialStore

        return CopilotCredentialStore().has_github_token()
    if provider == "codex":
        from embient.providers.codex import CodexCredentialStore

        return CodexCredentialStore().has_credentials()
    if provider == "gemini-cli":
        from embient.providers.gemini import GeminiCredentialStore

        return GeminiCredentialStore().has_credentials()

    env_var = _PROVIDER_ENV_VARS.get(provider)
    if env_var is None:
        return None
    return bool(os.environ.get(env_var))
