"""Persistent todo list widget for deepalpha-cli."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static


class TodoListWidget(Static):
    """Persistent widget showing the current todo list.

    Auto-hides when all items are completed by adding the
    ``all-completed`` CSS class (``display: none``).
    """

    DEFAULT_CSS = """
    TodoListWidget {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }

    TodoListWidget.all-completed {
        display: none;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._todos: list[dict] = []

    def update_todos(self, todos: list[dict]) -> None:
        """Update the displayed todo list.

        Args:
            todos: List of todo dicts with ``content`` and ``status`` keys.
        """
        self._todos = todos

        all_done = all(t.get("status") in ("completed", "done") for t in todos if isinstance(t, dict))

        if all_done:
            self.add_class("all-completed")
        else:
            self.remove_class("all-completed")

        self.update(self._render_todos())

    def _render_todos(self) -> Text:
        """Render todos as a Rich Text checklist."""
        text = Text()
        for i, todo in enumerate(self._todos, 1):
            if not isinstance(todo, dict):
                continue
            content = todo.get("content", "")
            status = todo.get("status", "pending")
            if i > 1:
                text.append("\n")
            text.append(f"{i}. ")
            if status in ("completed", "done"):
                text.append("\u2713 ", style="green")
            elif status == "in_progress":
                text.append("\u25c9 ", style="yellow")
            else:
                text.append("\u25cb ", style="dim")
            text.append(content)
        return text
