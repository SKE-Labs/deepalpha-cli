"""Interactive model selector screen for /model command."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, VerticalScroll
from textual.events import Click, Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

from deepalpha.model_config import get_available_models, has_provider_credentials


class ModelOption(Static):
    """A clickable model option in the selector."""

    def __init__(
        self,
        label: str,
        model_spec: str,
        provider: str,
        index: int,
        *,
        has_creds: bool | None = True,
        classes: str = "",
    ) -> None:
        super().__init__(label, classes=classes)
        self.model_spec = model_spec
        self.provider = provider
        self.index = index
        self.has_creds = has_creds

    class Clicked(Message):
        """Message sent when a model option is clicked."""

        def __init__(self, model_spec: str, provider: str, index: int) -> None:
            super().__init__()
            self.model_spec = model_spec
            self.provider = provider
            self.index = index

    def on_click(self, event: Click) -> None:
        event.stop()
        self.post_message(self.Clicked(self.model_spec, self.provider, self.index))


class ModelSelectorScreen(ModalScreen[tuple[str, str] | None]):
    """Full-screen modal for model selection.

    Displays available models grouped by provider with keyboard navigation
    and search filtering. Current model is highlighted.

    Returns (model_spec, provider) tuple on selection, or None on cancel.
    """

    ESCAPE_TO_MINIMIZE = False

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
    ModelSelectorScreen {
        align: center middle;
    }

    ModelSelectorScreen > Vertical {
        width: 70;
        max-width: 90%;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ModelSelectorScreen .model-selector-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    ModelSelectorScreen #model-filter {
        margin-bottom: 1;
        border: solid $primary-lighten-2;
    }

    ModelSelectorScreen #model-filter:focus {
        border: solid $primary;
    }

    ModelSelectorScreen .model-list {
        height: 1fr;
        min-height: 5;
        scrollbar-gutter: stable;
        background: $background;
    }

    ModelSelectorScreen #model-options {
        height: auto;
    }

    ModelSelectorScreen .model-provider-header {
        color: $primary;
        margin-top: 1;
    }

    ModelSelectorScreen #model-options > .model-provider-header:first-child {
        margin-top: 0;
    }

    ModelSelectorScreen .model-option {
        height: 1;
        padding: 0 1;
    }

    ModelSelectorScreen .model-option:hover {
        background: $surface-lighten-1;
    }

    ModelSelectorScreen .model-option-selected {
        background: $primary;
        text-style: bold;
    }

    ModelSelectorScreen .model-option-selected:hover {
        background: $primary-lighten-1;
    }

    ModelSelectorScreen .model-option-current {
        text-style: italic;
    }

    ModelSelectorScreen .model-selector-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(
        self,
        current_model: str | None = None,
        current_provider: str | None = None,
    ) -> None:
        super().__init__()
        self._current_model = current_model
        self._current_provider = current_provider

        # Build flat list of (model_spec, provider)
        self._all_models: list[tuple[str, str]] = []
        for provider, models in get_available_models().items():
            for model in models:
                model_spec = f"{provider}:{model}"
                self._all_models.append((model_spec, provider))

        self._filtered_models: list[tuple[str, str]] = list(self._all_models)
        self._selected_index = self._find_current_model_index()
        self._options_container: Container | None = None
        self._option_widgets: list[ModelOption] = []
        self._filter_text = ""
        self._current_spec: str | None = None
        if current_model and current_provider:
            self._current_spec = f"{current_provider}:{current_model}"

    def _find_current_model_index(self) -> int:
        if not self._current_model or not self._current_provider:
            return 0
        current_spec = f"{self._current_provider}:{self._current_model}"
        for i, (model_spec, _) in enumerate(self._filtered_models):
            if model_spec == current_spec:
                return i
        return 0

    def compose(self) -> ComposeResult:
        with Vertical():
            if self._current_model and self._current_provider:
                current_spec = f"{self._current_provider}:{self._current_model}"
                title = f"Select Model (current: {current_spec})"
            elif self._current_model:
                title = f"Select Model (current: {self._current_model})"
            else:
                title = "Select Model"
            yield Static(title, classes="model-selector-title")

            yield Input(
                placeholder="Type to filter or enter provider:model...",
                id="model-filter",
            )

            with VerticalScroll(classes="model-list"):
                self._options_container = Container(id="model-options")
                yield self._options_container

            yield Static(
                "↑/↓/tab navigate · Enter select · Esc cancel",
                classes="model-selector-help",
            )

    async def on_mount(self) -> None:
        await self._update_display()
        filter_input = self.query_one("#model-filter", Input)
        filter_input.focus()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter_text = event.value.lower()
        self._update_filtered_list()
        self.call_after_refresh(self._update_display)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_select()

    def on_model_option_clicked(self, event: ModelOption.Clicked) -> None:
        self._selected_index = event.index
        self.dismiss((event.model_spec, event.provider))

    def _update_filtered_list(self) -> None:
        if not self._filter_text:
            self._filtered_models = list(self._all_models)
            self._selected_index = self._find_current_model_index()
        else:
            self._filtered_models = [
                (model_spec, provider)
                for model_spec, provider in self._all_models
                if self._filter_text in model_spec.lower()
            ]
            if self._selected_index >= len(self._filtered_models):
                self._selected_index = max(0, len(self._filtered_models) - 1)

    async def _update_display(self) -> None:
        if not self._options_container:
            return

        await self._options_container.remove_children()
        self._option_widgets = []

        if not self._filtered_models:
            await self._options_container.mount(Static("[dim]No matching models[/dim]"))
            return

        # Group by provider
        by_provider: dict[str, list[str]] = {}
        for model_spec, provider in self._filtered_models:
            by_provider.setdefault(provider, []).append(model_spec)

        flat_index = 0
        selected_widget: ModelOption | None = None
        all_widgets: list[Static] = []

        for provider, model_specs in by_provider.items():
            has_creds = has_provider_credentials(provider)
            if has_creds is True:
                cred_indicator = "[green]✓[/green]"
            elif has_creds is False:
                cred_indicator = "[yellow]⚠ missing credentials[/yellow]"
            else:
                cred_indicator = "[dim]? credentials unknown[/dim]"
            all_widgets.append(
                Static(
                    f"[bold]{provider}[/bold] {cred_indicator}",
                    classes="model-provider-header",
                )
            )

            for model_spec in model_specs:
                is_current = model_spec == self._current_spec
                is_selected = flat_index == self._selected_index

                classes = "model-option"
                if is_selected:
                    classes += " model-option-selected"
                if is_current:
                    classes += " model-option-current"

                label = self._format_option_label(
                    model_spec,
                    selected=is_selected,
                    current=is_current,
                    has_creds=has_creds,
                )
                widget = ModelOption(
                    label=label,
                    model_spec=model_spec,
                    provider=provider,
                    index=flat_index,
                    has_creds=has_creds,
                    classes=classes,
                )
                all_widgets.append(widget)
                self._option_widgets.append(widget)

                if is_selected:
                    selected_widget = widget
                flat_index += 1

        await self._options_container.mount(*all_widgets)

        if selected_widget:
            if self._selected_index == 0:
                scroll_container = self.query_one(".model-list", VerticalScroll)
                scroll_container.scroll_home(animate=False)
            else:
                selected_widget.scroll_visible(animate=False)

    @staticmethod
    def _format_option_label(
        model_spec: str,
        *,
        selected: bool,
        current: bool,
        has_creds: bool | None,
    ) -> str:
        cursor = "> " if selected else "  "
        if not has_creds:
            spec_text = f"[yellow]{model_spec}[/yellow]"
        else:
            spec_text = model_spec
        suffix = " [dim](current)[/dim]" if current else ""
        return f"{cursor}{spec_text}{suffix}"

    def _move_selection(self, delta: int) -> None:
        if not self._filtered_models or not self._option_widgets:
            return

        count = len(self._filtered_models)
        old_index = self._selected_index
        new_index = (old_index + delta) % count
        self._selected_index = new_index

        old_widget = self._option_widgets[old_index]
        old_widget.remove_class("model-option-selected")
        old_widget.update(
            self._format_option_label(
                old_widget.model_spec,
                selected=False,
                current=old_widget.model_spec == self._current_spec,
                has_creds=old_widget.has_creds,
            )
        )

        new_widget = self._option_widgets[new_index]
        new_widget.add_class("model-option-selected")
        new_widget.update(
            self._format_option_label(
                new_widget.model_spec,
                selected=True,
                current=new_widget.model_spec == self._current_spec,
                has_creds=new_widget.has_creds,
            )
        )

        if new_index == 0:
            scroll_container = self.query_one(".model-list", VerticalScroll)
            scroll_container.scroll_home(animate=False)
        else:
            new_widget.scroll_visible()

    def action_move_up(self) -> None:
        self._move_selection(-1)

    def action_move_down(self) -> None:
        self._move_selection(1)

    def _visible_page_size(self) -> int:
        default_page_size = 10
        try:
            scroll = self.query_one(".model-list", VerticalScroll)
            height = scroll.size.height
        except Exception:
            return default_page_size
        if height <= 0:
            return default_page_size
        total_models = len(self._filtered_models)
        if total_models == 0:
            return default_page_size
        num_headers = len(self.query(".model-provider-header"))
        header_rows = max(0, num_headers * 2 - 1) if num_headers else 0
        total_rows = total_models + header_rows
        return max(1, int(height * total_models / total_rows))

    def action_page_up(self) -> None:
        if not self._filtered_models:
            return
        page = self._visible_page_size()
        target = max(0, self._selected_index - page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_page_down(self) -> None:
        if not self._filtered_models:
            return
        count = len(self._filtered_models)
        page = self._visible_page_size()
        target = min(count - 1, self._selected_index + page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_select(self) -> None:
        if self._filtered_models:
            model_spec, provider = self._filtered_models[self._selected_index]
            self.dismiss((model_spec, provider))
            return

        # No matches — check if user typed a custom provider:model spec
        filter_input = self.query_one("#model-filter", Input)
        custom_input = filter_input.value.strip()

        if custom_input and ":" in custom_input:
            provider = custom_input.split(":", 1)[0]
            self.dismiss((custom_input, provider))
        elif custom_input:
            self.dismiss((custom_input, ""))

    def action_cancel(self) -> None:
        self.dismiss(None)
