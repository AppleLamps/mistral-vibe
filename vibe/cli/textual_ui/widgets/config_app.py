from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical, Horizontal
from textual.message import Message
from textual.theme import BUILTIN_THEMES
from textual.widgets import Static, Select

from vibe.cli.textual_ui.terminal_theme import TERMINAL_THEME_NAME

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig

_ALL_THEMES = [TERMINAL_THEME_NAME] + sorted(
    k for k in BUILTIN_THEMES if k != "textual-ansi"
)


class ConfigApp(Container):
    can_focus = True
    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Close", show=False),
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
        models: list[str] | None = None,
    ) -> None:
        super().__init__(id="config-app")
        self.config = config
        self.changes: dict[str, str] = {}

        self.themes = (
            _ALL_THEMES
            if has_terminal_theme
            else [t for t in _ALL_THEMES if t != TERMINAL_THEME_NAME]
        )

        # Use provided models list or fall back to config.models
        self.model_aliases = models if models is not None else [m.alias for m in self.config.models]

    def compose(self) -> ComposeResult:
        with Vertical(id="config-content"):
            yield Static("Settings", classes="settings-title")
            yield Static("")

            # Model selector
            with Horizontal(classes="settings-row"):
                yield Static("Model: ", classes="settings-label")
                # Ensure current model is in the options list
                all_models = list(self.model_aliases)
                if self.config.active_model not in all_models:
                    all_models.insert(0, self.config.active_model)
                model_options = [(m, m) for m in all_models]
                yield Select(
                    model_options,
                    value=self.config.active_model,
                    id="model-select",
                    allow_blank=False,
                )

            yield Static("")

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

            yield Static("")
            yield Static(
                "Tab switch fields  ↑↓ navigate options  Enter select  ESC close",
                classes="settings-help"
            )

    def on_mount(self) -> None:
        # Focus the model select by default
        try:
            self.query_one("#model-select", Select).focus()
        except Exception:
            pass

    def on_select_changed(self, event: Select.Changed) -> None:
        select_id = event.select.id
        value = str(event.value) if event.value is not None else ""

        if select_id == "model-select":
            self.changes["active_model"] = value
            self.post_message(self.SettingChanged(key="active_model", value=value))
        elif select_id == "theme-select":
            self.changes["textual_theme"] = value
            self.post_message(self.SettingChanged(key="textual_theme", value=value))

    def action_close(self) -> None:
        self.post_message(self.ConfigClosed(changes=self.changes.copy()))
