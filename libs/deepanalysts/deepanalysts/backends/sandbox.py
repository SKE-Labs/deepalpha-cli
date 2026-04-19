"""Sandbox backend implementations for code execution.

This module provides sandbox backends that implement SandboxBackendProtocol,
enabling the `execute()` tool for running Python code in isolated environments.
"""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from deepanalysts.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)

# Shell command templates for file operations
_GLOB_COMMAND_TEMPLATE = """python3 -c "
import glob
import os
import json
import base64

# Decode base64-encoded parameters
path = base64.b64decode('{path_b64}').decode('utf-8')
pattern = base64.b64decode('{pattern_b64}').decode('utf-8')

os.chdir(path)
matches = sorted(glob.glob(pattern, recursive=True))
for m in matches:
    stat = os.stat(m)
    result = {{
        'path': m,
        'size': stat.st_size,
        'mtime': stat.st_mtime,
        'is_dir': os.path.isdir(m)
    }}
    print(json.dumps(result))
" 2>/dev/null"""

# Use heredoc to pass content via stdin to avoid ARG_MAX limits on large files.
# ARG_MAX limits the total size of command-line arguments.
# Previously, base64-encoded content was interpolated directly into the command
# string, which would fail for files larger than ~100KB after base64 expansion.
# Heredocs bypass this by passing data through stdin rather than as arguments.
# Stdin format: base64-encoded JSON with {{"path": str, "content": str (base64)}}
_WRITE_COMMAND_TEMPLATE = """python3 -c "
import os
import sys
import base64
import json

# Read JSON payload from stdin containing file_path and content (both base64-encoded)
payload_b64 = sys.stdin.read().strip()
if not payload_b64:
    print('Error: No payload received for write operation', file=sys.stderr)
    sys.exit(1)

try:
    payload = base64.b64decode(payload_b64).decode('utf-8')
    data = json.loads(payload)
    file_path = data['path']
    content = base64.b64decode(data['content']).decode('utf-8')
except Exception as e:
    print(f'Error: Failed to decode write payload: {{e}}', file=sys.stderr)
    sys.exit(1)

# Check if file already exists (atomic with write)
if os.path.exists(file_path):
    print(f'Error: File \\'{{file_path}}\\' already exists', file=sys.stderr)
    sys.exit(1)

# Create parent directory if needed
parent_dir = os.path.dirname(file_path) or '.'
os.makedirs(parent_dir, exist_ok=True)

with open(file_path, 'w') as f:
    f.write(content)
" <<'__DEEPALPHA_EOF__'
{payload_b64}
__DEEPALPHA_EOF__"""

# Use heredoc to pass edit parameters via stdin to avoid ARG_MAX limits.
# Stdin format: base64-encoded JSON with {{"path": str, "old": str, "new": str}}.
# JSON bundles all parameters; base64 ensures safe transport of arbitrary content
# (special chars, newlines, etc.) through the heredoc without escaping issues.
_EDIT_COMMAND_TEMPLATE = """python3 -c "
import sys
import base64
import json
import os

# Read and decode JSON payload from stdin
payload_b64 = sys.stdin.read().strip()
if not payload_b64:
    print('Error: No payload received for edit operation', file=sys.stderr)
    sys.exit(4)

try:
    payload = base64.b64decode(payload_b64).decode('utf-8')
    data = json.loads(payload)
    file_path = data['path']
    old = data['old']
    new = data['new']
except Exception as e:
    print(f'Error: Failed to decode edit payload: {{e}}', file=sys.stderr)
    sys.exit(4)

# Check if file exists
if not os.path.isfile(file_path):
    sys.exit(3)  # File not found

# Read file content
with open(file_path, 'r') as f:
    text = f.read()

# Count occurrences
count = text.count(old)

# Exit with error codes if issues found
if count == 0:
    sys.exit(1)  # String not found
elif count > 1 and not {replace_all}:
    sys.exit(2)  # Multiple occurrences without replace_all

# Perform replacement
if {replace_all}:
    result = text.replace(old, new)
else:
    result = text.replace(old, new, 1)

# Write back to file
with open(file_path, 'w') as f:
    f.write(result)

print(count)
" <<'__DEEPALPHA_EOF__'
{payload_b64}
__DEEPALPHA_EOF__"""

_READ_COMMAND_TEMPLATE = """python3 -c "
import os
import sys

file_path = '{file_path}'
offset = {offset}
limit = {limit}

if not os.path.isfile(file_path):
    print('Error: File not found')
    sys.exit(1)

if os.path.getsize(file_path) == 0:
    print('System reminder: File exists but has empty contents')
    sys.exit(0)

with open(file_path, 'r') as f:
    lines = f.readlines()

start_idx = offset
end_idx = offset + limit
selected_lines = lines[start_idx:end_idx]

for i, line in enumerate(selected_lines):
    line_num = offset + i + 1
    line_content = line.rstrip('\\n')
    print(f'{{line_num:6d}}\\t{{line_content}}')
" 2>&1"""


class BaseSandbox(SandboxBackendProtocol, ABC):
    """Base sandbox implementation with execute() as abstract method.

    This class provides default implementations for all protocol methods
    using shell commands. Subclasses only need to implement execute().
    """

    @abstractmethod
    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox and return ExecuteResponse."""
        ...

    def ls_info(self, path: str) -> list[FileInfo]:
        """Structured listing with file metadata using os.scandir."""
        cmd = f"""python3 -c "
import os
import json

path = '{path}'

try:
    with os.scandir(path) as it:
        for entry in it:
            result = {{
                'path': os.path.join(path, entry.name),
                'is_dir': entry.is_dir(follow_symlinks=False)
            }}
            print(json.dumps(result))
except FileNotFoundError:
    pass
except PermissionError:
    pass
" 2>/dev/null"""

        result = self.execute(cmd)

        file_infos: list[FileInfo] = []
        for line in result.output.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
            except json.JSONDecodeError:
                continue

        return file_infos

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers."""
        cmd = _READ_COMMAND_TEMPLATE.format(file_path=file_path, offset=offset, limit=limit)
        result = self.execute(cmd)

        output = result.output.rstrip()
        exit_code = result.exit_code

        if exit_code != 0 or "Error: File not found" in output:
            return f"Error: File '{file_path}' not found"

        return output

    def write(self, file_path: str, content: str) -> WriteResult:
        """Create a new file. Returns WriteResult; error populated on failure."""
        # Create JSON payload with file path and base64-encoded content
        # This avoids shell injection via file_path and ARG_MAX limits on content
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        payload = json.dumps({"path": file_path, "content": content_b64})
        payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")

        # Single atomic check + write command
        cmd = _WRITE_COMMAND_TEMPLATE.format(payload_b64=payload_b64)
        result = self.execute(cmd)

        # Check for errors (exit code or error message in output)
        if result.exit_code != 0 or "Error:" in result.output:
            error_msg = result.output.strip() or f"Failed to write file '{file_path}'"
            return WriteResult(error=error_msg)

        # External storage - no files_update needed
        return WriteResult(path=file_path, files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences. Returns EditResult."""
        # Create JSON payload with file path, old string, and new string
        # This avoids shell injection via file_path and ARG_MAX limits on strings
        payload = json.dumps({"path": file_path, "old": old_string, "new": new_string})
        payload_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")

        # Use template for string replacement
        cmd = _EDIT_COMMAND_TEMPLATE.format(payload_b64=payload_b64, replace_all=replace_all)
        result = self.execute(cmd)

        exit_code = result.exit_code
        output = result.output.strip()

        # Map exit codes to error messages
        error_messages = {
            1: f"Error: String not found in file: '{old_string}'",
            2: f"Error: String '{old_string}' appears multiple times. Use replace_all=True.",
            3: f"Error: File '{file_path}' not found",
            4: f"Error: Failed to decode edit payload: {output}",
        }
        if exit_code in error_messages:
            return EditResult(error=error_messages[exit_code])
        if exit_code != 0:
            return EditResult(error=f"Error editing file (exit code {exit_code}): {output or 'Unknown error'}")

        count = int(output)
        return EditResult(path=file_path, files_update=None, occurrences=count)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search files for pattern."""
        search_path = shlex.quote(path or ".")
        grep_opts = "-rHnF"

        glob_pattern = ""
        if glob:
            glob_pattern = f"--include='{glob}'"

        pattern_escaped = shlex.quote(pattern)
        cmd = f"grep {grep_opts} {glob_pattern} -e {pattern_escaped} {search_path} 2>/dev/null || true"
        result = self.execute(cmd)

        output = result.output.rstrip()
        if not output:
            return []

        matches: list[GrepMatch] = []
        for line in output.split("\n"):
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append({"path": parts[0], "line": int(parts[1]), "text": parts[2]})

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern."""
        pattern_b64 = base64.b64encode(pattern.encode("utf-8")).decode("ascii")
        path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")

        cmd = _GLOB_COMMAND_TEMPLATE.format(path_b64=path_b64, pattern_b64=pattern_b64)
        result = self.execute(cmd)

        output = result.output.strip()
        if not output:
            return []

        file_infos: list[FileInfo] = []
        for line in output.split("\n"):
            try:
                data = json.loads(line)
                file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
            except json.JSONDecodeError:
                continue

        return file_infos

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for the sandbox backend."""

    @abstractmethod
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the sandbox."""

    @abstractmethod
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the sandbox."""


class RestrictedSubprocessBackend(BaseSandbox):
    """Subprocess-based sandbox with security restrictions.

    Designed for calculations (Fibonacci, position sizing, etc.)
    running on the same machine with timeout and environment restrictions.

    Security features:
    - Timeout protection (default 30s)
    - Working directory isolation (temp dir)
    - Restricted environment variables
    - No external network access implied by restricted env

    Note: This is NOT container-level isolation. For untrusted code,
    use Modal, Runloop, or Daytona backends.
    """

    def __init__(self, timeout: int = 30, working_dir: str | None = None):
        """Initialize the restricted subprocess backend.

        Args:
            timeout: Maximum execution time in seconds (default 30).
            working_dir: Working directory for command execution.
                        If None, creates a temporary directory.
        """
        self._timeout = timeout
        self._id = f"subprocess-{uuid.uuid4().hex[:8]}"

        if working_dir:
            self._temp_dir = Path(working_dir)
            self._temp_dir.mkdir(parents=True, exist_ok=True)
            self._owns_temp_dir = False
        else:
            self._temp_dir_obj = tempfile.TemporaryDirectory(prefix="deepanalysts_sandbox_")
            self._temp_dir = Path(self._temp_dir_obj.name)
            self._owns_temp_dir = True

    @property
    def id(self) -> str:
        """Unique identifier for this sandbox instance."""
        return self._id

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in a restricted subprocess.

        Args:
            command: Shell command string to execute.

        Returns:
            ExecuteResponse with combined stdout/stderr, exit code, and truncation flag.
        """
        # Restricted environment - minimal PATH, no user-specific vars
        restricted_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "",
            "HOME": str(self._temp_dir),
            "TMPDIR": str(self._temp_dir),
            "LANG": "C.UTF-8",
        }

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                timeout=self._timeout,
                cwd=str(self._temp_dir),
                env=restricted_env,
                text=True,
            )

            # Combine stdout and stderr
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
                output=f"Error: Command timed out after {self._timeout} seconds",
                exit_code=-1,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error: {e!s}",
                exit_code=-1,
                truncated=False,
            )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files to the sandbox working directory."""
        responses: list[FileUploadResponse] = []

        for path, content in files:
            try:
                # Resolve path relative to temp dir
                file_path = self._temp_dir / path.lstrip("/")
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                responses.append(FileUploadResponse(path=path, error=str(e)))

        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from the sandbox working directory."""
        responses: list[FileDownloadResponse] = []

        for path in paths:
            try:
                file_path = self._temp_dir / path.lstrip("/")
                if not file_path.exists():
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                    continue

                content = file_path.read_bytes()
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception:
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))

        return responses

    def cleanup(self) -> None:
        """Clean up temporary directory if owned by this backend."""
        if self._owns_temp_dir and hasattr(self, "_temp_dir_obj"):
            self._temp_dir_obj.cleanup()

    def __del__(self) -> None:
        """Cleanup on garbage collection."""
        self.cleanup()


__all__ = ["BaseSandbox", "RestrictedSubprocessBackend"]
