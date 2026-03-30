"""Unit tests for SummarizationMiddleware with backend offloading."""

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest
from deepanalysts.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    WriteResult,
)
from deepanalysts.middleware.summarization import SummarizationMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# Configure anyio to use asyncio only (avoid trio which is not installed)
pytest_plugins = ("anyio",)


if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState


def make_conversation_messages(
    num_old: int = 6,
    num_recent: int = 3,
    *,
    include_previous_summary: bool = False,
) -> list:
    """Create a realistic conversation message sequence."""
    messages: list[BaseMessage] = []

    if include_previous_summary:
        messages.append(
            HumanMessage(
                content="Here is a summary of the conversation to date:\n\nPrevious summary content...",
                additional_kwargs={"lc_source": "summarization"},
                id="summary-msg-0",
            )
        )

    for i in range(num_old):
        if i % 3 == 0:
            messages.append(HumanMessage(content=f"User message {i}", id=f"human-{i}"))
        elif i % 3 == 1:
            messages.append(
                AIMessage(
                    content=f"AI response {i}",
                    id=f"ai-{i}",
                    tool_calls=[{"id": f"tool-call-{i}", "name": "test_tool", "args": {}}],
                )
            )
        else:
            messages.append(
                ToolMessage(
                    content=f"Tool result {i}",
                    tool_call_id=f"tool-call-{i - 1}",
                    id=f"tool-{i}",
                )
            )

    for i in range(num_recent):
        idx = num_old + i
        messages.append(HumanMessage(content=f"Recent message {idx}", id=f"recent-{idx}"))

    return messages


class MockBackend(BackendProtocol):
    """A mock backend that records read/write calls and can simulate failures."""

    def __init__(
        self,
        *,
        should_fail: bool = False,
        error_message: str | None = None,
        existing_content: str | None = None,
    ) -> None:
        self.write_calls: list[tuple[str, str]] = []
        self.edit_calls: list[tuple[str, str, str]] = []
        self.download_files_calls: list[list[str]] = []
        self.should_fail = should_fail
        self.error_message = error_message
        self.existing_content = existing_content

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        if self.existing_content is not None:
            return self.existing_content
        return ""

    async def aread(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        return self.read(path, offset, limit)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        self.download_files_calls.append(paths)
        responses = []
        for path in paths:
            if self.existing_content is not None:
                responses.append(
                    FileDownloadResponse(
                        path=path,
                        content=self.existing_content.encode("utf-8"),
                        error=None,
                    )
                )
            else:
                responses.append(
                    FileDownloadResponse(
                        path=path,
                        content=None,
                        error="file_not_found",
                    )
                )
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return self.download_files(paths)

    def write(self, path: str, content: str) -> WriteResult:
        self.write_calls.append((path, content))
        if self.should_fail:
            return WriteResult(error=self.error_message or "Mock write failure")
        return WriteResult(path=path)

    async def awrite(self, path: str, content: str) -> WriteResult:
        return self.write(path, content)

    def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        self.edit_calls.append((path, old_string, new_string))
        if self.should_fail:
            return EditResult(error=self.error_message or "Mock edit failure")
        return EditResult(path=path, occurrences=1)

    async def aedit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        return self.edit(path, old_string, new_string, replace_all)


def make_mock_runtime() -> MagicMock:
    """Create a mock Runtime."""
    runtime = MagicMock()
    runtime.context = {}
    runtime.stream_writer = MagicMock()
    runtime.store = None
    del runtime.config
    return runtime


def make_mock_model(summary_response: str = "This is a test summary.") -> MagicMock:
    """Create a mock LLM model for summarization."""
    model = MagicMock()
    model.invoke.return_value = MagicMock(text=summary_response)
    model._llm_type = "test-model"
    model.profile = {"max_input_tokens": 100000}
    model._get_ls_params.return_value = {"ls_provider": "test"}
    return model


class TestSummarizationMiddlewareInit:
    """Tests for middleware initialization."""

    def test_init_with_backend(self) -> None:
        """Test initialization with a backend instance."""
        backend = MockBackend()
        middleware = SummarizationMiddleware(
            model=make_mock_model(),
            backend=backend,
            trigger=("messages", 5),
            keep=("messages", 3),
        )

        assert middleware._backend is backend
        assert middleware._history_path_prefix == "/conversation_history"

    def test_init_with_backend_factory(self) -> None:
        """Test initialization with a backend factory function."""
        backend = MockBackend()
        factory = lambda _rt: backend  # noqa: E731

        middleware = SummarizationMiddleware(
            model=make_mock_model(),
            backend=factory,
            trigger=("messages", 5),
            keep=("messages", 3),
        )

        assert callable(middleware._backend)


class TestOffloadingBasic:
    """Tests for basic offloading behavior."""

    def test_offload_writes_to_backend(self) -> None:
        """Test that summarization triggers a write to the backend."""
        backend = MockBackend()
        mock_model = make_mock_model()

        middleware = SummarizationMiddleware(
            model=mock_model,
            backend=backend,
            trigger=("messages", 5),
            keep=("messages", 2),
        )

        messages = make_conversation_messages(num_old=6, num_recent=2)
        state = cast("AgentState[Any]", {"messages": messages})
        runtime = make_mock_runtime()

        with patch(
            "deepanalysts.middleware.summarization.get_config",
            return_value={"configurable": {"thread_id": "test-thread-123"}},
        ):
            result = middleware.before_model(state, runtime)

        assert result is not None
        assert len(backend.write_calls) == 1

        path, content = backend.write_calls[0]
        assert path == "/conversation_history/test-thread-123.md"
        assert "## Summarized at" in content

    def test_summarization_continues_on_backend_failure(self) -> None:
        """Test that summarization continues (with warning) when backend write fails."""
        backend = MockBackend(should_fail=True)
        mock_model = make_mock_model(summary_response="Summary despite failure")

        middleware = SummarizationMiddleware(
            model=mock_model,
            backend=backend,
            trigger=("messages", 5),
            keep=("messages", 2),
        )

        messages = make_conversation_messages(num_old=6, num_recent=2)
        state = cast("AgentState[Any]", {"messages": messages})
        runtime = make_mock_runtime()

        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = middleware.before_model(state, runtime)
            # Should emit a warning about offload failure
            assert len(w) == 1
            assert "Offloading conversation history to backend failed" in str(w[0].message)

        # Should continue with summarization (not abort)
        assert result is not None
        # Summary message should not include file path (since offload failed)
        summary_msgs = [
            m
            for m in result["messages"]
            if hasattr(m, "additional_kwargs") and m.additional_kwargs.get("lc_source") == "summarization"
        ]
        assert len(summary_msgs) == 1
        assert "summary of the conversation" in summary_msgs[0].content.lower()


class TestNoSummarizationTriggered:
    """Tests for when summarization threshold is not met."""

    def test_no_offload_when_below_threshold(self) -> None:
        """Test that no offload occurs when message count is below trigger."""
        backend = MockBackend()
        mock_model = make_mock_model()

        middleware = SummarizationMiddleware(
            model=mock_model,
            backend=backend,
            trigger=("messages", 100),  # High threshold
            keep=("messages", 3),
        )

        messages = make_conversation_messages(num_old=3, num_recent=2)
        state = cast("AgentState[Any]", {"messages": messages})
        runtime = make_mock_runtime()

        result = middleware.before_model(state, runtime)

        assert result is None
        assert len(backend.write_calls) == 0


class TestAsyncBehavior:
    """Tests for async version of before_model."""

    @pytest.mark.anyio
    async def test_async_offload_writes_to_backend(self) -> None:
        """Test that async summarization triggers a write to the backend."""
        backend = MockBackend()
        mock_model = make_mock_model()
        mock_model.ainvoke = MagicMock(return_value=MagicMock(text="Async summary"))

        middleware = SummarizationMiddleware(
            model=mock_model,
            backend=backend,
            trigger=("messages", 5),
            keep=("messages", 2),
        )

        messages = make_conversation_messages(num_old=6, num_recent=2)
        state = cast("AgentState[Any]", {"messages": messages})
        runtime = make_mock_runtime()

        result = await middleware.abefore_model(state, runtime)

        assert result is not None
        assert len(backend.write_calls) == 1

    @pytest.mark.anyio
    async def test_async_continues_on_failure(self) -> None:
        """Test that async summarization continues (with warning) on backend failure."""
        backend = MockBackend(should_fail=True)
        mock_model = make_mock_model(summary_response="Async summary despite failure")

        middleware = SummarizationMiddleware(
            model=mock_model,
            backend=backend,
            trigger=("messages", 5),
            keep=("messages", 2),
        )

        messages = make_conversation_messages(num_old=6, num_recent=2)
        state = cast("AgentState[Any]", {"messages": messages})
        runtime = make_mock_runtime()

        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = await middleware.abefore_model(state, runtime)
            # Should emit a warning about offload failure
            assert len(w) == 1
            assert "Offloading conversation history to backend failed" in str(w[0].message)

        # Should continue with summarization (not abort)
        assert result is not None
