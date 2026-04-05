"""Google Gemini CLI OAuth provider — Google AI Pro/Ultra subscription.

Uses standard Google OAuth 2.0 with PKCE to authenticate with a Google account
that has a Google AI Pro ($20/mo) or Ultra ($250/mo) subscription.  The OAuth
token is used with LangChain's ``ChatGoogleGenerativeAI`` for inference.

The client credentials are extracted from environment variables or from
an installed ``@google/gemini-cli-core`` package if available.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

from embient.providers.copilot import _safe_chmod

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"
CLOUDCODE_URL = "https://cloudcode-pa.googleapis.com"

REDIRECT_PORT = 8085
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/oauth2callback"
SCOPES = "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile"

DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"

_TOKEN_SAFETY_MARGIN_S = 5 * 60

# Fallback client credentials — users should set env vars or install gemini-cli
_DEFAULT_CLIENT_ID = ""
_DEFAULT_CLIENT_SECRET = ""


def _get_client_credentials() -> tuple[str, str]:
    """Resolve Google OAuth client credentials.

    Checks env vars first, then falls back to extracting from an installed
    ``@google/gemini-cli-core`` package.
    """
    import os

    client_id = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_SECRET", "")

    if client_id and client_secret:
        return client_id, client_secret

    # Try to extract from installed gemini-cli-core
    extracted = _extract_from_gemini_cli()
    if extracted:
        return extracted

    if not client_id or not client_secret:
        raise RuntimeError(
            "Google OAuth credentials not found.\n"
            "Set GEMINI_CLI_OAUTH_CLIENT_ID and GEMINI_CLI_OAUTH_CLIENT_SECRET,\n"
            "or install @google/gemini-cli globally: npm install -g @google/gemini-cli"
        )
    return client_id, client_secret


def _extract_from_gemini_cli() -> tuple[str, str] | None:
    """Try to extract OAuth credentials from an installed gemini-cli package."""
    import re
    import shutil

    npm_bin = shutil.which("npm")
    if not npm_bin:
        return None

    # Common locations for global npm modules
    search_paths = [
        Path.home() / ".nvm" / "versions",
        Path("/usr/lib/node_modules"),
        Path("/usr/local/lib/node_modules"),
        Path.home() / "node_modules",
    ]

    # Also check npm root -g
    try:
        import subprocess

        result = subprocess.run(  # noqa: S603
            [npm_bin, "root", "-g"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            search_paths.insert(0, Path(result.stdout.strip()))
    except Exception:
        pass

    oauth_file = "/@google/gemini-cli-core/dist/src/code_assist/oauth2.js"
    client_id_re = re.compile(r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)")
    client_secret_re = re.compile(r"(GOCSPX-[A-Za-z0-9_-]+)")

    for base in search_paths:
        candidate = base / oauth_file.lstrip("/")
        if not candidate.exists():
            # Also search recursively one level for nvm versions
            for child in base.glob("**/node_modules" + oauth_file):
                candidate = child
                break
            else:
                continue

        try:
            content = candidate.read_text()
            id_match = client_id_re.search(content)
            secret_match = client_secret_re.search(content)
            if id_match and secret_match:
                return id_match.group(1), secret_match.group(1)
        except Exception:
            continue

    return None


def _generate_pkce() -> tuple[str, str, str]:
    """Generate PKCE verifier, challenge, and state."""
    verifier = secrets.token_hex(32)
    challenge_bytes = hashlib.sha256(verifier.encode()).digest()
    import base64

    challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode()
    state = verifier  # used for CSRF validation
    return verifier, challenge, state


class GeminiCredentialStore:
    """Persists Google Gemini OAuth tokens on disk."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = base_dir or (Path.home() / ".embient" / "credentials")

    @property
    def _path(self) -> Path:
        return self._dir / "gemini-oauth.json"

    def save(
        self,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        email: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "email": email,
            "project_id": project_id,
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


def _exchange_code(auth_code: str, verifier: str) -> dict:
    """Exchange an authorization code for tokens."""
    client_id, client_secret = _get_client_credentials()
    data: dict[str, str] = {
        "client_id": client_id,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret

    with httpx.Client() as client:
        resp = client.post(GOOGLE_TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _refresh_tokens(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    client_id, client_secret = _get_client_credentials()
    data: dict[str, str] = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if client_secret:
        data["client_secret"] = client_secret

    with httpx.Client() as client:
        resp = client.post(GOOGLE_TOKEN_URL, data=data)
        if resp.status_code in (401, 403):
            raise RuntimeError("Gemini token refresh failed. Re-authenticate with: embient auth gemini")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]


def _get_user_email(access_token: str) -> str | None:
    try:
        with httpx.Client() as client:
            resp = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.is_success:
                return resp.json().get("email")
    except Exception:
        pass
    return None


class GeminiTokenManager:
    """Thread-safe manager that lazily refreshes the Gemini OAuth token."""

    def __init__(self, store: GeminiCredentialStore | None = None) -> None:
        self._store = store or GeminiCredentialStore()
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

        creds = self._store.load()
        if creds:
            self._access_token = creds["access_token"]
            self._refresh_token = creds["refresh_token"]
            self._expires_at = float(creds.get("expires_at", 0))

    def is_authenticated(self) -> bool:
        return self._store.has_credentials()

    def _is_usable(self) -> bool:
        return self._access_token is not None and (self._expires_at - time.time()) > _TOKEN_SAFETY_MARGIN_S

    def _refresh(self) -> str:
        if not self._refresh_token:
            creds = self._store.load()
            if not creds:
                raise RuntimeError("No Gemini credentials stored. Run: embient auth gemini")
            self._refresh_token = creds["refresh_token"]

        data = _refresh_tokens(self._refresh_token)
        self._access_token = data["access_token"]
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._expires_at = time.time() + expires_in

        self._store.save(self._access_token, self._refresh_token, self._expires_at)
        return self._access_token

    def get_token_sync(self) -> str:
        """Return a valid access token, refreshing if needed."""
        with self._lock:
            if self._is_usable():
                assert self._access_token is not None
                return self._access_token
            return self._refresh()

    async def get_token(self) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_token_sync)


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback code."""

    auth_code: str | None = None
    state: str | None = None

    def do_GET(self) -> None:
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Error: {error}</h1>".encode())
            return

        _OAuthCallbackHandler.auth_code = code
        _OAuthCallbackHandler.state = state

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Authenticated! You can close this tab.</h1>")

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress server logs


def gemini_login_interactive() -> None:
    """Run the Google Gemini CLI OAuth flow from the terminal."""
    from embient.config import console

    console.print()
    console.print("[bold]Google Gemini CLI Login (Google AI Pro/Ultra)[/bold]")
    console.print()

    try:
        client_id, _secret = _get_client_credentials()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    verifier, challenge, state = _generate_pkce()

    auth_url = f"{GOOGLE_AUTH_URL}?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
    )

    # Reset handler state
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.state = None

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _OAuthCallbackHandler)
    server.timeout = 300

    console.print("[dim]Opening browser for Google authentication...[/dim]")
    console.print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        console.print(f"  Open this URL in your browser:\n  [cyan]{auth_url}[/cyan]")
        console.print()

    console.print("[dim]Waiting for callback on localhost:8085...[/dim]")

    # Handle one request (the OAuth callback)
    server.handle_request()
    server.server_close()

    if not _OAuthCallbackHandler.auth_code:
        console.print("[red]No authorization code received.[/red]")
        return

    if _OAuthCallbackHandler.state != state:
        console.print("[red]State mismatch — possible CSRF attack.[/red]")
        return

    console.print("[green]Authorization code received.[/green]")
    console.print("[dim]Exchanging for tokens...[/dim]")

    try:
        token_data = _exchange_code(_OAuthCallbackHandler.auth_code, verifier)
    except Exception as exc:
        console.print(f"[red]Token exchange failed: {exc}[/red]")
        return

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = time.time() + expires_in

    email = _get_user_email(access_token)

    store = GeminiCredentialStore()
    store.save(access_token, refresh_token, expires_at, email=email)

    console.print()
    console.print("[bold green]Authenticated with Google Gemini.[/bold green]")
    if email:
        console.print(f"[dim]Account: {email}[/dim]")
    console.print()
    console.print("Use with:  [cyan]embient --provider gemini-cli[/cyan]")
    console.print("       or: [cyan]embient --model gemini-3-pro-preview[/cyan]")
    console.print()
