"""Request context variables for DeepAlpha CLI.

Provides context variables for storing session-scoped data
that needs to be accessible from tools and middleware during agent execution.

Usage:
    # At CLI startup (e.g., main.py)
    from deepalpha.context import set_auth_token, set_thread_id, set_user_profile

    set_auth_token(cli_token)
    set_thread_id(thread_id)
    set_user_profile(user_profile)

    # In tools/middleware
    from deepalpha.context import get_auth_token, get_thread_id, get_user_profile

    auth_token = get_auth_token()
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepalpha.spawns.manager import SpawnManager

# Auth token for authenticated API calls (CLI session token)
_auth_token_context: ContextVar[str | None] = ContextVar("auth_token", default=None)

# Thread ID for conversation tracking
_thread_id_context: ContextVar[str | None] = ContextVar("thread_id", default=None)

# User profile data (account balance, risk settings, etc.)
_user_profile_context: ContextVar[dict | None] = ContextVar("user_profile", default=None)


# Screenshots captured via HITL (e.g., chart screenshots from request_chart_screenshot)
_screenshots_context: ContextVar[list | None] = ContextVar("screenshots", default=None)

# SpawnManager instance for spawn tools
_spawn_manager_context: ContextVar[SpawnManager | None] = ContextVar("spawn_manager", default=None)


# Auth Token (CLI session token)
def set_auth_token(token: str) -> None:
    """Set the auth token for the current session context."""
    _auth_token_context.set(token)


def get_auth_token() -> str | None:
    """Get the auth token from the current session context."""
    return _auth_token_context.get()


# Backwards compatibility aliases
set_jwt_token = set_auth_token
get_jwt_token = get_auth_token


# Thread ID
def set_thread_id(thread_id: str) -> None:
    """Set the thread ID for the current session context."""
    _thread_id_context.set(thread_id)


def get_thread_id() -> str | None:
    """Get the thread ID from the current session context."""
    return _thread_id_context.get()


# User Profile
def set_user_profile(profile: dict) -> None:
    """Set the user profile for the current session context."""
    _user_profile_context.set(profile)


def get_user_profile() -> dict | None:
    """Get the user profile from the current session context."""
    return _user_profile_context.get()


# Screenshots (HITL-captured chart screenshots)
def set_screenshots(images: list) -> None:
    """Set the screenshots for the current session context.

    These are typically captured via HITL when the user responds to
    a request_chart_screenshot tool call.
    """
    _screenshots_context.set(images)


def get_screenshots() -> list | None:
    """Get the screenshots from the current session context."""
    return _screenshots_context.get()


# SpawnManager
def set_spawn_manager(manager: SpawnManager) -> None:
    """Set the SpawnManager instance for spawn tools to access."""
    _spawn_manager_context.set(manager)


def get_spawn_manager() -> SpawnManager | None:
    """Get the SpawnManager instance from context."""
    return _spawn_manager_context.get()


__all__ = [
    # Setters (for CLI startup)
    "set_auth_token",
    "set_jwt_token",  # Backwards compatibility
    "set_thread_id",
    "set_user_profile",
    "set_screenshots",
    "set_spawn_manager",
    # Getters (for tools/middleware)
    "get_auth_token",
    "get_jwt_token",  # Backwards compatibility
    "get_thread_id",
    "get_user_profile",
    "get_screenshots",
    "get_spawn_manager",
]
