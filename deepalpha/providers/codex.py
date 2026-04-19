"""OpenAI Codex subscription provider — OAuth for ChatGPT Plus/Pro.

Uses the device-code flow so the user authorises in a browser and the CLI
polls for completion.  The resulting access token is used to call the Codex
Responses API at ``chatgpt.com/backend-api/codex/responses``.

Tokens are automatically refreshed via the stored refresh token.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
import webbrowser
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import httpx

from deepalpha.providers.copilot import _safe_chmod

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
TOKEN_URL = f"{ISSUER}/oauth/token"
DEVICE_CODE_URL = f"{ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{ISSUER}/api/accounts/deviceauth/token"
DEVICE_VERIFY_URL = f"{ISSUER}/codex/device"

CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_CODEX_MODEL = "gpt-5.3-codex"

_TOKEN_SAFETY_MARGIN_S = 5 * 60


@dataclass
class DeviceCodeResponse:
    device_auth_id: str
    user_code: str
    interval: int


class CodexCredentialStore:
    """Persists Codex OAuth tokens on disk."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = base_dir or (Path.home() / ".deepalpha" / "credentials")

    @property
    def _path(self) -> Path:
        return self._dir / "codex-oauth.json"

    def save(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        account_id: str | None = None,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "account_id": account_id,
            "updated_at": time.time(),
        }
        self._path.write_text(json.dumps(payload))
        _safe_chmod(self._path)

    def load(self) -> dict | None:
        try:
            data = json.loads(self._path.read_text())
            if "access_token" in data and "refresh_token" in data:
                return data  # type: ignore[no-any-return]
            return None
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def has_credentials(self) -> bool:
        return self._path.exists()

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


def _extract_account_id(id_token: str) -> str | None:
    """Extract the ChatGPT account ID from a JWT id_token."""
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return None
        # Pad base64url to valid base64
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return (
            payload.get("chatgpt_account_id")
            or (payload.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
            or (payload.get("organizations") or [{}])[0].get("id")
        )
    except Exception:
        return None


def request_device_code() -> DeviceCodeResponse:
    """Request a device code for the OpenAI Codex device-auth flow."""
    with httpx.Client() as client:
        resp = client.post(
            DEVICE_CODE_URL,
            json={"client_id": CLIENT_ID},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    return DeviceCodeResponse(
        device_auth_id=data["device_auth_id"],
        user_code=data["user_code"],
        interval=int(data.get("interval", 5)),
    )


def poll_for_auth_code(device: DeviceCodeResponse, timeout: int = 300) -> tuple[str, str]:
    """Poll until the user authorises. Returns (authorization_code, code_verifier)."""
    deadline = time.time() + timeout
    interval = max(1, device.interval)

    with httpx.Client() as client:
        while time.time() < deadline:
            time.sleep(interval)
            resp = client.post(
                DEVICE_TOKEN_URL,
                json={
                    "device_auth_id": device.device_auth_id,
                    "user_code": device.user_code,
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["authorization_code"], data["code_verifier"]
            if resp.status_code == 403:
                raise RuntimeError("Device authorization was denied.")
            # 202 = still pending, keep polling

    raise RuntimeError("Device authorization timed out — please try again.")


def exchange_code_for_tokens(
    auth_code: str,
    code_verifier: str,
) -> dict:
    """Exchange an authorization code for OAuth tokens.

    Returns dict with ``access_token``, ``refresh_token``, ``expires_in``,
    and optionally ``id_token``.
    """
    with httpx.Client() as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": f"{ISSUER}/deviceauth/callback",
                "client_id": CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Codex token exchange failed (HTTP {resp.status_code}).")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def refresh_tokens(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    with httpx.Client() as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code in (401, 403):
            raise RuntimeError("Codex token refresh failed. Re-authenticate with: deepalpha auth codex")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


class CodexTokenManager:
    """Thread-safe manager that lazily refreshes the Codex OAuth token."""

    def __init__(self, store: CodexCredentialStore | None = None) -> None:
        self._store = store or CodexCredentialStore()
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._account_id: str | None = None

        creds = self._store.load()
        if creds:
            self._access_token = creds["access_token"]
            self._refresh_token = creds["refresh_token"]
            self._expires_at = float(creds.get("expires_at", 0))
            self._account_id = creds.get("account_id")

    def is_authenticated(self) -> bool:
        return self._store.has_credentials()

    def _is_usable(self) -> bool:
        return self._access_token is not None and (self._expires_at - time.time()) > _TOKEN_SAFETY_MARGIN_S

    def _refresh(self) -> str:
        """Refresh the token (caller holds self._lock)."""
        if not self._refresh_token:
            creds = self._store.load()
            if not creds:
                raise RuntimeError("No Codex credentials stored. Run: deepalpha auth codex")
            self._refresh_token = creds["refresh_token"]

        data = refresh_tokens(self._refresh_token)
        self._access_token = data["access_token"]
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._expires_at = time.time() + expires_in

        if "id_token" in data:
            acct = _extract_account_id(data["id_token"])
            if acct:
                self._account_id = acct

        self._store.save(
            self._access_token,
            self._refresh_token,
            self._expires_at,
            self._account_id,
        )
        return self._access_token

    def get_token_sync(self) -> tuple[str, str | None]:
        """Return ``(access_token, account_id)``, refreshing if needed."""
        with self._lock:
            if self._is_usable():
                assert self._access_token is not None
                return self._access_token, self._account_id
            token = self._refresh()
            return token, self._account_id

    async def get_token(self) -> tuple[str, str | None]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_token_sync)


class CodexAuth(httpx.Auth):
    """Pluggable ``httpx.Auth`` that injects a fresh Codex Bearer token
    and rewrites the URL to the Codex Responses API endpoint."""

    def __init__(self, manager: CodexTokenManager) -> None:
        self._manager = manager

    def _apply(self, request: httpx.Request, token: str, account_id: str | None) -> None:
        request.headers["Authorization"] = f"Bearer {token}"
        if account_id:
            request.headers["ChatGPT-Account-Id"] = account_id
        # Rewrite chat/completions and responses URLs to the Codex endpoint
        url_str = str(request.url)
        if "/chat/completions" in url_str or "/v1/responses" in url_str:
            request.url = httpx.URL(CODEX_API_URL)

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token, account_id = self._manager.get_token_sync()
        self._apply(request, token, account_id)
        yield request

    async def async_auth_flow(self, request: httpx.Request):  # type: ignore[override]
        token, account_id = await self._manager.get_token()
        self._apply(request, token, account_id)
        yield request


def codex_login_interactive() -> None:
    """Run the OpenAI Codex device-code login from the terminal."""
    from deepalpha.config import console

    console.print()
    console.print("[bold]OpenAI Codex Login (ChatGPT Plus/Pro)[/bold]")
    console.print()

    console.print("[dim]Requesting device code from OpenAI...[/dim]")
    device = request_device_code()

    console.print()
    console.print(f"  Visit:  [cyan]{DEVICE_VERIFY_URL}[/cyan]")
    console.print(f"  Code:   [bold yellow]{device.user_code}[/bold yellow]")
    console.print()

    try:
        webbrowser.open(DEVICE_VERIFY_URL)
        console.print("[dim]Browser opened. Waiting for authorisation...[/dim]")
    except Exception:
        console.print("[dim]Waiting for authorisation...[/dim]")

    auth_code, code_verifier = poll_for_auth_code(device)
    console.print("[green]Device authorised.[/green]")

    console.print("[dim]Exchanging for tokens...[/dim]")
    token_data = exchange_code_for_tokens(auth_code, code_verifier)

    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = time.time() + expires_in

    account_id = None
    if "id_token" in token_data:
        account_id = _extract_account_id(token_data["id_token"])

    store = CodexCredentialStore()
    store.save(access_token, refresh_token, expires_at, account_id)

    console.print()
    console.print("[bold green]Authenticated with OpenAI Codex.[/bold green]")
    if account_id:
        console.print(f"[dim]Account: {account_id}[/dim]")
    console.print()
    console.print("Use with:  [cyan]deepalpha --provider codex[/cyan]")
    console.print("       or: [cyan]deepalpha --model codex/gpt-5.3-codex[/cyan]")
    console.print()
