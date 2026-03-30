"""Interactive thread selector screen for /threads command."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Click

from embient.sessions import _format_timestamp, list_threads

logger = logging.getLogger(__name__)

# Column widths for aligned formatting
_COL_TID = 10
_COL_AGENT = 14


class ThreadOption(Static):
    """A clickable thread option in the selector."""

    def __init__(
        self,
        label: str,
        thread_id: str,
        index: int,
        *,
        classes: str = "",
    ) -> None:
        super().__init__(label, classes=classes)
        self.thread_id = thread_id
        self.index = index

    class Clicked(Message):
        """Message sent when a thread option is clicked."""

        def __init__(self, thread_id: str, index: int) -> None:
            super().__init__()
            self.thread_id = thread_id
            self.index = index

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Clicked(self.thread_id, self.index))


class ThreadSelectorScreen(ModalScreen[str | None]):
    """Modal dialog for browsing and resuming threads.

    Displays recent threads with keyboard navigation. The current thread
    is pre-selected and visually marked.

    Returns a thread_id string on selection, or None on cancel.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("k", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("j", "move_down", "Down", show=False, priority=True),
        Binding("tab", "move_down", "Down", show=False, priority=True),
        Binding("shift+tab", "move_up", "Up", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    CSS = """
    ThreadSelectorScreen {
        align: center middle;
    }

    ThreadSelectorScreen > Vertical {
        width: 70;
        max-width: 90%;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ThreadSelectorScreen .thread-selector-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    ThreadSelectorScreen .thread-list-header {
        height: 1;
        padding: 0 2 0 1;
        color: $text-muted;
        text-style: bold;
    }

    ThreadSelectorScreen .thread-list {
        height: 1fr;
        min-height: 5;
        scrollbar-gutter: stable;
        background: $background;
    }

    ThreadSelectorScreen .thread-option {
        height: 1;
        padding: 0 1;
    }

    ThreadSelectorScreen .thread-option:hover {
        background: $surface-lighten-1;
    }

    ThreadSelectorScreen .thread-option-selected {
        background: $primary;
        text-style: bold;
    }

    ThreadSelectorScreen .thread-option-selected:hover {
        background: $primary-lighten-1;
    }

    ThreadSelectorScreen .thread-option-current {
        text-style: italic;
    }

    ThreadSelectorScreen .thread-selector-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }

    ThreadSelectorScreen .thread-empty {
        color: $text-muted;
        text-align: center;
        margin-top: 2;
    }
    """

    def __init__(self, current_thread: str | None = None) -> None:
        super().__init__()
        self._current_thread = current_thread
        self._threads: list[dict] = []
        self._selected_index = 0
        self._option_widgets: list[ThreadOption] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            if self._current_thread:
                title = f"Select Thread (current: {self._current_thread})"
            else:
                title = "Select Thread"
            yield Static(title, classes="thread-selector-title")
            yield Static(self._format_header(), classes="thread-list-header")

            with VerticalScroll(classes="thread-list"):
                yield Static(
                    "[dim]Loading threads...[/dim]",
                    classes="thread-empty",
                    id="thread-loading",
                )

            yield Static(
                "↑/↓/tab navigate · Enter select · Esc cancel",
                classes="thread-selector-help",
            )

    async def on_mount(self) -> None:
        try:
            self._threads = await list_threads(limit=20)
        except Exception as exc:
            logger.exception("Failed to load threads for thread selector")
            scroll = self.query_one(".thread-list", VerticalScroll)
            await scroll.remove_children()
            await scroll.mount(
                Static(
                    f"[red]Failed to load threads: {exc}. Press Esc to close.[/red]",
                    classes="thread-empty",
                )
            )
            self.focus()
            return

        for i, t in enumerate(self._threads):
            if t["thread_id"] == self._current_thread:
                self._selected_index = i
                break

        await self._build_list()
        self.focus()

    async def _build_list(self) -> None:
        scroll = self.query_one(".thread-list", VerticalScroll)
        await scroll.remove_children()
        self._option_widgets = []

        if not self._threads:
            await scroll.mount(Static("[dim]No threads found[/dim]", classes="thread-empty"))
            return

        selected_widget: ThreadOption | None = None

        for i, thread in enumerate(self._threads):
            is_current = thread["thread_id"] == self._current_thread
            is_selected = i == self._selected_index

            classes = "thread-option"
            if is_selected:
                classes += " thread-option-selected"
            if is_current:
                classes += " thread-option-current"

            label = self._format_option_label(thread, selected=is_selected, current=is_current)
            widget = ThreadOption(
                label=label,
                thread_id=thread["thread_id"],
                index=i,
                classes=classes,
            )
            self._option_widgets.append(widget)

            if is_selected:
                selected_widget = widget

        await scroll.mount(*self._option_widgets)

        if selected_widget:
            if self._selected_index == 0:
                scroll.scroll_home(animate=False)
            else:
                selected_widget.scroll_visible(animate=False)

    @staticmethod
    def _format_header() -> str:
        return f"  {'Thread':<{_COL_TID}}  {'Agent':<{_COL_AGENT}}  Updated"

    @staticmethod
    def _format_option_label(
        thread: dict,
        *,
        selected: bool,
        current: bool,
    ) -> str:
        cursor = "> " if selected else "  "
        tid = thread["thread_id"][:_COL_TID]
        agent = (thread.get("agent_name") or "unknown")[:_COL_AGENT]
        timestamp = _format_timestamp(thread.get("updated_at"))

        label = f"{cursor}{tid:<{_COL_TID}}  {agent:<{_COL_AGENT}}  {timestamp}"
        if current:
            label += " [dim](current)[/dim]"
        return label

    def _move_selection(self, delta: int) -> None:
        if not self._threads or not self._option_widgets:
            return

        count = len(self._threads)
        old_index = self._selected_index
        new_index = (old_index + delta) % count
        self._selected_index = new_index

        old_widget = self._option_widgets[old_index]
        old_widget.remove_class("thread-option-selected")
        old_thread = self._threads[old_index]
        old_widget.update(
            self._format_option_label(
                old_thread,
                selected=False,
                current=old_thread["thread_id"] == self._current_thread,
            )
        )

        new_widget = self._option_widgets[new_index]
        new_widget.add_class("thread-option-selected")
        new_thread = self._threads[new_index]
        new_widget.update(
            self._format_option_label(
                new_thread,
                selected=True,
                current=new_thread["thread_id"] == self._current_thread,
            )
        )

        if new_index == 0:
            scroll = self.query_one(".thread-list", VerticalScroll)
            scroll.scroll_home(animate=False)
        else:
            new_widget.scroll_visible()

    def action_move_up(self) -> None:
        self._move_selection(-1)

    def action_move_down(self) -> None:
        self._move_selection(1)

    def _visible_page_size(self) -> int:
        default_page_size = 10
        try:
            scroll = self.query_one(".thread-list", VerticalScroll)
            height = scroll.size.height
        except Exception:
            return default_page_size
        if height <= 0:
            return default_page_size
        return max(1, height)

    def action_page_up(self) -> None:
        if not self._threads:
            return
        page = self._visible_page_size()
        target = max(0, self._selected_index - page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_page_down(self) -> None:
        if not self._threads:
            return
        count = len(self._threads)
        page = self._visible_page_size()
        target = min(count - 1, self._selected_index + page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_select(self) -> None:
        if self._threads:
            thread_id = self._threads[self._selected_index]["thread_id"]
            self.dismiss(thread_id)

    def on_thread_option_clicked(self, event: ThreadOption.Clicked) -> None:
        if 0 <= event.index < len(self._threads):
            self._selected_index = event.index
            self.dismiss(event.thread_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
