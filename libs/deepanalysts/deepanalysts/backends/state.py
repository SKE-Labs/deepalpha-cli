"""StateBackend: Store files in LangGraph agent state (ephemeral).

Files stored here persist within a conversation thread but not across threads.
State is automatically checkpointed after each agent step by LangGraph.

Write/edit operations return ``files_update`` dicts in their results, which
the middleware uses to update LangGraph state via Command objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deepanalysts.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    GrepMatch,
    WriteResult,
)
from deepanalysts.backends.utils import (
    _filter_files_by_path,
    _glob_search_files,
    _normalize_content,
    check_empty_content,
    create_file_data,
    file_data_to_string,
    format_content_with_line_numbers,
    grep_matches_from_files,
    perform_string_replacement,
    update_file_data,
)

if TYPE_CHECKING:
    from langchain.tools import ToolRuntime


class StateBackend(BackendProtocol):
    """Backend that stores files in agent state (ephemeral).

    Uses LangGraph's state management and checkpointing. Files persist within
    a conversation thread but not across threads. State is automatically
    checkpointed after each agent step.

    Write/edit results include ``files_update`` dicts for LangGraph state
    updates (unlike external backends which set ``files_update=None``).

    Args:
        runtime: The ToolRuntime instance providing state access.
        file_format: Storage format — ``"v1"`` (default) stores content as
            ``list[str]``, ``"v2"`` stores as plain ``str`` with ``encoding``.
    """

    def __init__(
        self,
        runtime: ToolRuntime,
        *,
        file_format: str = "v1",
    ) -> None:
        self.runtime = runtime
        self._file_format = file_format

    def _prepare_for_storage(self, file_data: dict[str, Any]) -> dict[str, Any]:
        """Convert file data to the configured storage format."""
        if self._file_format == "v2":
            # Ensure content is a string for v2
            content = file_data.get("content", "")
            if isinstance(content, list):
                content = "\n".join(content)
            return {
                "content": content,
                "encoding": file_data.get("encoding", "utf-8"),
                "created_at": file_data["created_at"],
                "modified_at": file_data["modified_at"],
            }
        # v1: ensure content is list[str]
        content = file_data.get("content", "")
        if isinstance(content, str):
            content = content.split("\n")
        return {
            "content": content,
            "created_at": file_data["created_at"],
            "modified_at": file_data["modified_at"],
        }

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories in the specified directory (non-recursive).

        Args:
            path: Absolute path to directory.

        Returns:
            List of FileInfo dicts. Directories have trailing ``/`` and ``is_dir=True``.
        """
        files = self.runtime.state.get("files", {})
        infos: list[FileInfo] = []
        subdirs: set[str] = set()

        normalized_path = path if path.endswith("/") else path + "/"

        for k, fd in files.items():
            if not k.startswith(normalized_path):
                continue

            relative = k[len(normalized_path) :]

            if "/" in relative:
                subdir_name = relative.split("/")[0]
                subdirs.add(normalized_path + subdir_name + "/")
                continue

            # Direct file in this directory
            raw = fd.get("content", "")
            size = len("\n".join(raw)) if isinstance(raw, list) else len(raw)
            infos.append(
                {
                    "path": k,
                    "is_dir": False,
                    "size": int(size),
                    "modified_at": fd.get("modified_at", ""),
                }
            )

        infos.extend(FileInfo(path=subdir, is_dir=True, size=0, modified_at="") for subdir in sorted(subdirs))
        infos.sort(key=lambda x: x.get("path", ""))
        return infos

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with line numbers.

        Args:
            file_path: Absolute file path.
            offset: Line offset (0-indexed).
            limit: Maximum number of lines.

        Returns:
            Formatted content with line numbers, or error message.
        """
        files = self.runtime.state.get("files", {})
        file_data = files.get(file_path)

        if file_data is None:
            return f"Error: File '{file_path}' not found"

        content = _normalize_content(file_data)
        empty_msg = check_empty_content(content)
        if empty_msg:
            return empty_msg

        lines = content.splitlines()
        start_idx = offset
        end_idx = min(start_idx + limit, len(lines))

        if start_idx >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

        selected = lines[start_idx:end_idx]
        return format_content_with_line_numbers(selected, start_line=start_idx + 1)

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file in state.

        Returns WriteResult with ``files_update`` for LangGraph state update.
        """
        files = self.runtime.state.get("files", {})

        if file_path in files:
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        new_fd = create_file_data(content, file_format=self._file_format)
        stored = self._prepare_for_storage(new_fd)
        return WriteResult(path=file_path, files_update={file_path: stored})

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences.

        Returns EditResult with ``files_update`` and occurrences.
        """
        files = self.runtime.state.get("files", {})
        file_data = files.get(file_path)

        if file_data is None:
            return EditResult(error=f"Error: File '{file_path}' not found")

        content = file_data_to_string(file_data)
        result = perform_string_replacement(content, old_string, new_string, replace_all)

        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result
        new_fd = update_file_data(file_data, new_content)
        stored = self._prepare_for_storage(new_fd)
        return EditResult(
            path=file_path,
            files_update={file_path: stored},
            occurrences=int(occurrences),
        )

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search state files for a literal text pattern.

        Args:
            pattern: Literal string to search for.
            path: Directory to search in.
            glob: File pattern to match.

        Returns:
            List of GrepMatch dicts or error string.
        """
        files = self.runtime.state.get("files", {})
        return grep_matches_from_files(files, pattern, path or "/", glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern.
            path: Base path to search from.

        Returns:
            List of FileInfo dicts for matching files.
        """
        files = self.runtime.state.get("files", {})
        result = _glob_search_files(files, pattern, path)
        if result == "No files found":
            return []

        paths = result.split("\n")
        infos: list[FileInfo] = []
        for p in paths:
            fd = files.get(p)
            if fd:
                raw = fd.get("content", "")
                size = len("\n".join(raw)) if isinstance(raw, list) else len(raw)
            else:
                size = 0
            infos.append(
                {
                    "path": p,
                    "is_dir": False,
                    "size": int(size),
                    "modified_at": fd.get("modified_at", "") if fd else "",
                }
            )
        return infos

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from state as bytes.

        Args:
            paths: List of file paths.

        Returns:
            List of FileDownloadResponse with content or error.
        """
        state_files = self.runtime.state.get("files", {})
        responses: list[FileDownloadResponse] = []

        for path in paths:
            file_data = state_files.get(path)
            if file_data is None:
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                continue

            content_str = file_data_to_string(file_data)
            content_bytes = content_str.encode("utf-8")
            responses.append(FileDownloadResponse(path=path, content=content_bytes, error=None))

        return responses
