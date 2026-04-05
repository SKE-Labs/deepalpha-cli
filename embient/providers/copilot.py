"""GitHub Copilot subscription provider — OAuth device flow + token exchange.

Authentication is a two-step process:

1. **GitHub OAuth device flow** — the user authorises via ``github.com/login/device``
   and we receive a long-lived GitHub access token.
2. **Copilot token exchange** — the GitHub token is exchanged for a short-lived
   Copilot API token (~30 min) via ``api.github.com/copilot_internal/v2/token``.

At runtime the ``CopilotAuth`` httpx auth handler transparently refreshes the
Copilot API token before each LLM request so long agent sessions never hit an
expired-token error.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import webbrowser
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import httpx

CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"  # noqa: S105
DEFAULT_COPILOT_BASE_URL = "https://api.individual.githubcopilot.com"

_TOKEN_SAFETY_MARGIN_S = 5 * 60  # 5 minutes


def _safe_chmod(path: Path, mode: int = 0o600) -> None:
    """Set file permissions, ignoring errors on platforms that don't support it."""
    try:
        path.chmod(mode)
    except OSError:
        pass


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


class CopilotCredentialStore:
    """Persists GitHub and Copilot tokens on disk with restrictive permissions."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = base_dir or (Path.home() / ".embient" / "credentials")

    @property
    def _github_path(self) -> Path:
        return self._dir / "copilot-github.json"

    @property
    def _copilot_path(self) -> Path:
        return self._dir / "copilot-api.json"

    def save_github_token(self, token: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {"github_token": token, "created_at": time.time()}
        self._github_path.write_text(json.dumps(payload))
        _safe_chmod(self._github_path)

    def load_github_token(self) -> str | None:
        try:
            data = json.loads(self._github_path.read_text())
            return data.get("github_token")  # type: ignore[no-any-return]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def save_copilot_token(self, token: str, expires_at: float) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {"token": token, "expires_at": expires_at, "updated_at": time.time()}
        self._copilot_path.write_text(json.dumps(payload))
        _safe_chmod(self._copilot_path)

    def load_copilot_token(self) -> tuple[str, float] | None:
        try:
            data = json.loads(self._copilot_path.read_text())
            token = data["token"]
            expires_at = float(data["expires_at"])
            return token, expires_at
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def has_github_token(self) -> bool:
        return self._github_path.exists()

    def clear(self) -> None:
        for p in (self._github_path, self._copilot_path):
            p.unlink(missing_ok=True)


def request_device_code() -> DeviceCodeResponse:
    """Initiate the GitHub device-flow and return the device code payload."""
    with httpx.Client() as client:
        resp = client.post(
            DEVICE_CODE_URL,
            data={"client_id": CLIENT_ID, "scope": "read:user"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    return DeviceCodeResponse(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        interval=int(data.get("interval", 5)),
        expires_in=int(data.get("expires_in", 900)),
    )


def poll_for_access_token(device: DeviceCodeResponse) -> str:
    """Block until the user authorises and return the GitHub access token."""
    deadline = time.time() + device.expires_in
    interval = max(1, device.interval)

    with httpx.Client() as client:
        while time.time() < deadline:
            time.sleep(interval)
            resp = client.post(
                ACCESS_TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "device_code": device.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            if "access_token" in data:
                return data["access_token"]  # type: ignore[no-any-return]

            error = data.get("error", "")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                # RFC 8628 §3.5 — add 5 s to the interval
                interval = int(data.get("interval", interval + 5))
                continue
            if error == "expired_token":
                raise RuntimeError("GitHub device code expired — please try again.")
            if error == "access_denied":
                raise RuntimeError("GitHub login was cancelled by the user.")
            raise RuntimeError(f"GitHub device-flow error: {error}")

    raise RuntimeError("GitHub device code expired — please try again.")


def exchange_for_copilot_token(github_token: str) -> tuple[str, float]:
    """Exchange a GitHub token for a Copilot API token.

    Returns:
        ``(copilot_token, expires_at_epoch_seconds)``
    """
    with httpx.Client() as client:
        resp = client.get(
            COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/json",
            },
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                "Copilot token exchange failed (HTTP "
                f"{resp.status_code}). Your GitHub token may be revoked or you "
                "may not have an active Copilot subscription.\n"
                "Re-authenticate with: embient auth copilot"
            )
        resp.raise_for_status()
        data = resp.json()

    token = data.get("token")
    if not token:
        raise RuntimeError("Copilot token response missing 'token' field.")

    raw_exp = data.get("expires_at")
    if raw_exp is None:
        raise RuntimeError("Copilot token response missing 'expires_at' field.")

    expires_at = float(raw_exp)
    # GitHub returns epoch seconds but defensively handle milliseconds too
    if expires_at > 10_000_000_000:
        expires_at = expires_at / 1000.0

    return token, expires_at


def derive_base_url_from_token(token: str) -> str:
    """Extract the API base URL embedded in a Copilot token.

    The token is a semicolon-delimited set of key/value pairs. One of them is
    ``proxy-ep=<host>`` which we convert from ``proxy.*`` to ``api.*``.
    """
    match = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token, re.IGNORECASE)
    if not match:
        return DEFAULT_COPILOT_BASE_URL
    proxy_ep = match.group(1).strip()
    host = re.sub(r"^https?://", "", proxy_ep)
    host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
    return f"https://{host}" if host else DEFAULT_COPILOT_BASE_URL


class CopilotTokenManager:
    """Thread-safe manager that lazily refreshes the Copilot API token."""

    def __init__(self, store: CopilotCredentialStore | None = None) -> None:
        self._store = store or CopilotCredentialStore()
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._base_url: str = DEFAULT_COPILOT_BASE_URL

        cached = self._store.load_copilot_token()
        if cached:
            self._token, self._expires_at = cached
            self._base_url = derive_base_url_from_token(self._token)

    def is_authenticated(self) -> bool:
        return self._store.has_github_token()

    def _is_usable(self) -> bool:
        return self._token is not None and (self._expires_at - time.time()) > _TOKEN_SAFETY_MARGIN_S

    def _refresh(self) -> tuple[str, str]:
        """Refresh the token (caller holds self._lock)."""
        github_token = self._store.load_github_token()
        if not github_token:
            raise RuntimeError("No GitHub token stored. Run: embient auth copilot")

        token, expires_at = exchange_for_copilot_token(github_token)
        base_url = derive_base_url_from_token(token)

        self._token = token
        self._expires_at = expires_at
        self._base_url = base_url
        self._store.save_copilot_token(token, expires_at)
        return token, base_url

    def get_token_sync(self) -> tuple[str, str]:
        """Return ``(copilot_api_token, base_url)``, refreshing if needed."""
        with self._lock:
            if self._is_usable():
                assert self._token is not None
                return self._token, self._base_url
            return self._refresh()

    async def get_token(self) -> tuple[str, str]:
        """Async wrapper — runs the sync refresh in a thread to avoid blocking."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_token_sync)


class CopilotAuth(httpx.Auth):
    """Pluggable ``httpx.Auth`` that injects a fresh Copilot Bearer token
    and the required ``Openai-Intent`` header for the Copilot API."""

    def __init__(self, manager: CopilotTokenManager) -> None:
        self._manager = manager

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token, _ = self._manager.get_token_sync()
        request.headers["Authorization"] = f"Bearer {token}"
        request.headers["Openai-Intent"] = "conversation-edits"
        yield request

    async def async_auth_flow(self, request: httpx.Request):  # type: ignore[override]
        token, _ = await self._manager.get_token()
        request.headers["Authorization"] = f"Bearer {token}"
        request.headers["Openai-Intent"] = "conversation-edits"
        yield request


def copilot_login_interactive() -> None:
    """Run the full GitHub Copilot device-flow login from the terminal."""
    from embient.config import console

    console.print()
    console.print("[bold]GitHub Copilot Login[/bold]")
    console.print()

    console.print("[dim]Requesting device code from GitHub...[/dim]")
    device = request_device_code()

    console.print()
    console.print(f"  Visit:  [cyan]{device.verification_uri}[/cyan]")
    console.print(f"  Code:   [bold yellow]{device.user_code}[/bold yellow]")
    console.print()

    try:
        webbrowser.open(device.verification_uri)
        console.print("[dim]Browser opened. Waiting for authorisation...[/dim]")
    except Exception:
        console.print("[dim]Waiting for authorisation...[/dim]")

    github_token = poll_for_access_token(device)

    store = CopilotCredentialStore()
    store.save_github_token(github_token)
    console.print("[green]GitHub access token acquired.[/green]")

    console.print("[dim]Exchanging for Copilot API token...[/dim]")
    try:
        token, expires_at = exchange_for_copilot_token(github_token)
        store.save_copilot_token(token, expires_at)
        base_url = derive_base_url_from_token(token)
    except RuntimeError as exc:
        console.print(f"[red]Warning:[/red] {exc}")
        console.print("[yellow]GitHub token saved, but Copilot token exchange failed.[/yellow]")
        console.print("[yellow]Make sure you have an active GitHub Copilot subscription.[/yellow]")
        return

    console.print()
    console.print("[bold green]Authenticated with GitHub Copilot.[/bold green]")
    console.print(f"[dim]Base URL: {base_url}[/dim]")
    console.print()
    console.print("Use with:  [cyan]embient --provider copilot[/cyan]")
    console.print("       or: [cyan]embient --model copilot/claude-sonnet-4-5-20250929[/cyan]")
    console.print()
