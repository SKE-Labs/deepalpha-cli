"""Unit tests for FilesystemMiddleware.

Tests truncation behavior for large files and the read_file tool.
"""

from unittest.mock import MagicMock, patch

from deepanalysts.backends.store import StoreBackend
from deepanalysts.middleware.filesystem import (
    NUM_CHARS_PER_TOKEN,
    READ_FILE_TRUNCATION_MSG,
    FilesystemMiddleware,
)
from langgraph.store.memory import InMemoryStore


def _make_mock_runtime(store: InMemoryStore | None = None) -> MagicMock:
    """Create a mock ToolRuntime with a store for testing StoreBackend."""
    runtime = MagicMock()
    runtime.store = store or InMemoryStore()
    runtime.config = {"configurable": {"user_id": "test-user-123"}}
    runtime.tool_call_id = "test-call-id"
    return runtime


def _make_store_backend() -> StoreBackend:
    """Create a StoreBackend with InMemoryStore for testing."""
    return StoreBackend(_make_mock_runtime())


def _invoke_read_file(middleware: FilesystemMiddleware, file_path: str, offset: int = 0, limit: int = 500) -> str:
    """Invoke the read_file tool's sync function directly.

    This bypasses StructuredTool's pydantic validation (which requires
    ToolRuntime injection via langgraph) and calls the inner function directly.
    """
    read_file_tool = next(t for t in middleware.tools if t.name == "read_file")
    # The sync function is stored as .func on StructuredTool
    sync_fn = read_file_tool.func
    # Create a mock runtime for the tool call
    runtime = MagicMock()
    runtime.tool_call_id = "test-call-id"
    return sync_fn(file_path=file_path, runtime=runtime, offset=offset, limit=limit)


class TestReadFileTruncation:
    """Tests for read_file tool truncation behavior."""

    def test_read_large_single_line_file_returns_reasonable_size(self):
        """A large single-line file should be truncated within the token budget.

        This tests the fix for the truncation accounting bug where the
        truncation message was appended *after* truncating to the budget,
        causing total output to exceed the limit.
        """
        token_limit = 20000
        max_chars = NUM_CHARS_PER_TOKEN * token_limit  # 80,000 chars

        # Create a backend and write a large single-line file (no newlines)
        backend = _make_store_backend()
        large_content = str({f"key_{i}": f"value_{i}" * 100 for i in range(5000)})
        assert len(large_content) > max_chars, "Test data must exceed the token budget"

        file_path = "/large_file.json"
        backend.write(file_path, large_content)

        # Create middleware with the same backend and token limit
        middleware = FilesystemMiddleware(
            backend=backend,
            tool_token_limit_before_evict=token_limit,
        )

        result = _invoke_read_file(middleware, file_path)

        # Result must not exceed the budget
        assert len(result) <= max_chars, f"Result length {len(result)} exceeds budget {max_chars}"

        # Truncation message should be present
        assert "[Output was truncated due to size limits" in result

    def test_truncation_message_fits_within_budget(self):
        """The truncation message itself must be accounted for in the budget.

        content + truncation_msg <= budget
        """
        token_limit = 20000
        max_chars = NUM_CHARS_PER_TOKEN * token_limit

        backend = _make_store_backend()
        # Create content just over the threshold
        content = "x" * (max_chars + 1000)
        file_path = "/just_over.txt"
        backend.write(file_path, content)

        middleware = FilesystemMiddleware(
            backend=backend,
            tool_token_limit_before_evict=token_limit,
        )

        result = _invoke_read_file(middleware, file_path)

        # The total result (content + truncation message) must fit within budget
        assert len(result) <= max_chars, (
            f"Result length {len(result)} exceeds budget {max_chars}. "
            f"Truncation message not accounted for in budget calculation."
        )

    def test_small_file_not_truncated(self):
        """Files under the token budget should not be truncated."""
        token_limit = 20000

        backend = _make_store_backend()
        small_content = "Hello, world!\nLine 2\nLine 3\n"
        file_path = "/small.txt"
        backend.write(file_path, small_content)

        middleware = FilesystemMiddleware(
            backend=backend,
            tool_token_limit_before_evict=token_limit,
        )

        result = _invoke_read_file(middleware, file_path)

        assert "[Output was truncated" not in result
