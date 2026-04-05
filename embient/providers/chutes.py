"""Chutes.ai subscription provider configuration.

Chutes ($3+/mo) provides OpenAI-compatible access to various open-source and
frontier models with subscription-based rate limits.
"""

from __future__ import annotations

import os

CHUTES_BASE_URL = "https://llm.chutes.ai/v1"

DEFAULT_CHUTES_MODEL = "deepseek-ai/DeepSeek-V3-0324"


def has_chutes_credentials() -> bool:
    return bool(os.environ.get("CHUTES_API_KEY"))


def get_chutes_config() -> tuple[str, str, str] | None:
    """Resolve Chutes.ai connection parameters.

    Environment variables:
        ``CHUTES_API_KEY``  — required
        ``CHUTES_BASE_URL`` — optional, full URL override
        ``CHUTES_MODEL``    — optional, default model override
    """
    api_key = os.environ.get("CHUTES_API_KEY")
    if not api_key:
        return None

    base_url = os.environ.get("CHUTES_BASE_URL", CHUTES_BASE_URL)
    model = os.environ.get("CHUTES_MODEL", DEFAULT_CHUTES_MODEL)
    return api_key, base_url, model
