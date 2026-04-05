"""MiniMax Coding Plan provider configuration.

MiniMax Token Plan ($10-50/mo) provides OpenAI-compatible access to M2.7
and M2.5 models through their API.
"""

from __future__ import annotations

import os

MINIMAX_GLOBAL_URL = "https://api.minimaxi.com/v1"
MINIMAX_CN_URL = "https://api.minimax.chat/v1"

DEFAULT_MINIMAX_MODEL = "MiniMax-M2.5"

_BASE_URLS: dict[str, str] = {
    "global": MINIMAX_GLOBAL_URL,
    "cn": MINIMAX_CN_URL,
}


def has_minimax_credentials() -> bool:
    return bool(os.environ.get("MINIMAX_API_KEY"))


def get_minimax_config() -> tuple[str, str, str] | None:
    """Resolve MiniMax Coding Plan connection parameters.

    Environment variables:
        ``MINIMAX_API_KEY``  — required
        ``MINIMAX_BASE_URL`` — optional, ``global`` (default) or ``cn``
        ``MINIMAX_MODEL``    — optional, default model override
    """
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return None

    raw_url = os.environ.get("MINIMAX_BASE_URL", "global")
    base_url = _BASE_URLS.get(raw_url, raw_url)

    model = os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL)
    return api_key, base_url, model
