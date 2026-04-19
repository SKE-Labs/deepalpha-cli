"""Z.AI subscription provider configuration.

Z.AI exposes an OpenAI-compatible API. This module resolves the API key
and base URL from environment variables so ``create_model`` can wire them
into LangChain's ``ChatOpenAI``.
"""

from __future__ import annotations

import os

# Base URL variants — the "coding" endpoints are optimised for code tasks.
ZAI_CODING_GLOBAL_URL = "https://api.z.ai/api/coding/paas/v4"
ZAI_CODING_CN_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
ZAI_GLOBAL_URL = "https://api.z.ai/api/paas/v4"
ZAI_CN_URL = "https://open.bigmodel.cn/api/paas/v4"

DEFAULT_ZAI_MODEL = "glm-5"

_BASE_URLS: dict[str, str] = {
    "coding-global": ZAI_CODING_GLOBAL_URL,
    "coding-cn": ZAI_CODING_CN_URL,
    "global": ZAI_GLOBAL_URL,
    "cn": ZAI_CN_URL,
}


def has_zai_credentials() -> bool:
    """Return True if a Z.AI API key is available."""
    return bool(os.environ.get("ZAI_API_KEY"))


def get_zai_config() -> tuple[str, str, str] | None:
    """Resolve Z.AI connection parameters from the environment.

    Returns:
        ``(api_key, base_url, default_model)`` or ``None`` when no key is set.

    Environment variables:
        ``ZAI_API_KEY``  — required
        ``ZAI_BASE_URL`` — optional, one of ``coding-global`` (default),
                           ``coding-cn``, ``global``, ``cn``, or a full URL.
        ``ZAI_MODEL``    — optional, default model name override.
    """
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        return None

    raw_url = os.environ.get("ZAI_BASE_URL", "coding-global")
    base_url = _BASE_URLS.get(raw_url, raw_url)

    model = os.environ.get("ZAI_MODEL", DEFAULT_ZAI_MODEL)
    return api_key, base_url, model
