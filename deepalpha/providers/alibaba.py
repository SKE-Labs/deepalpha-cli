"""Alibaba Cloud AI Coding Plan provider configuration.

Alibaba's Coding Plan ($50/mo) provides OpenAI-compatible access to multiple
models (Qwen3.5-Plus, Kimi K2.5, GLM-5, MiniMax M2.5) through DashScope.
"""

from __future__ import annotations

import os

ALIBABA_GLOBAL_URL = "https://coding-intl.dashscope.aliyuncs.com/v1"
ALIBABA_CN_URL = "https://coding.dashscope.aliyuncs.com/v1"

DEFAULT_ALIBABA_MODEL = "qwen3.5-plus"

_BASE_URLS: dict[str, str] = {
    "global": ALIBABA_GLOBAL_URL,
    "cn": ALIBABA_CN_URL,
}


def has_alibaba_credentials() -> bool:
    return bool(os.environ.get("ALIBABA_API_KEY"))


def get_alibaba_config() -> tuple[str, str, str] | None:
    """Resolve Alibaba Coding Plan connection parameters.

    Environment variables:
        ``ALIBABA_API_KEY``  — required (format ``sk-sp-xxxxx``)
        ``ALIBABA_BASE_URL`` — optional, ``global`` (default) or ``cn``
        ``ALIBABA_MODEL``    — optional, default model override
    """
    api_key = os.environ.get("ALIBABA_API_KEY")
    if not api_key:
        return None

    raw_url = os.environ.get("ALIBABA_BASE_URL", "global")
    base_url = _BASE_URLS.get(raw_url, raw_url)

    model = os.environ.get("ALIBABA_MODEL", DEFAULT_ALIBABA_MODEL)
    return api_key, base_url, model
