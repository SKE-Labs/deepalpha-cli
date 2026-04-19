"""Textual UI application for DeepAlpha CLI."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from textual.app import App
from textual.binding import Binding, BindingType
from textual.containers import Container, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Click, MouseUp
from textual.theme import Theme
from textual.widgets import Static

from deepalpha.auth import load_credentials
from deepalpha.clipboard import copy_selection_to_clipboard
from deepalpha.config import get_agent_context_info, settings
from deepalpha.textual_adapter import TextualUIAdapter, execute_task_textual
from deepalpha.utils.prompt_loader import load_prompt
from deepalpha.widgets.approval import ApprovalMenu
from deepalpha.widgets.chat_input import ChatInput
from deepalpha.widgets.loading import LoadingWidget
from deepalpha.widgets.messages import (
    AssistantMessage,
    ErrorMessage,
    SystemMessage,
    ToolCallMessage,
    UserMessage,
)
from deepalpha.widgets.status import StatusBar
from deepalpha.widgets.todo_list import TodoListWidget
from deepalpha.widgets.welcome import WelcomeBanner

if TYPE_CHECKING:
    from langgraph.pregel import Pregel
    from textual.app import ComposeResult
    from textual.worker import Worker


class TextualTokenTracker:
    """Token tracker that updates the status bar."""

    def __init__(self, update_callback: callable, hide_callback: callable | None = None) -> None:
        """Initialize with callbacks to update the display."""
        self._update_callback = update_callback
        self._hide_callback = hide_callback
        self.current_context = 0

    def add(self, total_tokens: int, _output_tokens: int = 0) -> None:
        """Update token count from a response.

        Args:
            total_tokens: Total context tokens (input + output from usage_metadata)
            _output_tokens: Unused, kept for backwards compatibility
        """
        self.current_context = total_tokens
        self._update_callback(self.current_context)

    def reset(self) -> None:
        """Reset token count."""
        self.current_context = 0
        self._update_callback(0)

    def hide(self) -> None:
        """Hide the token display (e.g., during streaming)."""
        if self._hide_callback:
            self._hide_callback()

    def show(self) -> None:
        """Show the token display with current value (e.g., after interrupt)."""
        self._update_callback(self.current_context)


class TextualSessionState:
    """Session state for the Textual app."""

    def __init__(
        self,
        *,
        auto_approve: bool = False,
        thread_id: str | None = None,
    ) -> None:
        """Initialize session state.

        Args:
            auto_approve: Whether to auto-approve tool calls
            thread_id: Optional thread ID (generates 8-char hex if not provided)
        """
        self.auto_approve = auto_approve
        self.thread_id = thread_id if thread_id else uuid.uuid4().hex[:8]

    def reset_thread(self) -> str:
        """Reset to a new thread. Returns the new thread_id."""
        self.thread_id = uuid.uuid4().hex[:8]
        return self.thread_id


REMEMBER_PROMPT = load_prompt("commands/remember.md")


class DeepAlphaApp(App):
    """Main Textual application for DeepAlpha CLI."""

    TITLE = "DeepAlpha"
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False

    # Slow down scroll speed (default is 3 lines per scroll event)
    # Using 0.25 to require 4 scroll events per line - very smooth
    SCROLL_SENSITIVITY_Y = 0.25

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "interrupt", "Interrupt", show=False, priority=True),
        Binding("ctrl+c", "quit_or_interrupt", "Quit/Interrupt", show=False),
        Binding("ctrl+d", "quit_app", "Quit", show=False, priority=True),
        Binding("ctrl+t", "toggle_auto_approve", "Toggle Auto-Approve", show=False),
        Binding("shift+tab", "toggle_auto_approve", "Toggle Auto-Approve", show=False, priority=True),
        Binding("ctrl+o", "toggle_tool_output", "Toggle Tool Output", show=False),
        # Approval menu keys (handled at App level for reliability)
        Binding("up", "approval_up", "Up", show=False),
        Binding("k", "approval_up", "Up", show=False),
        Binding("down", "approval_down", "Down", show=False),
        Binding("j", "approval_down", "Down", show=False),
        Binding("enter", "approval_select", "Select", show=False),
        Binding("y", "approval_yes", "Yes", show=False),
        Binding("1", "approval_yes", "Yes", show=False),
        Binding("n", "approval_no", "No", show=False),
        Binding("2", "approval_no", "No", show=False),
        Binding("a", "approval_auto", "Auto", show=False),
        Binding("3", "approval_auto", "Auto", show=False),
    ]

    def __init__(
        self,
        *,
        agent: Pregel | None = None,
        assistant_id: str | None = None,
        backend: Any = None,  # CompositeBackend
        auto_approve: bool = False,
        cwd: str | Path | None = None,
        thread_id: str | None = None,
        initial_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the DeepAlpha application.

        Args:
            agent: Pre-configured LangGraph agent (optional for standalone mode)
            assistant_id: Agent identifier for memory storage
            backend: Backend for file operations
            auto_approve: Whether to start with auto-approve enabled
            cwd: Current working directory to display
            thread_id: Optional thread ID for session persistence
            initial_prompt: Optional prompt to auto-submit when session starts
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self.register_theme(
            Theme(
                name="deepalpha-dark",
                primary="#ffffff",
                secondary="#212121",
                background="#121212",
                surface="#121212",
                panel="#1c1c1c",
                accent="#333333",
                warning="#f59e0b",
                error="#ff4444",
                success="#22c55e",
                dark=True,
            )
        )
        self.theme = "deepalpha-dark"
        self._agent = agent
        self._assistant_id = assistant_id
        self._backend = backend
        self._auto_approve = auto_approve
        self._cwd = str(cwd) if cwd else str(Path.cwd())
        # Avoid collision with App._thread_id
        self._lc_thread_id = thread_id
        self._initial_prompt = initial_prompt
        self._status_bar: StatusBar | None = None
        self._chat_input: ChatInput | None = None
        self._quit_pending = False
        self._session_state: TextualSessionState | None = None
        self._ui_adapter: TextualUIAdapter | None = None
        self._pending_approval_widget: Any = None
        # Agent task tracking for interruption
        self._agent_worker: Worker[None] | None = None
        self._agent_running = False
        self._loading_widget: LoadingWidget | None = None
        self._token_tracker: TextualTokenTracker | None = None
        self._todo_widget: TodoListWidget | None = None

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        # Gather context info for welcome banner
        agent_info = get_agent_context_info(self._assistant_id)

        # Load user email and auth token from credentials
        creds = load_credentials()
        user_email = creds.email if creds else None
        auth_token = creds.cli_token if creds else None

        # Main chat area with scrollable messages
        # Input is inside scroll so it appears right below content initially
        with VerticalScroll(id="chat"):
            yield WelcomeBanner(
                model_name=settings.model_name,
                agent_info=agent_info,
                cwd=self._cwd,
                user_email=user_email,
                auth_token=auth_token,
                id="welcome-banner",
            )
            yield Container(id="messages")
            with Container(id="bottom-app-container"):
                yield ChatInput(cwd=self._cwd, id="input-area")
            yield Static(id="chat-spacer")  # Fills remaining space below input

        # Status bar at bottom
        yield StatusBar(cwd=self._cwd, id="status-bar")

    async def on_mount(self) -> None:
        """Initialize components after mount."""
        self._status_bar = self.query_one("#status-bar", StatusBar)
        self._chat_input = self.query_one("#input-area", ChatInput)

        # Set initial auto-approve state
        if self._auto_approve:
            self._status_bar.set_auto_approve(enabled=True)

        # Create session state
        self._session_state = TextualSessionState(
            auto_approve=self._auto_approve,
            thread_id=self._lc_thread_id,
        )

        # Create token tracker that updates status bar
        self._token_tracker = TextualTokenTracker(self._update_tokens, self._hide_tokens)

        # Create UI adapter if agent is provided
        if self._agent:
            self._ui_adapter = TextualUIAdapter(
                mount_message=self._mount_message,
                update_status=self._update_status,
                request_approval=self._request_approval,
                on_auto_approve_enabled=self._on_auto_approve_enabled,
                scroll_to_bottom=self._scroll_chat_to_bottom,
                show_thinking=self._show_thinking,
                hide_thinking=self._hide_thinking,
                update_todos=self._update_todos,
            )
            self._ui_adapter.set_token_tracker(self._token_tracker)

        # Focus the input (autocomplete is now built into ChatInput)
        self._chat_input.focus_input()

        # Size the spacer to fill remaining viewport below input
        self.call_after_refresh(self._size_initial_spacer)

        # Start spawn manager (background task scheduler)
        self._start_spawn_manager()

        # Load thread history if resuming a session
        if self._lc_thread_id and self._agent:
            self.call_after_refresh(lambda: asyncio.create_task(self._load_thread_history()))
        # Auto-submit initial prompt if provided (but not when resuming - let user see history first)
        elif self._initial_prompt and self._initial_prompt.strip():
            # Use call_after_refresh to ensure UI is fully mounted before submitting
            self.call_after_refresh(lambda: asyncio.create_task(self._handle_user_message(self._initial_prompt)))

    def _start_spawn_manager(self) -> None:
        """Initialize and start the spawn manager in the background."""
        from deepalpha.context import set_spawn_manager

        async def _init_spawn_manager():
            try:
                from deepalpha.spawns.manager import SpawnManager

                self._spawn_manager = SpawnManager(on_result=self._on_spawn_result)
                await self._spawn_manager.start()
                set_spawn_manager(self._spawn_manager)
            except Exception:
                logging.getLogger(__name__).debug("Failed to start spawn manager", exc_info=True)

        self._spawn_manager_task = asyncio.create_task(_init_spawn_manager())

    def _on_spawn_result(self, spawn, run) -> None:
        """Called by executor when a spawn run completes."""
        status = run.status.upper()
        preview = ""
        if run.result:
            preview = run.result[:150].replace("\n", " ")
        elif run.error:
            preview = run.error[:150]

        msg = f"[Spawn '{spawn.name}'] {status}"
        if preview:
            msg += f": {preview}"

        # Schedule mount on the event loop (called from background task)
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._mount_message(SystemMessage(msg))))
        except RuntimeError:
            pass

    def _update_status(self, message: str) -> None:
        """Update the status bar with a message."""
        if self._status_bar:
            self._status_bar.set_status_message(message)

    def _update_tokens(self, count: int) -> None:
        """Update the token count in status bar."""
        if self._status_bar:
            self._status_bar.set_tokens(count)

    def _hide_tokens(self) -> None:
        """Hide the token display during streaming."""
        if self._status_bar:
            self._status_bar.hide_tokens()

    def _scroll_chat_to_bottom(self) -> None:
        """Scroll the chat area to the bottom.

        Uses anchor() for smoother streaming - keeps scroll locked to bottom
        as new content is added without causing visual jumps.
        """
        chat = self.query_one("#chat", VerticalScroll)
        if chat.virtual_size.height > chat.size.height:
            chat.anchor()

    async def _show_thinking(self) -> None:
        """Show or reposition the thinking spinner at the bottom of messages."""
        if self._loading_widget:
            await self._loading_widget.remove()
            self._loading_widget = None

        self._loading_widget = LoadingWidget("Thinking")
        messages = self.query_one("#messages", Container)
        await messages.mount(self._loading_widget)
        self._scroll_chat_to_bottom()

    async def _hide_thinking(self) -> None:
        """Hide the thinking spinner."""
        if self._loading_widget:
            await self._loading_widget.remove()
            self._loading_widget = None

    def _update_todos(self, todos: list[dict]) -> None:
        """Update the persistent todo list widget.

        Creates the widget on first call and mounts it after ``#messages``.
        Subsequent calls update in place.

        Args:
            todos: List of todo dicts with ``content`` and ``status`` keys.
        """
        if self._todo_widget is None:
            self._todo_widget = TodoListWidget(id="todo-list")
            # mount synchronously from the app thread
            chat = self.query_one("#chat", VerticalScroll)
            messages = self.query_one("#messages", Container)
            chat.mount(self._todo_widget, after=messages)
        self._todo_widget.update_todos(todos)

    def _size_initial_spacer(self) -> None:
        """Size the spacer to fill remaining viewport below input."""
        chat = self.query_one("#chat", VerticalScroll)
        welcome = self.query_one("#welcome-banner", WelcomeBanner)
        input_container = self.query_one("#bottom-app-container", Container)
        spacer = self.query_one("#chat-spacer", Static)
        content_height = welcome.size.height + input_container.size.height + 4
        spacer_height = chat.size.height - content_height
        if spacer_height > 0:
            spacer.styles.height = spacer_height

    async def _remove_spacer(self) -> None:
        """Remove the initial spacer when first message is sent."""
        try:
            spacer = self.query_one("#chat-spacer", Static)
            await spacer.remove()
        except NoMatches:
            pass

    async def _request_approval(
        self,
        action_request: Any,
        assistant_id: str | None,
    ) -> asyncio.Future:
        """Request user approval inline in the messages area.

        Returns a Future that resolves to the user's decision.
        Mounts ApprovalMenu in the messages area (inline with chat).
        ChatInput stays visible - user can still see it.

        If another approval is already pending, queue this one.
        """
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future = loop.create_future()

        # If there's already a pending approval, wait for it to complete first
        if self._pending_approval_widget is not None:
            while self._pending_approval_widget is not None:
                await asyncio.sleep(0.1)

        # Create menu with unique ID to avoid conflicts
        unique_id = f"approval-menu-{uuid.uuid4().hex[:8]}"
        menu = ApprovalMenu(action_request, assistant_id, id=unique_id)
        menu.set_future(result_future)

        # Store reference
        self._pending_approval_widget = menu

        # Mount approval inline in messages area (not replacing ChatInput)
        try:
            messages = self.query_one("#messages", Container)
            await messages.mount(menu)
            self._scroll_chat_to_bottom()
            # Focus approval menu
            self.call_after_refresh(menu.focus)
        except Exception as e:
            self._pending_approval_widget = None
            if not result_future.done():
                result_future.set_exception(e)

        return result_future

    def _on_auto_approve_enabled(self) -> None:
        """Callback when auto-approve mode is enabled via HITL."""
        self._auto_approve = True
        if self._status_bar:
            self._status_bar.set_auto_approve(enabled=True)
        if self._session_state:
            self._session_state.auto_approve = True

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle submitted input from ChatInput widget."""
        value = event.value
        mode = event.mode

        # Reset quit pending state on any input
        self._quit_pending = False

        # Handle different modes
        if mode == "bash":
            # Bash command - strip the ! prefix
            await self._handle_bash_command(value.removeprefix("!"))
        elif mode == "command":
            # Slash command
            await self._handle_command(value)
        else:
            # Normal message - will be sent to agent
            await self._handle_user_message(value)

    def on_chat_input_mode_changed(self, event: ChatInput.ModeChanged) -> None:
        """Update status bar when input mode changes."""
        if self._status_bar:
            self._status_bar.set_mode(event.mode)

    async def on_approval_menu_decided(
        self,
        event: Any,
    ) -> None:
        """Handle approval menu decision - remove from messages and refocus input."""
        # Remove ApprovalMenu using stored reference
        if self._pending_approval_widget:
            await self._pending_approval_widget.remove()
            self._pending_approval_widget = None

        # Refocus the chat input
        if self._chat_input:
            self.call_after_refresh(self._chat_input.focus_input)

    async def _handle_bash_command(self, command: str) -> None:
        """Handle a bash command (! prefix).

        Args:
            command: The bash command to execute
        """
        # Mount user message showing the bash command
        await self._mount_message(UserMessage(f"!{command}"))

        # Execute the bash command (shell=True is intentional for user-requested bash)
        try:
            result = await asyncio.to_thread(  # noqa: S604
                subprocess.run,
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=60,
            )
            output = result.stdout.strip()
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr.strip()}"

            if output:
                # Display output as assistant message (uses markdown for code blocks)
                msg = AssistantMessage(f"```\n{output}\n```")
                await self._mount_message(msg)
                await msg.write_initial_content()
            else:
                await self._mount_message(SystemMessage("Command completed (no output)"))

            if result.returncode != 0:
                await self._mount_message(ErrorMessage(f"Exit code: {result.returncode}"))

            # Scroll to show the output
            self._scroll_chat_to_bottom()

        except subprocess.TimeoutExpired:
            await self._mount_message(ErrorMessage("Command timed out (60s limit)"))
        except OSError as e:
            await self._mount_message(ErrorMessage(str(e)))

    async def _handle_command(self, command: str) -> None:
        """Handle a slash command.

        Args:
            command: The slash command (including /)
        """
        cmd = command.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            self.exit()
        elif cmd == "/help":
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                SystemMessage("Commands: /quit, /clear, /remember, /tokens, /threads, /model, /spawns, /help")
            )

        elif cmd == "/version":
            await self._mount_message(UserMessage(command))
            # Show CLI package version
            try:
                from deepalpha._version import __version__

                await self._mount_message(SystemMessage(f"deepalpha version: {__version__}"))
            except Exception:
                await self._mount_message(SystemMessage("deepalpha version: unknown"))
        elif cmd == "/clear":
            await self._clear_messages()
            if self._token_tracker:
                self._token_tracker.reset()
            # Clear status message (e.g., "Interrupted" from previous session)
            self._update_status("")
            # Reset thread to start fresh conversation
            if self._session_state:
                new_thread_id = self._session_state.reset_thread()
                await self._mount_message(SystemMessage(f"Started new session: {new_thread_id}"))
        elif cmd == "/threads":
            await self._mount_message(UserMessage(command))
            current_thread = self._session_state.thread_id if self._session_state else None

            from deepalpha.widgets.thread_selector import ThreadSelectorScreen

            def on_thread_selected(thread_id: str | None) -> None:
                if thread_id and self._session_state and thread_id != current_thread:
                    self._session_state.thread_id = thread_id
                    self.run_worker(self._switch_thread(thread_id))
                elif thread_id == current_thread:
                    self.call_after_refresh(
                        lambda: self.run_worker(self._mount_message(SystemMessage(f"Already on thread {thread_id}")))
                    )

            self.push_screen(
                ThreadSelectorScreen(current_thread=current_thread),
                callback=on_thread_selected,
            )
        elif cmd == "/model":
            await self._mount_message(UserMessage(command))

            from deepalpha.config import settings
            from deepalpha.model_config import has_provider_credentials
            from deepalpha.widgets.api_key_input import ApiKeyInputScreen
            from deepalpha.widgets.model_selector import ModelSelectorScreen

            def on_model_selected(result: tuple[str, str] | None) -> None:
                if result is None:
                    return
                model_spec, provider = result
                if ":" in model_spec:
                    _, model_name = model_spec.split(":", 1)
                else:
                    model_name = model_spec

                if has_provider_credentials(provider) is False:
                    # OAuth providers need `deepalpha auth <provider>`, not an API key
                    from deepalpha.model_config import _FILE_CREDENTIAL_PROVIDERS

                    if provider in _FILE_CREDENTIAL_PROVIDERS:
                        auth_cmd = provider.replace("gemini-cli", "gemini")
                        self.run_worker(
                            self._mount_message(
                                SystemMessage(f"{provider} requires authentication. Run: deepalpha auth {auth_cmd}")
                            )
                        )
                        return

                    # API-key providers — prompt the user
                    def on_key_entered(key: str | None) -> None:
                        if key is None:
                            self.run_worker(self._mount_message(SystemMessage("Model switch cancelled.")))
                            return
                        self.run_worker(self._switch_model(model_name, provider))

                    self.push_screen(ApiKeyInputScreen(provider), callback=on_key_entered)
                else:
                    self.run_worker(self._switch_model(model_name, provider))

            self.push_screen(
                ModelSelectorScreen(
                    current_model=settings.model_name,
                    current_provider=settings.model_provider,
                ),
                callback=on_model_selected,
            )
        elif cmd == "/tokens":
            await self._mount_message(UserMessage(command))
            if self._token_tracker and self._token_tracker.current_context > 0:
                count = self._token_tracker.current_context
                if count >= 1000:
                    formatted = f"{count / 1000:.1f}K"
                else:
                    formatted = str(count)
                await self._mount_message(SystemMessage(f"Current context: {formatted} tokens"))
            else:
                await self._mount_message(SystemMessage("No token usage yet"))
        elif cmd == "/remember" or cmd.startswith("/remember "):
            # Extract any additional context after /remember
            additional_context = ""
            if cmd.startswith("/remember "):
                additional_context = command.strip()[len("/remember ") :].strip()

            # Build the final prompt
            if additional_context:
                final_prompt = f"{REMEMBER_PROMPT}\n\n**Additional context from user:** {additional_context}"
            else:
                final_prompt = REMEMBER_PROMPT

            # Send as a user message to the agent
            await self._handle_user_message(final_prompt)
            return  # _handle_user_message already mounts the message
        elif cmd == "/spawns":
            await self._mount_message(UserMessage(command))
            from deepalpha.context import get_spawn_manager

            manager = get_spawn_manager()
            if manager is None:
                await self._mount_message(SystemMessage("Spawn system not running."))
            else:
                spawns = await manager.list_spawns()
                if not spawns:
                    await self._mount_message(SystemMessage("No spawns. Ask the agent to create one."))
                else:
                    lines = [f"Spawns ({len(spawns)}):"]
                    for s in spawns:
                        lines.append(
                            f"  {s.id} | {s.name} | {s.status} | {s.schedule_display} | "
                            f"runs: {s.run_count}/{s.max_runs} | next: {s.next_run_at or 'N/A'}"
                        )
                    await self._mount_message(SystemMessage("\n".join(lines)))
        else:
            await self._mount_message(UserMessage(command))
            await self._mount_message(SystemMessage(f"Unknown command: {cmd}"))

    async def _handle_user_message(self, message: str) -> None:
        """Handle a user message to send to the agent.

        Args:
            message: The user's message
        """
        # Mount the user message
        await self._mount_message(UserMessage(message))

        # Check if agent is available
        if self._agent and self._ui_adapter and self._session_state:
            self._agent_running = True

            # Disable submission while agent is working (user can still type)
            if self._chat_input:
                self._chat_input.set_cursor_active(active=False)
                self._chat_input.set_submit_enabled(enabled=False)

            # Use run_worker to avoid blocking the main event loop
            # This allows the UI to remain responsive during agent execution
            self._agent_worker = self.run_worker(
                self._run_agent_task(message),
                exclusive=False,
            )
        else:
            await self._mount_message(
                SystemMessage("Agent not configured. Run with --agent flag or use standalone mode.")
            )

    async def _run_agent_task(self, message: str) -> None:
        """Run the agent task in a background worker.

        This runs in a worker thread so the main event loop stays responsive.
        """
        try:
            await execute_task_textual(
                user_input=message,
                agent=self._agent,
                assistant_id=self._assistant_id,
                session_state=self._session_state,
                adapter=self._ui_adapter,
                backend=self._backend,
            )
        except Exception as e:
            await self._mount_message(ErrorMessage(f"Agent error: {e}"))
        finally:
            # Clean up loading widget and agent state
            await self._cleanup_agent_task()

    async def _cleanup_agent_task(self) -> None:
        """Clean up after agent task completes or is cancelled."""
        self._agent_running = False
        self._agent_worker = None

        # Remove thinking spinner if present
        await self._hide_thinking()

        # Re-enable submission now that agent is done
        if self._chat_input:
            self._chat_input.set_cursor_active(active=True)
            self._chat_input.set_submit_enabled(enabled=True)

        # Ensure token display is restored (in case of early cancellation)
        if self._token_tracker:
            self._token_tracker.show()

    async def _load_thread_history(self) -> None:
        """Load and render message history when resuming a thread.

        This retrieves the checkpoint state from the agent and converts
        stored messages into UI widgets.
        """
        if not self._agent or not self._lc_thread_id:
            return

        config = {"configurable": {"thread_id": self._lc_thread_id}}

        try:
            # Get the state snapshot from the agent
            state = await self._agent.aget_state(config)
            if not state or not state.values:
                return

            messages = state.values.get("messages", [])
            if not messages:
                return

            # Track tool calls from AIMessages to match with ToolMessages
            pending_tool_calls: dict[str, dict] = {}

            for msg in messages:
                if isinstance(msg, HumanMessage):
                    # Skip system messages that were auto-injected
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if content.startswith("[SYSTEM]"):
                        continue
                    await self._mount_message(UserMessage(content))

                elif isinstance(msg, AIMessage):
                    # Render text content if present
                    content = msg.content
                    if isinstance(content, str) and content.strip():
                        widget = AssistantMessage(content)
                        await self._mount_message(widget)
                        await widget.write_initial_content()

                    # Track tool calls for later matching with ToolMessages
                    tool_calls = getattr(msg, "tool_calls", [])
                    for tc in tool_calls:
                        tc_id = tc.get("id")
                        if tc_id:
                            pending_tool_calls[tc_id] = {
                                "name": tc.get("name", "unknown"),
                                "args": tc.get("args", {}),
                            }
                            # Mount tool call widget
                            tool_widget = ToolCallMessage(
                                tc.get("name", "unknown"),
                                tc.get("args", {}),
                            )
                            await self._mount_message(tool_widget)
                            # Store widget reference for result matching
                            pending_tool_calls[tc_id]["widget"] = tool_widget

                elif isinstance(msg, ToolMessage):
                    # Match with pending tool call and show result
                    tc_id = getattr(msg, "tool_call_id", None)
                    if tc_id and tc_id in pending_tool_calls:
                        tool_info = pending_tool_calls.pop(tc_id)
                        widget = tool_info.get("widget")
                        if widget:
                            status = getattr(msg, "status", "success")
                            content = msg.content if isinstance(msg.content, str) else str(msg.content)
                            if status == "success":
                                widget.set_success(content)
                            else:
                                widget.set_error(content)

            # Mark any unmatched tool calls as interrupted (no ToolMessage result)
            for tool_info in pending_tool_calls.values():
                widget = tool_info.get("widget")
                if widget:
                    widget.set_rejected()  # Shows as interrupted/rejected in UI

            # Show system message indicating this is a resumed session
            await self._mount_message(SystemMessage(f"Resumed session: {self._lc_thread_id}"))

            # Scroll to bottom after UI renders
            def scroll_to_end() -> None:
                chat = self.query_one("#chat", VerticalScroll)
                chat.scroll_end(animate=False)

            self.call_after_refresh(scroll_to_end)

        except Exception as e:
            # Don't fail the app if history loading fails
            await self._mount_message(SystemMessage(f"Could not load history: {e}"))

    async def _mount_message(self, widget: Static) -> None:
        """Mount a message widget to the messages area.

        Args:
            widget: The message widget to mount
        """
        await self._remove_spacer()
        messages = self.query_one("#messages", Container)
        await messages.mount(widget)
        # Scroll to keep input bar visible
        input_container = self.query_one("#bottom-app-container", Container)
        input_container.scroll_visible()

    async def _clear_messages(self) -> None:
        """Clear the messages area and remove todo widget."""
        try:
            messages = self.query_one("#messages", Container)
            await messages.remove_children()
        except NoMatches:
            # Widget not found - can happen during shutdown
            pass
        if self._todo_widget is not None:
            try:
                await self._todo_widget.remove()
            except Exception:
                pass
            self._todo_widget = None

    async def _switch_thread(self, thread_id: str) -> None:
        """Switch to a different thread, clearing UI and loading its history."""
        await self._clear_messages()
        if self._token_tracker:
            self._token_tracker.reset()
        self._update_status("")

        # Update internal thread tracking
        self._lc_thread_id = thread_id

        await self._mount_message(SystemMessage(f"Switched to thread: {thread_id}"))
        await self._load_thread_history()

    async def _switch_model(self, model_name: str, provider: str | None = None) -> None:
        """Switch to a different LLM model, recreating the agent."""
        from deepalpha.agent import create_cli_agent
        from deepalpha.config import create_model, settings
        from deepalpha.sessions import generate_thread_id

        try:
            model = create_model(model_name, provider_override=provider)
        except SystemExit:
            await self._mount_message(ErrorMessage(f"Failed to switch to model: {model_name}"))
            return

        # Clear conversation and start new thread
        await self._clear_messages()
        if self._token_tracker:
            self._token_tracker.reset()
        self._update_status("")

        new_thread_id = generate_thread_id()
        if self._session_state:
            self._session_state.thread_id = new_thread_id
        self._lc_thread_id = new_thread_id

        # Recreate agent with new model
        try:
            from deepalpha.tools import fetch_url, http_request
            from deepalpha.trading_tools.research import web_search as park_web_search

            tools = [http_request, fetch_url, park_web_search]
            agent, backend = create_cli_agent(
                model=model,
                assistant_id=self._assistant_id,
                tools=tools,
                auto_approve=self._session_state.auto_approve if self._session_state else False,
                checkpointer=self._agent.checkpointer if self._agent else None,
            )
            self._agent = agent
            self._backend = backend
            provider = settings.model_provider or "unknown"
            await self._mount_message(SystemMessage(f"Switched to {provider}:{model_name} (thread: {new_thread_id})"))
        except Exception as e:
            await self._mount_message(ErrorMessage(f"Failed to recreate agent: {e}"))

    def action_quit_or_interrupt(self) -> None:
        """Handle Ctrl+C - interrupt agent, reject approval, or quit on double press.

        Priority order:
        1. If agent is running, interrupt it (preserve input)
        2. If approval menu is active, reject it
        3. If double press (quit_pending), quit
        4. Otherwise show quit hint
        """
        # If agent is running, interrupt it
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()
            self._quit_pending = False
            return

        # If approval menu is active, reject it
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()
            self._quit_pending = False
            return

        # Double Ctrl+C to quit
        if self._quit_pending:
            self.exit()
        else:
            self._quit_pending = True
            self.notify("Press Ctrl+C again to quit", timeout=3)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable app-level escape binding when a modal screen is active."""
        if action == "interrupt":
            from textual.screen import ModalScreen

            if isinstance(self.screen, ModalScreen):
                return False
        return True

    def action_interrupt(self) -> None:
        """Handle escape key - interrupt agent or reject approval.

        This is the primary way to stop a running agent.
        """
        # If agent is running, interrupt it
        if self._agent_running and self._agent_worker:
            self._agent_worker.cancel()
            return

        # If approval menu is active, reject it
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def action_quit_app(self) -> None:
        """Handle quit action (Ctrl+D)."""
        # Stop spawn manager gracefully
        if hasattr(self, "_spawn_manager") and self._spawn_manager:

            async def _stop():
                try:
                    await self._spawn_manager.stop()
                except Exception:
                    pass

            try:
                loop = asyncio.get_running_loop()
                self._spawn_stop_task = loop.create_task(_stop())
            except RuntimeError:
                pass
        self.exit()

    def action_toggle_auto_approve(self) -> None:
        """Toggle auto-approve mode."""
        self._auto_approve = not self._auto_approve
        if self._status_bar:
            self._status_bar.set_auto_approve(enabled=self._auto_approve)
        if self._session_state:
            self._session_state.auto_approve = self._auto_approve

    def action_toggle_tool_output(self) -> None:
        """Toggle expand/collapse of the most recent tool output."""
        # Find all tool messages with output, get the most recent one
        try:
            tool_messages = list(self.query(ToolCallMessage))
            # Find ones with output, toggle the most recent
            for tool_msg in reversed(tool_messages):
                if tool_msg.has_output:
                    tool_msg.toggle_output()
                    return
        except Exception:
            pass

    # Approval menu action handlers (delegated from App-level bindings)
    # NOTE: These only activate when approval widget is pending AND input is not focused
    def action_approval_up(self) -> None:
        """Handle up arrow in approval menu."""
        # Only handle if approval is active (input handles its own up for history/completion)
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_move_up()

    def action_approval_down(self) -> None:
        """Handle down arrow in approval menu."""
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_move_down()

    def action_approval_select(self) -> None:
        """Handle enter in approval menu."""
        # Only handle if approval is active AND input is not focused
        if self._pending_approval_widget and not self._is_input_focused():
            self._pending_approval_widget.action_select()

    def _is_input_focused(self) -> bool:
        """Check if the chat input (or its text area) has focus."""
        if not self._chat_input:
            return False
        focused = self.focused
        if focused is None:
            return False
        # Check if focused widget is the text area inside chat input
        return focused.id == "chat-input" or focused in self._chat_input.walk_children()

    def action_approval_yes(self) -> None:
        """Handle yes/1 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_approve()

    def action_approval_no(self) -> None:
        """Handle no/2 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def action_approval_auto(self) -> None:
        """Handle auto/3 in approval menu."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_auto()

    def action_approval_escape(self) -> None:
        """Handle escape in approval menu - reject."""
        if self._pending_approval_widget:
            self._pending_approval_widget.action_select_reject()

    def on_click(self, _event: Click) -> None:
        """Handle clicks anywhere in the terminal to focus on the command line."""
        if not self._chat_input:
            return

        self.call_after_refresh(self._chat_input.focus_input)

    def on_mouse_up(self, event: MouseUp) -> None:
        """Copy selection to clipboard on mouse release."""
        copy_selection_to_clipboard(self)


async def run_textual_app(
    *,
    agent: Pregel | None = None,
    assistant_id: str | None = None,
    backend: Any = None,  # CompositeBackend
    auto_approve: bool = False,
    cwd: str | Path | None = None,
    thread_id: str | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the Textual application.

    Args:
        agent: Pre-configured LangGraph agent (optional)
        assistant_id: Agent identifier for memory storage
        backend: Backend for file operations
        auto_approve: Whether to start with auto-approve enabled
        cwd: Current working directory to display
        thread_id: Optional thread ID for session persistence
        initial_prompt: Optional prompt to auto-submit when session starts
    """
    app = DeepAlphaApp(
        agent=agent,
        assistant_id=assistant_id,
        backend=backend,
        auto_approve=auto_approve,
        cwd=cwd,
        thread_id=thread_id,
        initial_prompt=initial_prompt,
    )
    await app.run_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_textual_app())
