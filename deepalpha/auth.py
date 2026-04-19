"""Authentication module for DeepAlpha CLI.

Provides Supabase CLI-style authentication with browser-based login
and manual token entry. Uses server-managed CLI session tokens.

Usage:
    # Login
    deepalpha login

    # Check auth status
    deepalpha status

    # Logout
    deepalpha logout
"""

import json
import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console
from rich.prompt import Prompt

console = Console()

# Default URLs
DEFAULT_FRONTEND_URL = "https://deepalpha.mn"
DEFAULT_BASEMENT_API = "https://basement.deepalpha.mn"


def get_deepalpha_dir() -> Path:
    """Get the .deepalpha directory path, creating it if needed."""
    deepalpha_dir = Path.home() / ".deepalpha"
    deepalpha_dir.mkdir(parents=True, exist_ok=True)
    return deepalpha_dir


def get_credentials_path() -> Path:
    """Get the path to the credentials file."""
    return get_deepalpha_dir() / "credentials.json"


@dataclass
class Credentials:
    """Stored authentication credentials.

    Uses CLI session tokens (managed by server) instead of Supabase JWTs.
    Sessions last 30 days and can be revoked from the web dashboard.
    """

    cli_token: str  # Server-managed CLI session token
    user_id: str | None
    email: str | None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "cli_token": self.cli_token,
            "user_id": self.user_id,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Credentials":
        """Create from dictionary."""
        return cls(
            cli_token=data.get("cli_token", ""),
            user_id=data.get("user_id"),
            email=data.get("email"),
        )


def save_credentials(credentials: Credentials) -> None:
    """Save credentials to the credentials file.

    Args:
        credentials: Credentials object to save
    """
    creds_path = get_credentials_path()
    # Ensure parent directory exists
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    # Write with restrictive permissions
    creds_path.write_text(json.dumps(credentials.to_dict(), indent=2))
    # Set file permissions to owner-only (Unix)
    try:
        os.chmod(creds_path, 0o600)
    except OSError:
        pass  # Windows doesn't support chmod


def load_credentials() -> Credentials | None:
    """Load credentials from the credentials file.

    Returns:
        Credentials object if found and valid, None otherwise
    """
    creds_path = get_credentials_path()
    if not creds_path.exists():
        return None

    try:
        data = json.loads(creds_path.read_text())
        credentials = Credentials.from_dict(data)
        # Check if token exists
        if not credentials.cli_token:
            return None
        return credentials
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def clear_credentials() -> bool:
    """Remove stored credentials.

    Returns:
        True if credentials were removed, False if none existed
    """
    creds_path = get_credentials_path()
    if creds_path.exists():
        creds_path.unlink()
        return True
    return False


def is_authenticated() -> bool:
    """Check if user is authenticated with valid credentials.

    Note: Server-managed sessions don't expire locally. The server will
    return 401 if the session is invalid/expired.

    Returns:
        True if authenticated with valid token, False otherwise
    """
    credentials = load_credentials()
    return credentials is not None and bool(credentials.cli_token)


def get_cli_token() -> str | None:
    """Get the stored CLI session token if authenticated.

    Returns:
        CLI token string if authenticated, None otherwise
    """
    credentials = load_credentials()
    if not credentials:
        return None
    return credentials.cli_token


# Keep get_jwt_token as an alias for backwards compatibility
get_jwt_token = get_cli_token


def validate_token(token: str) -> bool:
    """Validate a CLI token by making a test request to the API.

    Args:
        token: The CLI token to validate

    Returns:
        True if valid, False otherwise
    """
    basement_api = os.environ.get("BASEMENT_API", DEFAULT_BASEMENT_API)

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{basement_api}/api/v1/profiles/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 200:
                return True
            console.print(f"[dim]Server returned {response.status_code}[/dim]")
            return False
    except Exception as e:
        console.print(f"[dim]Validation error: {e}[/dim]")
        return False


def login_interactive(frontend_url: str | None = None) -> bool:
    """Perform interactive browser-based login.

    Opens browser to frontend auth URL and prompts user to paste the token.

    Args:
        frontend_url: Optional frontend URL override

    Returns:
        True if login successful, False otherwise
    """
    base_url = frontend_url or os.environ.get("DEEPALPHA_FRONTEND_URL", DEFAULT_FRONTEND_URL)

    # Build auth URL - pointing to frontend CLI auth page
    auth_url = f"{base_url}/auth/cli"

    console.print("\n[bold]Opening browser for authentication...[/bold]")
    console.print(f"[dim]If browser doesn't open, visit:[/dim]\n{auth_url}\n")

    # Open browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        console.print("[yellow]Could not open browser automatically.[/yellow]")
        console.print(f"Please open this URL manually:\n{auth_url}")

    console.print()
    console.print("[bold]After signing in, copy the verification code from the browser.[/bold]")
    console.print()

    # Prompt for token
    token = Prompt.ask("Enter verification code")

    if not token or not token.strip():
        console.print("\n[red]No token provided.[/red]")
        return False

    token = token.strip()

    # Validate the token
    console.print("\n[dim]Validating token...[/dim]")

    if not validate_token(token):
        console.print("\n[red]Invalid or expired token.[/red]")
        console.print("[dim]Please try again with a valid token.[/dim]")
        return False

    # Save credentials
    credentials = Credentials(
        cli_token=token,
        user_id=None,  # We don't have this from the token entry flow
        email=None,
    )
    save_credentials(credentials)

    console.print("\n[green]Successfully authenticated![/green]")

    return True


def login_with_token(token: str) -> bool:
    """Login with a provided CLI token (for automation/testing).

    Args:
        token: CLI session token to use

    Returns:
        True if token was saved successfully
    """
    credentials = Credentials(
        cli_token=token,
        user_id=None,
        email=None,
    )
    save_credentials(credentials)
    return True


async def revoke_session(cli_token: str) -> bool:
    """Revoke the CLI session on the server.

    Args:
        cli_token: The CLI token to revoke

    Returns:
        True if revoked successfully, False otherwise
    """
    basement_api = os.environ.get("BASEMENT_API", DEFAULT_BASEMENT_API)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{basement_api}/api/v1/auth/cli-session",
                headers={"Authorization": f"Bearer {cli_token}"},
            )
            return response.status_code == 200
    except Exception as e:
        console.print(f"[yellow]Warning: Could not revoke server session: {e}[/yellow]")
        return False


async def login_command() -> None:
    """CLI handler for: deepalpha login."""
    if is_authenticated():
        credentials = load_credentials()
        console.print("[yellow]Already authenticated.[/yellow]")
        if credentials and credentials.email:
            console.print(f"[dim]Logged in as:[/dim] {credentials.email}")
        console.print("[dim]Use 'deepalpha logout' to sign out first.[/dim]")
        return

    success = login_interactive()
    if not success:
        sys.exit(1)


async def logout_command() -> None:
    """CLI handler for: deepalpha logout.

    Clears local credentials and revokes the server session.
    """
    credentials = load_credentials()

    # Revoke server session if we have a token
    if credentials and credentials.cli_token:
        console.print("[dim]Revoking server session...[/dim]")
        await revoke_session(credentials.cli_token)

    # Clear local credentials
    if clear_credentials():
        console.print("[green]Successfully logged out.[/green]")
    else:
        console.print("[yellow]No credentials found.[/yellow]")


async def status_command() -> None:
    """CLI handler for: deepalpha status."""
    credentials = load_credentials()

    if not credentials:
        console.print("[yellow]Not authenticated[/yellow]")
        console.print("[dim]Run 'deepalpha login' to authenticate.[/dim]")
        return

    console.print("[green]Authenticated[/green]")
    if credentials.email:
        console.print(f"[dim]Email:[/dim] {credentials.email}")
    if credentials.user_id:
        console.print(f"[dim]User ID:[/dim] {credentials.user_id}")
    console.print("[dim]Session:[/dim] CLI token (server-managed)")
