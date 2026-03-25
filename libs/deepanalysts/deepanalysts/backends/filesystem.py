"""Local filesystem backend for reading files directly from disk.

This backend reads files from the local filesystem. When ``virtual_mode=True``,
path traversal (``..``, ``~``) is blocked and all resolved paths are verified
to stay within the root directory.

Security Warning:
    This backend grants agents direct filesystem read/write access.
    For web servers / HTTP APIs, prefer ``StoreBackend`` or a sandboxed backend.
    Use Human-in-the-Loop (HITL) middleware to review sensitive operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import wcmatch.glob as wcglob

from deepanalysts.backends.protocol import (
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileOperationError,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from deepanalysts.backends.utils import check_empty_content, perform_string_replacement

logger = logging.getLogger(__name__)


def _map_exception_to_standard_error(exc: Exception) -> FileOperationError | None:
    """Map an exception to a standardized ``FileOperationError`` code.

    Returns ``None`` for unrecognized exceptions.
    """
    if isinstance(exc, FileNotFoundError):
        return "file_not_found"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, IsADirectoryError):
        return "is_directory"
    if isinstance(exc, (NotADirectoryError, FileExistsError, ValueError)):
        return "invalid_path"
    return None


class LocalFilesystemBackend(BackendProtocol):
    """Backend that reads/writes files directly to the local filesystem.

    Unlike RestrictedSubprocessBackend, this has no process sandboxing — it
    operates directly on the local filesystem. Use for loading memories, skills,
    and configuration files.

    When ``virtual_mode=True``:
    - All paths are treated as virtual paths under ``root``.
    - Path traversal (``..``, ``~``) is blocked.
    - Resolved paths are verified to stay within ``root``.

    When ``virtual_mode=False`` (default):
    - Absolute paths are used as-is; relative paths resolve under ``root``.
    - No security guardrails.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        root_dir: str | Path | None = None,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the filesystem backend.

        Args:
            root: Optional root directory. If provided, all paths are relative to this.
                  If None, paths are treated as absolute or relative to cwd.
            root_dir: Alias for root (for backwards compatibility).
            virtual_mode: If True, paths are treated as virtual under root.
                Traversal (``..``, ``~``) is blocked and resolved paths verified.
            max_file_size_mb: Maximum file size in MB for grep Python fallback.
                Files exceeding this are skipped. Defaults to 10 MB.
        """
        effective_root = root or root_dir
        self._root = Path(effective_root).expanduser().resolve() if effective_root else None
        self._virtual_mode = virtual_mode
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path with security checks.

        When ``virtual_mode=True``, blocks traversal and verifies the resolved
        path stays within root. When ``virtual_mode=False``, absolute paths
        are used as-is and relative paths resolve under root.

        Raises:
            ValueError: If path traversal is attempted in virtual_mode or
                resolved path escapes root.
        """
        if self._virtual_mode:
            vpath = path if path.startswith("/") else "/" + path
            if ".." in vpath or vpath.startswith("~"):
                msg = "Path traversal not allowed"
                raise ValueError(msg)
            root = self._root or Path.cwd()
            full = (root / vpath.lstrip("/")).resolve()
            try:
                full.relative_to(root)
            except ValueError:
                msg = f"Path:{full} outside root directory: {root}"
                raise ValueError(msg) from None
            return full

        p = Path(path).expanduser()
        if self._root and not p.is_absolute():
            return self._root / p
        return p.resolve()

    def _to_virtual_path(self, path: Path) -> str:
        """Convert a filesystem path to a virtual path relative to root.

        Returns:
            Forward-slash relative path string prefixed with ``/``.

        Raises:
            ValueError: If path is outside root.
        """
        root = self._root or Path.cwd()
        return "/" + path.resolve().relative_to(root).as_posix()

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files in a directory.

        Args:
            path: Directory path to list.

        Returns:
            List of FileInfo dicts with path, is_dir, size, modified_at.
        """
        resolved = self._resolve_path(path)
        if not resolved.exists() or not resolved.is_dir():
            return []

        results: list[FileInfo] = []
        try:
            for entry in resolved.iterdir():
                try:
                    is_file = entry.is_file()
                    is_dir = entry.is_dir()
                except OSError:
                    continue

                if self._virtual_mode:
                    try:
                        display_path = self._to_virtual_path(entry)
                    except (ValueError, OSError):
                        continue
                else:
                    display_path = str(entry)

                if is_dir:
                    display_path += "/"

                info: FileInfo = {"path": display_path, "is_dir": is_dir}
                try:
                    st = entry.stat()
                    info["size"] = int(st.st_size) if is_file else 0
                    info["modified_at"] = datetime.fromtimestamp(st.st_mtime).isoformat()
                except OSError:
                    pass
                results.append(info)
        except (OSError, PermissionError):
            pass

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers.

        Uses ``os.open`` with ``O_NOFOLLOW`` where available to prevent
        symlink following.

        Args:
            file_path: Path to file.
            offset: Line number to start from (0-indexed).
            limit: Max lines to read.

        Returns:
            File content with line numbers, or error message.
        """
        try:
            resolved = self._resolve_path(file_path)
        except ValueError as e:
            return f"Error: {e}"

        if not resolved.exists():
            return f"Error: File '{file_path}' not found"
        if not resolved.is_file():
            return f"Error: '{file_path}' is not a file"

        try:
            fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except PermissionError:
            return f"Error: Permission denied reading '{file_path}'"
        except OSError as e:
            return f"Error reading file '{file_path}': {e}"

        empty_msg = check_empty_content(content)
        if empty_msg:
            return empty_msg

        lines = content.splitlines()
        selected = lines[offset : offset + limit]

        if not selected and offset >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

        output_lines = []
        for i, line in enumerate(selected):
            line_num = offset + i + 1
            output_lines.append(f"{line_num:6d}\t{line}")

        return "\n".join(output_lines)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write content to a new file.

        Uses ``os.open`` with ``O_NOFOLLOW`` where available to prevent
        writing through symlinks.

        Args:
            file_path: Path to create.
            content: Content to write.

        Returns:
            WriteResult with path or error.
        """
        try:
            resolved = self._resolve_path(file_path)
        except ValueError as e:
            return WriteResult(error=str(e))

        if resolved.exists():
            return WriteResult(error=f"Error: File '{file_path}' already exists")

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)

            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved, flags, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            return WriteResult(path=str(resolved))
        except PermissionError:
            return WriteResult(error=f"Error: Permission denied writing '{file_path}'")
        except OSError as e:
            return WriteResult(error=f"Error writing file '{file_path}': {e}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing string.

        Uses ``os.open`` with ``O_NOFOLLOW`` for both read and write.

        Args:
            file_path: Path to file.
            old_string: String to find.
            new_string: Replacement string.
            replace_all: Replace all occurrences.

        Returns:
            EditResult with path and count, or error.
        """
        try:
            resolved = self._resolve_path(file_path)
        except ValueError as e:
            return EditResult(error=str(e))

        if not resolved.exists():
            return EditResult(error=f"Error: File '{file_path}' not found")

        try:
            fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                content = f.read()
        except PermissionError:
            return EditResult(error=f"Error: Permission denied reading '{file_path}'")
        except OSError as e:
            return EditResult(error=f"Error reading file '{file_path}': {e}")

        result = perform_string_replacement(content, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result

        try:
            flags = os.O_WRONLY | os.O_TRUNC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(resolved, flags)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
        except PermissionError:
            return EditResult(error=f"Error: Permission denied writing '{file_path}'")
        except OSError as e:
            return EditResult(error=f"Error writing file '{file_path}': {e}")

        return EditResult(path=str(resolved), occurrences=int(occurrences))

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for literal text pattern in files.

        Tries ripgrep first (``rg -F`` for literal mode), falls back to
        Python search with ``max_file_size_bytes`` protection.

        Args:
            pattern: Literal string to search.
            path: Directory to search in.
            glob: File pattern to match.

        Returns:
            List of matches or error string.
        """
        try:
            search_path = self._resolve_path(path or ".")
        except ValueError:
            return []

        if not search_path.exists():
            return []

        # Try ripgrep first
        rg_results = self._ripgrep_search(pattern, search_path, glob)
        if rg_results is not None:
            return self._results_to_matches(rg_results)

        # Python fallback with max_file_size protection
        py_results = self._python_search(re.escape(pattern), search_path, glob)
        return self._results_to_matches(py_results)

    def _ripgrep_search(
        self, pattern: str, base: Path, include_glob: str | None
    ) -> dict[str, list[tuple[int, str]]] | None:
        """Search using ripgrep with fixed-string (literal) mode.

        Returns None if ripgrep is unavailable or times out.
        """
        cmd = ["rg", "--json", "-F"]
        if include_glob:
            cmd.extend(["--glob", include_glob])
        cmd.extend(["--", pattern, str(base)])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        results: dict[str, list[tuple[int, str]]] = {}
        for line in proc.stdout.splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("type") != "match":
                continue
            pdata = data.get("data", {})
            ftext = pdata.get("path", {}).get("text")
            if not ftext:
                continue

            p = Path(ftext)
            if self._virtual_mode:
                try:
                    display = self._to_virtual_path(p)
                except (ValueError, OSError):
                    continue
            else:
                display = str(p)

            ln = pdata.get("line_number")
            lt = pdata.get("lines", {}).get("text", "").rstrip("\n")
            if ln is None:
                continue
            results.setdefault(display, []).append((int(ln), lt))

        return results

    def _python_search(
        self, escaped_pattern: str, base: Path, include_glob: str | None
    ) -> dict[str, list[tuple[int, str]]]:
        """Fallback search using Python. Skips files exceeding max_file_size_bytes."""
        regex = re.compile(escaped_pattern)
        results: dict[str, list[tuple[int, str]]] = {}
        root = base if base.is_dir() else base.parent

        for fp in root.rglob("*"):
            try:
                if not fp.is_file():
                    continue
            except (PermissionError, OSError):
                continue

            if include_glob:
                rel = str(fp.relative_to(root))
                if not wcglob.globmatch(rel, include_glob, flags=wcglob.BRACE | wcglob.GLOBSTAR):
                    continue

            try:
                if fp.stat().st_size > self._max_file_size_bytes:
                    continue
            except OSError:
                continue

            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            if self._virtual_mode:
                try:
                    display = self._to_virtual_path(fp)
                except (ValueError, OSError):
                    continue
            else:
                display = str(fp)

            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    results.setdefault(display, []).append((line_num, line))

        return results

    def _results_to_matches(self, results: dict[str, list[tuple[int, str]]]) -> list[GrepMatch]:
        """Convert search results dict to list of GrepMatch."""
        matches: list[GrepMatch] = []
        for fpath, items in results.items():
            for line_num, line_text in items:
                matches.append({"path": fpath, "line": int(line_num), "text": line_text})
        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern.
            path: Base path.

        Returns:
            List of matching FileInfo.
        """
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        if self._virtual_mode and ".." in Path(pattern).parts:
            return []

        try:
            search_path = self._resolve_path(path)
        except ValueError:
            return []

        if not search_path.exists():
            return []

        results: list[FileInfo] = []
        try:
            for match in search_path.rglob(pattern):
                try:
                    if not match.is_file():
                        continue
                except (PermissionError, OSError):
                    continue

                if self._virtual_mode:
                    try:
                        display = self._to_virtual_path(match)
                    except (ValueError, OSError):
                        continue
                else:
                    display = str(match)

                info: FileInfo = {"path": display, "is_dir": False}
                try:
                    st = match.stat()
                    info["size"] = int(st.st_size)
                    info["modified_at"] = datetime.fromtimestamp(st.st_mtime).isoformat()
                except OSError:
                    pass
                results.append(info)
        except (OSError, ValueError):
            pass

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def execute(self, command: str, timeout: int = 120) -> ExecuteResponse:
        """Execute a shell command.

        Uses restricted environment (PATH, HOME, TMPDIR, LANG only).

        Args:
            command: Shell command string to execute.
            timeout: Maximum execution time in seconds (default 120).

        Returns:
            ExecuteResponse with combined stdout/stderr and exit code.
        """
        cwd = str(self._root) if self._root else None

        # Restricted environment
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),  # noqa: S108
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),  # noqa: S108
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                timeout=timeout,
                cwd=cwd,
                text=True,
                env=env,
            )

            output = result.stdout or ""
            if result.stderr:
                output += "\n" + result.stderr if output else result.stderr

            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=False,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: Command timed out after {timeout} seconds",
                exit_code=-1,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error: {e!s}",
                exit_code=-1,
                truncated=False,
            )

    async def aexecute(self, command: str, timeout: int = 120) -> ExecuteResponse:
        """Async version of execute."""
        return await asyncio.to_thread(self.execute, command, timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the filesystem.

        Args:
            files: List of (path, content_bytes) tuples.

        Returns:
            List of FileUploadResponse objects.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                resolved = self._resolve_path(path)
                resolved.parent.mkdir(parents=True, exist_ok=True)

                flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(resolved, flags, 0o644)
                with os.fdopen(fd, "wb") as f:
                    f.write(content)

                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as exc:
                error = _map_exception_to_standard_error(exc)
                if error is None:
                    raise
                responses.append(FileUploadResponse(path=path, error=error))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files (read as bytes).

        Uses ``O_NOFOLLOW`` where available.

        Args:
            paths: List of file paths.

        Returns:
            List of FileDownloadResponse with content or error.
        """
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                resolved = self._resolve_path(path)
                fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as f:
                    content = f.read()
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception as exc:
                error = _map_exception_to_standard_error(exc)
                if error is None:
                    raise
                responses.append(FileDownloadResponse(path=path, content=None, error=error))
        return responses


# Alias for backwards compatibility
FilesystemBackend = LocalFilesystemBackend

__all__ = ["LocalFilesystemBackend", "FilesystemBackend"]
