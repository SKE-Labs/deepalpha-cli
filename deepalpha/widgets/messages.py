"""Message widgets for deepalpha-cli."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownStream

from deepalpha.ui import format_tool_display
from deepalpha.widgets.diff import format_diff_textual

if TYPE_CHECKING:
    from textual.app import ComposeResult

# Maximum number of tool arguments to display inline
_MAX_INLINE_ARGS = 3


class UserMessage(Static):
    """Widget displaying a user message."""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
        border-left: thick white;
    }

    UserMessage .user-prefix {
        color: white;
        text-style: bold;
    }

    UserMessage .user-content {
        margin-left: 1;
    }
    """

    def __init__(self, content: str, **kwargs: Any) -> None:
        """Initialize a user message.

        Args:
            content: The message content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content

    def compose(self) -> ComposeResult:
        """Compose the user message layout."""
        text = Text()
        text.append("> ", style="bold white")
        text.append(self._content)
        yield Static(text)


class AssistantMessage(Horizontal):
    """Widget displaying an assistant message with markdown support.

    Uses MarkdownStream for smoother streaming instead of re-rendering
    the full content on each update.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
    }

    AssistantMessage .assistant-marker {
        color: #94a3b8;
        width: 2;
        height: 1;
    }

    AssistantMessage .assistant-body {
        width: 1fr;
        height: auto;
    }

    AssistantMessage .assistant-body Markdown {
        padding: 0;
        margin: 0;
    }
    """

    def __init__(self, content: str = "", **kwargs: Any) -> None:
        """Initialize an assistant message.

        Args:
            content: Initial markdown content
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._content = content
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None

    def compose(self) -> ComposeResult:
        """Compose the assistant message layout."""
        yield Static("\u2022", classes="assistant-marker")
        with Vertical(classes="assistant-body"):
            yield Markdown("", id="assistant-content")

    def on_mount(self) -> None:
        """Store reference to markdown widget."""
        self._markdown = self.query_one("#assistant-content", Markdown)

    def _get_markdown(self) -> Markdown:
        """Get the markdown widget, querying if not cached."""
        if self._markdown is None:
            self._markdown = self.query_one("#assistant-content", Markdown)
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream:
        """Ensure the markdown stream is initialized."""
        if self._stream is None:
            self._stream = Markdown.get_stream(self._get_markdown())
        return self._stream

    async def append_content(self, text: str) -> None:
        """Append content to the message (for streaming).

        Uses MarkdownStream for smoother rendering instead of re-rendering
        the full content on each chunk.

        Args:
            text: Text to append
        """
        if not text:
            return
        self._content += text
        stream = self._ensure_stream()
        await stream.write(text)

    async def write_initial_content(self) -> None:
        """Write initial content if provided at construction time."""
        if self._content:
            stream = self._ensure_stream()
            await stream.write(self._content)

    async def stop_stream(self) -> None:
        """Stop the streaming and finalize the content."""
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None

    async def set_content(self, content: str) -> None:
        """Set the full message content.

        This stops any active stream and sets content directly.

        Args:
            content: The markdown content to display
        """
        await self.stop_stream()
        self._content = content
        if self._markdown:
            await self._markdown.update(content)


class SubToolLine(Static):
    """Lightweight widget for a nested sub-tool call inside a task block.

    Shows status as:  > tool_label (pending) -> checkmark tool_label (success) -> x tool_label (error)
    """

    DEFAULT_CSS = """
    SubToolLine {
        height: auto;
        margin: 0 0 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, tool_name: str, args: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._args = args or {}
        self._label = format_tool_display(tool_name, self._args)

    def on_mount(self) -> None:
        self.update(Text.assemble(("\u203a ", "dim"), (self._label, "")))

    def mark_success(self) -> None:
        self.update(Text.assemble(("✓ ", "green"), (self._label, "")))

    def mark_error(self) -> None:
        self.update(Text.assemble(("✗ ", "red"), (self._label, "")))


class ToolCallMessage(Vertical):
    """Widget displaying a tool call with collapsible output.

    Tool outputs are shown as a 3-line preview by default.
    Press Ctrl+O to expand/collapse the full output.
    """

    DEFAULT_CSS = """
    ToolCallMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
        border: round $surface-lighten-2;
    }

    ToolCallMessage.subagent-tool {
    }

    ToolCallMessage.tool-success {
    }

    ToolCallMessage.tool-error {
    }

    ToolCallMessage.tool-rejected {
    }

    ToolCallMessage .tool-header {
        text-style: bold;
    }

    ToolCallMessage .tool-header.pending {
        color: $text-muted;
    }

    ToolCallMessage .tool-header.success {
        color: $success;
    }

    ToolCallMessage .tool-header.error {
        color: $error;
    }

    ToolCallMessage .tool-header.rejected {
        color: $warning;
    }

    ToolCallMessage .tool-source {
        color: $warning;
        text-style: italic;
        margin-left: 2;
    }

    ToolCallMessage .tool-args {
        color: $text-muted;
        margin-left: 2;
    }

    ToolCallMessage #sub-tools {
        height: auto;
        margin: 0 0 0 1;
    }

    ToolCallMessage .tool-output {
        margin-left: 2;
        margin-top: 1;
        padding: 1;
        background: $surface-darken-1;
        color: $text-muted;
        max-height: 20;
        overflow-y: auto;
    }

    ToolCallMessage .tool-output-preview {
        margin-left: 2;
        color: $text-muted;
    }

    ToolCallMessage .tool-output-hint {
        margin-left: 2;
        color: $text-muted;
        text-style: italic;
    }

    ToolCallMessage:hover {
        background: $surface-lighten-1;
    }
    """

    # Max lines/chars to show in preview mode
    _PREVIEW_LINES = 3
    _PREVIEW_CHARS = 200

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        source_agent: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize a tool call message.

        Args:
            tool_name: Name of the tool being called
            args: Tool arguments (optional)
            source_agent: Name of subagent that invoked the tool (None for main agent)
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._args = args or {}
        self._source_agent = source_agent
        self._status = "pending"
        self._output: str = ""
        self._expanded: bool = False
        self._sub_tool_calls: dict[str, SubToolLine] = {}
        # Widget references (set in on_mount)
        self._header_widget: Static | None = None
        self._preview_widget: Static | None = None
        self._hint_widget: Static | None = None
        self._full_widget: Static | None = None

    def compose(self) -> ComposeResult:
        """Compose the tool call message layout."""
        tool_label = format_tool_display(self._tool_name, self._args)
        self._header_widget = Static(
            f"[dim]>[/dim] {tool_label}",
            classes="tool-header pending",
        )
        yield self._header_widget
        # Show source agent for subagent tool calls
        if self._source_agent:
            # Strip unique ID suffix if present (e.g., "technical_analyst:abc12345" -> "technical_analyst")
            base_name = self._source_agent.split(":")[0] if ":" in self._source_agent else self._source_agent
            agent_display = base_name.replace("_", " ").title()
            yield Static(f"via {agent_display}", classes="tool-source")
        # Task tool: show first line of description as a clean summary
        if self._tool_name == "task" and "description" in self._args:
            desc = str(self._args["description"])
            first_line = desc.split("\n")[0].strip()
            if len(first_line) > 120:
                first_line = first_line[:120] + "..."
            yield Static(first_line, classes="tool-args", markup=False)
        # write_todos: persistent widget handles display, skip inline checklist
        elif self._tool_name == "write_todos":
            pass
        else:
            args = self._filtered_args()
            if args:
                args_str = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:_MAX_INLINE_ARGS])
                if len(args) > _MAX_INLINE_ARGS:
                    args_str += ", ..."
                yield Static(f"({args_str})", classes="tool-args")
        # Sub-tools container for task-type tools (subagent calls nest here)
        if self._tool_name == "task":
            yield Vertical(id="sub-tools")
        # Output area - hidden initially, shown when output is set
        # Use markup=False for output content to prevent Rich markup injection
        yield Static("", classes="tool-output-preview", id="output-preview", markup=False)
        yield Static("", classes="tool-output-hint", id="output-hint")  # hint uses our markup
        yield Static("", classes="tool-output", id="output-full", markup=False)

    def on_mount(self) -> None:
        """Cache widget references and hide output areas initially."""
        self._preview_widget = self.query_one("#output-preview", Static)
        self._hint_widget = self.query_one("#output-hint", Static)
        self._full_widget = self.query_one("#output-full", Static)
        self._preview_widget.display = False
        self._hint_widget.display = False
        self._full_widget.display = False

    def _update_header(self, icon: str, css_class: str) -> None:
        """Update the header widget with a new icon and CSS class.

        Args:
            icon: Icon character to display (e.g., checkmark, cross)
            css_class: CSS class for coloring (success, error, rejected)
        """
        if self._header_widget:
            tool_label = format_tool_display(self._tool_name, self._args)
            self._header_widget.update(f"{icon} {tool_label}")
            self._header_widget.remove_class("pending", "success", "error", "rejected")
            self._header_widget.add_class(css_class)

    def set_success(self, result: str = "") -> None:
        """Mark the tool call as successful.

        Args:
            result: Tool output/result to display
        """
        self._status = "success"
        self._output = self._format_result(result)
        self._update_header("[green]\u2713[/green]", "success")
        self._update_output_display()

    def set_error(self, error: str) -> None:
        """Mark the tool call as failed.

        Args:
            error: Error message
        """
        self._status = "error"
        self._output = error
        self._update_header("[red]\u2717[/red]", "error")
        # Always show full error - errors should be visible
        self._expanded = True
        self._update_output_display()

    def set_rejected(self) -> None:
        """Mark the tool call as rejected by user."""
        self._status = "rejected"
        self._update_header("[yellow]\u2717[/yellow]", "rejected")

    def set_skipped(self) -> None:
        """Mark the tool call as skipped (due to another rejection)."""
        self._status = "skipped"
        self._update_header("[dim]-[/dim]", "rejected")

    def set_instance_id(self, instance_id: str, description: str) -> None:
        """Store instance mapping for parallel subagent correlation.

        This is used for task tools to map instance IDs to their descriptions
        when multiple subagents of the same type run in parallel.

        Args:
            instance_id: The unique instance ID (first 8 chars of tool_call_id)
            description: The task description for this instance
        """
        if not hasattr(self, "_instance_mappings"):
            self._instance_mappings: dict[str, str] = {}
        self._instance_mappings[instance_id] = description

    def toggle_output(self) -> None:
        """Toggle between preview and full output display."""
        if not self._output:
            return
        self._expanded = not self._expanded
        self._update_output_display()

    def on_click(self) -> None:
        """Handle click to toggle output expansion."""
        self.toggle_output()

    def _update_output_display(self) -> None:
        """Update the output display based on expanded state."""
        if not self._output or not self._preview_widget:
            return

        output_stripped = self._output.strip()
        lines = output_stripped.split("\n")
        total_lines = len(lines)
        total_chars = len(output_stripped)

        # Truncate if too many lines OR too many characters
        needs_truncation = total_lines > self._PREVIEW_LINES or total_chars > self._PREVIEW_CHARS

        if self._expanded:
            # Show full output
            self._preview_widget.display = False
            self._hint_widget.display = False
            self._full_widget.update(self._output)
            self._full_widget.display = True
        else:
            # Show preview
            self._full_widget.display = False
            if needs_truncation:
                # Truncate by lines first, then by chars
                if total_lines > self._PREVIEW_LINES:
                    preview_text = "\n".join(lines[: self._PREVIEW_LINES])
                else:
                    preview_text = output_stripped

                # Also truncate by chars if still too long
                if len(preview_text) > self._PREVIEW_CHARS:
                    preview_text = preview_text[: self._PREVIEW_CHARS] + "..."

                self._preview_widget.update(preview_text)
                self._preview_widget.display = True

                # Show expand hint
                self._hint_widget.update("[dim]... (click to expand)[/dim]")
                self._hint_widget.display = True
            elif output_stripped:
                # Output fits in preview, just show it
                self._preview_widget.update(output_stripped)
                self._preview_widget.display = True
                self._hint_widget.display = False
            else:
                self._preview_widget.display = False
                self._hint_widget.display = False

    @property
    def has_output(self) -> bool:
        """Check if this tool message has output to display."""
        return bool(self._output)

    async def add_sub_tool(self, tool_call_id: str, tool_name: str, args: dict[str, Any] | None = None) -> None:
        """Add a nested sub-tool call inside this task block.

        Args:
            tool_call_id: Unique ID for the tool call
            tool_name: Name of the tool
            args: Tool arguments
        """
        if tool_call_id in self._sub_tool_calls:
            return
        sub_tool = SubToolLine(tool_name, args)
        self._sub_tool_calls[tool_call_id] = sub_tool
        try:
            container = self.query_one("#sub-tools", Vertical)
            await container.mount(sub_tool)
        except Exception:
            pass

    def complete_sub_tool(self, tool_call_id: str, *, success: bool = True) -> None:
        """Update a sub-tool's status icon.

        Args:
            tool_call_id: The tool call ID to update
            success: Whether the tool succeeded
        """
        sub_tool = self._sub_tool_calls.get(tool_call_id)
        if sub_tool is None:
            return
        if success:
            sub_tool.mark_success()
        else:
            sub_tool.mark_error()

    @staticmethod
    def _format_todos_checklist(todos: list) -> Text:
        """Format a list of todo dicts as a numbered checklist with styled icons."""
        text = Text()
        for i, todo in enumerate(todos, 1):
            if isinstance(todo, dict):
                content = todo.get("content", "")
                status = todo.get("status", "pending")
                if i > 1:
                    text.append("\n")
                text.append(f"{i}. ")
                if status in ("completed", "done"):
                    text.append("✓ ", style="green")
                else:
                    text.append("○ ", style="dim")
                text.append(content)
        return text

    def _format_result(self, result: str) -> str:
        """Format tool result for cleaner display."""
        if self._tool_name == "write_todos":
            # Persistent todo widget handles display; suppress output panel
            return ""
        return result

    # Args already represented in the header by format_tool_display.
    # These are excluded from the secondary args line to avoid redundancy.
    _HEADER_SHOWN_ARGS: ClassVar[dict[str, set[str]]] = {
        "task": {"description", "subagent_type"},
        "web_search": {"query"},
        "get_financial_news": {"topic"},
        "get_fundamentals": {"ticker", "data_type"},
        "get_latest_candle": {"symbol"},
        "get_candles_around_date": {"symbol", "date"},
        "get_indicator": {"indicator", "symbol"},
        "get_economics_calendar": {"from_date", "to_date", "country", "impact", "event"},
        "get_user_trading_insights": {"status", "ticker"},
        "create_trading_insight": {"symbol", "position"},
        "update_trading_insight": {"signal_id", "status"},
        "calculate_position_size": {"symbol"},
        "read_file": {"file_path", "path"},
        "grep": {"pattern"},
        "shell": {"command"},
        "ls": {"path"},
        "glob": {"pattern"},
        "http_request": {"method", "url"},
        "fetch_url": {"url"},
        "write_todos": {"todos"},
    }

    def _filtered_args(self) -> dict[str, Any]:
        """Filter tool args for display, excluding args already shown in the header."""
        # File tools: only show specific metadata keys
        if self._tool_name in ("write_file", "edit_file"):
            filtered: dict[str, Any] = {}
            for key in ("file_path", "path", "replace_all"):
                if key in self._args:
                    filtered[key] = self._args[key]
            return filtered

        # For tools with smart header formatting, exclude primary args
        excluded = self._HEADER_SHOWN_ARGS.get(self._tool_name)
        if excluded:
            return {k: v for k, v in self._args.items() if k not in excluded}

        return self._args


class DiffMessage(Static):
    """Widget displaying a diff with syntax highlighting."""

    DEFAULT_CSS = """
    DiffMessage {
        height: auto;
        padding: 1;
        margin: 1 0 0 0;
        background: $surface;
        border: solid $surface-lighten-2;
    }

    DiffMessage .diff-header {
        text-style: bold;
        margin-bottom: 1;
    }

    DiffMessage .diff-add {
        color: #22c55e;
        background: #22c55e20;
    }

    DiffMessage .diff-remove {
        color: #ef4444;
        background: #ef444420;
    }

    DiffMessage .diff-context {
        color: $text-muted;
    }

    DiffMessage .diff-hunk {
        color: $text-muted;
        text-style: bold;
    }
    """

    def __init__(self, diff_content: str, file_path: str = "", **kwargs: Any) -> None:
        """Initialize a diff message.

        Args:
            diff_content: The unified diff content
            file_path: Path to the file being modified
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._diff_content = diff_content
        self._file_path = file_path

    def compose(self) -> ComposeResult:
        """Compose the diff message layout."""
        if self._file_path:
            yield Static(f"[bold]File: {self._file_path}[/bold]", classes="diff-header")

        # Render the diff with enhanced formatting
        rendered = format_diff_textual(self._diff_content, max_lines=100)
        yield Static(rendered)


class ErrorMessage(Static):
    """Widget displaying an error message."""

    DEFAULT_CSS = """
    ErrorMessage {
        height: auto;
        padding: 1;
        margin: 1 0 0 0;
        background: #7f1d1d;
        color: white;
        border-left: thick $error;
    }
    """

    def __init__(self, error: str, **kwargs: Any) -> None:
        """Initialize an error message.

        Args:
            error: The error message
            **kwargs: Additional arguments passed to parent
        """
        # Use Text object to combine styled prefix with unstyled error content
        text = Text("Error: ", style="bold red")
        text.append(error)
        super().__init__(text, **kwargs)


class SystemMessage(Static):
    """Widget displaying a system message."""

    DEFAULT_CSS = """
    SystemMessage {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        """Initialize a system message.

        Args:
            message: The system message
            **kwargs: Additional arguments passed to parent
        """
        # Use Text object to safely render message without markup parsing
        super().__init__(Text(message, style="dim"), **kwargs)
