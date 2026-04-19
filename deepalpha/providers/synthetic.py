"""Synthetic.new subscription provider configuration.

Synthetic ($20-60/mo) provides OpenAI-compatible access to various open-source
coding LLMs (Qwen3 Coder, Kimi K2, GLM-4.5, DeepSeek, etc.).
"""

from __future__ import annotations

import os

SYNTHETIC_BASE_URL = "https://api.synthetic.new/v1"

DEFAULT_SYNTHETIC_MODEL = "qwen3-coder-480b"


def has_synthetic_credentials() -> bool:
    return bool(os.environ.get("SYNTHETIC_API_KEY"))


def get_synthetic_config() -> tuple[str, str, str] | None:
    """Resolve Synthetic.new connection parameters.

    Environment variables:
        ``SYNTHETIC_API_KEY``  — required
        ``SYNTHETIC_BASE_URL`` — optional, full URL override
        ``SYNTHETIC_MODEL``    — optional, default model override
    """
    api_key = os.environ.get("SYNTHETIC_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("SYNTHETIC_BASE_URL", SYNTHETIC_BASE_URL)
    model = os.environ.get("SYNTHETIC_MODEL", DEFAULT_SYNTHETIC_MODEL)
    return api_key, base_url, model
