from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.theme import BUILTIN_THEMES
from textual.widgets import Button, Input, Select, Static

from vibe.cli.textual_ui.terminal_theme import TERMINAL_THEME_NAME

if TYPE_CHECKING:
    from vibe.core.config import ModelConfig, VibeConfig

_ALL_THEMES = [TERMINAL_THEME_NAME] + sorted(
    k for k in BUILTIN_THEMES if k != "textual-ansi"
)


class ConfigApp(Container):
    """Enhanced configuration app with search, provider filter, and manual entry."""

    can_focus = True
    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", show=False),
        Binding("ctrl+f", "focus_search", "Search", show=False),
        Binding("ctrl+m", "focus_manual", "Manual", show=False),
    ]

    class SettingChanged(Message):
        def __init__(self, key: str, value: str) -> None:
            super().__init__()
            self.key = key
            self.value = value

    class ConfigClosed(Message):
        def __init__(self, changes: dict[str, str]) -> None:
            super().__init__()
            self.changes = changes

    def __init__(
        self,
        config: VibeConfig,
        *,
        has_terminal_theme: bool = False,
        models: list[ModelConfig] | None = None,
    ) -> None:
        super().__init__(id="config-app")
        self.config = config
        self.changes: dict[str, str] = {}

        self.themes = (
            _ALL_THEMES
            if has_terminal_theme
            else [t for t in _ALL_THEMES if t != TERMINAL_THEME_NAME]
        )

        # Store full model objects for filtering
        self._all_models: list[ModelConfig] = models if models is not None else list(config.models)

        # Get unique providers from models
        self._providers = sorted(set(m.provider for m in self._all_models))

        # Current filter state
        self._current_provider: str | None = None  # None means "all"
        self._search_query: str = ""
        self._selected_index: int = 0
        self._filtered_models: list[ModelConfig] = []

        # Widget references
        self._model_widgets: list[Static] = []
        self._scroll_container: VerticalScroll | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="config-content"):
            yield Static("Settings", classes="settings-title")

            # Provider filter section
            with Horizontal(classes="settings-row provider-filter"):
                yield Static("Provider: ", classes="settings-label")
                provider_options = [("All", "all")] + [(p, p) for p in self._providers]
                yield Select(
                    provider_options,
                    value="all",
                    id="provider-filter",
                    allow_blank=False,
                )

            # Search input
            with Horizontal(classes="settings-row"):
                yield Static("Search: ", classes="settings-label")
                yield Input(
                    placeholder="Type to filter models...",
                    id="model-search",
                )

            # Model list (scrollable)
            yield Static("", id="model-count-label")
            with VerticalScroll(id="model-list-scroll") as scroll:
                self._scroll_container = scroll
                # Model items will be added dynamically
                pass

            # Manual entry section
            with Horizontal(classes="settings-row"):
                yield Static("Manual: ", classes="settings-label")
                yield Input(
                    placeholder="Enter model alias directly (e.g., or:gpt-4)",
                    id="manual-model-input",
                )
                yield Button("Use", id="use-manual-btn", variant="primary")

            # Theme selector
            with Horizontal(classes="settings-row"):
                yield Static("Theme: ", classes="settings-label")
                theme_options = [(t, t) for t in self.themes]
                yield Select(
                    theme_options,
                    value=self.config.textual_theme,
                    id="theme-select",
                    allow_blank=False,
                )

            yield Static(
                "Tab fields  ↑↓ models  Enter select  Ctrl+F search  ESC close",
                classes="settings-help"
            )

    def on_mount(self) -> None:
        """Initialize the model list on mount."""
        self._update_filtered_models()
        self._render_model_list()
        # Focus the search input by default
        try:
            self.query_one("#model-search", Input).focus()
        except Exception:
            pass

    def _update_filtered_models(self) -> None:
        """Update the filtered model list based on current filters."""
        models = self._all_models

        # Filter by provider
        if self._current_provider and self._current_provider != "all":
            models = [m for m in models if m.provider == self._current_provider]

        # Filter by search query
        if self._search_query:
            query = self._search_query.lower()
            models = [
                m for m in models
                if query in m.alias.lower() or query in m.name.lower() or query in m.provider.lower()
            ]

        self._filtered_models = models

        # Reset selection if out of bounds
        if self._selected_index >= len(self._filtered_models):
            self._selected_index = max(0, len(self._filtered_models) - 1)

        # Update count label
        try:
            count_label = self.query_one("#model-count-label", Static)
            total = len(self._all_models)
            filtered = len(self._filtered_models)
            if filtered == total:
                count_label.update(f"Models ({filtered}):")
            else:
                count_label.update(f"Models ({filtered} of {total}):")
        except Exception:
            pass

    def _render_model_list(self) -> None:
        """Render the model list in the scroll container."""
        if not self._scroll_container:
            return

        # Clear existing widgets
        for widget in self._model_widgets:
            widget.remove()
        self._model_widgets.clear()

        # Group models by provider for better organization
        if not self._filtered_models:
            widget = Static("  No models match your search", classes="settings-option")
            self._scroll_container.mount(widget)
            self._model_widgets.append(widget)
            return

        # Render models
        current_active = self.changes.get("active_model", self.config.active_model)

        for i, model in enumerate(self._filtered_models):
            is_selected = i == self._selected_index
            is_active = model.alias == current_active

            cursor = "› " if is_selected else "  "
            active_marker = " ✓" if is_active else ""

            # Format: cursor + alias + [provider] + active marker
            text = f"{cursor}{model.alias:<30} [{model.provider}]{active_marker}"

            widget = Static(text, classes="settings-option model-item")
            widget.add_class("model-selected" if is_selected else "model-unselected")
            if is_active:
                widget.add_class("model-active")

            self._scroll_container.mount(widget)
            self._model_widgets.append(widget)

    def _update_model_selection(self) -> None:
        """Update just the selection styling without full re-render."""
        current_active = self.changes.get("active_model", self.config.active_model)

        for i, widget in enumerate(self._model_widgets):
            if i >= len(self._filtered_models):
                break

            model = self._filtered_models[i]
            is_selected = i == self._selected_index
            is_active = model.alias == current_active

            cursor = "› " if is_selected else "  "
            active_marker = " ✓" if is_active else ""

            text = f"{cursor}{model.alias:<30} [{model.provider}]{active_marker}"
            widget.update(text)

            widget.remove_class("model-selected", "model-unselected")
            widget.add_class("model-selected" if is_selected else "model-unselected")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select widget changes."""
        select_id = event.select.id
        value = str(event.value) if event.value is not None else ""

        if select_id == "provider-filter":
            self._current_provider = value if value != "all" else None
            self._update_filtered_models()
            self._render_model_list()
        elif select_id == "theme-select":
            self.changes["textual_theme"] = value
            self.post_message(self.SettingChanged(key="textual_theme", value=value))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "model-search":
            self._search_query = event.value
            self._update_filtered_models()
            self._render_model_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "model-search":
            # Select the currently highlighted model
            self._select_current_model()
        elif event.input.id == "manual-model-input":
            # Use the manually entered model
            self._use_manual_model(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "use-manual-btn":
            try:
                manual_input = self.query_one("#manual-model-input", Input)
                self._use_manual_model(manual_input.value)
            except Exception:
                pass

    def _select_current_model(self) -> None:
        """Select the currently highlighted model."""
        if self._filtered_models and 0 <= self._selected_index < len(self._filtered_models):
            model = self._filtered_models[self._selected_index]
            self.changes["active_model"] = model.alias
            self.post_message(self.SettingChanged(key="active_model", value=model.alias))
            self._update_model_selection()

    def _use_manual_model(self, alias: str) -> None:
        """Use a manually entered model alias."""
        alias = alias.strip()
        if alias:
            self.changes["active_model"] = alias
            self.post_message(self.SettingChanged(key="active_model", value=alias))
            # Update the display
            self._update_model_selection()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for model list navigation."""
        # Only handle navigation when focus is on search or within the model list
        if event.key == "up":
            if self._filtered_models:
                self._selected_index = (self._selected_index - 1) % len(self._filtered_models)
                self._update_model_selection()
                self._scroll_to_selected()
                event.prevent_default()
        elif event.key == "down":
            if self._filtered_models:
                self._selected_index = (self._selected_index + 1) % len(self._filtered_models)
                self._update_model_selection()
                self._scroll_to_selected()
                event.prevent_default()
        elif event.key == "enter":
            # If we're in the search input, select the model
            focused = self.app.focused
            if focused and getattr(focused, 'id', None) == "model-search":
                self._select_current_model()
                event.prevent_default()

    def _scroll_to_selected(self) -> None:
        """Scroll to ensure the selected model is visible."""
        if self._scroll_container and self._model_widgets and self._selected_index < len(self._model_widgets):
            widget = self._model_widgets[self._selected_index]
            widget.scroll_visible()

    def action_focus_search(self) -> None:
        """Focus the search input."""
        try:
            self.query_one("#model-search", Input).focus()
        except Exception:
            pass

    def action_focus_manual(self) -> None:
        """Focus the manual input."""
        try:
            self.query_one("#manual-model-input", Input).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.post_message(self.ConfigClosed(changes=self.changes.copy()))
