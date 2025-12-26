from __future__ import annotations

import os
from typing import TYPE_CHECKING, ClassVar

from dotenv import set_key
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import Input, Static

from vibe.core.paths.global_paths import GLOBAL_ENV_FILE

if TYPE_CHECKING:
    from vibe.core.config import ProviderConfig, VibeConfig


class ProviderApp(Container):
    """Widget for managing API providers and keys."""

    can_focus = True
    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "select_provider", "Select", show=False),
        Binding("escape", "close", "Close", show=False),
    ]

    class ProviderClosed(Message):
        def __init__(self, changed: bool = False) -> None:
            super().__init__()
            self.changed = changed

    class ProviderSelected(Message):
        def __init__(self, provider_name: str) -> None:
            super().__init__()
            self.provider_name = provider_name

    def __init__(self, config: VibeConfig) -> None:
        super().__init__(id="provider-app")
        self.config = config
        self.selected_index = 0
        self.providers = self._get_providers_with_status()
        self.mode: str = "list"  # "list" or "input"
        self.input_provider: ProviderConfig | None = None
        self._changed = False

        self.title_widget: Static | None = None
        self.provider_widgets: list[Static] = []
        self.help_widget: Static | None = None
        self.input_widget: Input | None = None
        self.input_container: Vertical | None = None

    def _get_providers_with_status(self) -> list[dict]:
        """Get list of providers with their configuration status."""
        providers = []
        for provider in self.config.providers:
            has_key = False
            if provider.api_key_env_var:
                has_key = bool(os.getenv(provider.api_key_env_var))

            # Count models for this provider
            model_count = sum(1 for m in self.config.models if m.provider == provider.name)

            providers.append({
                "provider": provider,
                "has_key": has_key,
                "model_count": model_count,
                "is_dynamic": provider.fetch_models,
            })
        return providers

    def compose(self) -> ComposeResult:
        with Vertical(id="provider-content"):
            self.title_widget = Static("Providers", classes="settings-title")
            yield self.title_widget

            yield Static("")

            for _ in self.providers:
                widget = Static("", classes="settings-option")
                self.provider_widgets.append(widget)
                yield widget

            yield Static("")

            # Input container (hidden by default)
            with Vertical(id="provider-input-container") as input_container:
                self.input_container = input_container
                self.input_container.display = False
                yield Static("", id="input-label")
                self.input_widget = Input(
                    password=True,
                    id="api-key-input",
                    placeholder="Paste API key here",
                )
                yield self.input_widget
                yield Static("", id="input-feedback")

            self.help_widget = Static(
                "↑↓ navigate  Enter set key  ESC close", classes="settings-help"
            )
            yield self.help_widget

    def on_mount(self) -> None:
        self._update_display()
        self.focus()

    def _update_display(self) -> None:
        for i, (prov_info, widget) in enumerate(
            zip(self.providers, self.provider_widgets, strict=True)
        ):
            is_selected = i == self.selected_index
            cursor = "› " if is_selected else "  "

            provider = prov_info["provider"]
            has_key = prov_info["has_key"]
            is_dynamic = prov_info["is_dynamic"]

            status = "✓" if has_key else "✗"
            status_class = "configured" if has_key else "not-configured"

            dynamic_tag = " [dynamic]" if is_dynamic else ""
            text = f"{cursor}[{status}] {provider.name}{dynamic_tag}"

            widget.update(text)

            widget.remove_class("settings-value-cycle-selected", "settings-value-cycle-unselected")
            if is_selected:
                widget.add_class("settings-value-cycle-selected")
            else:
                widget.add_class("settings-value-cycle-unselected")

    def action_move_up(self) -> None:
        if self.mode == "list":
            self.selected_index = (self.selected_index - 1) % len(self.providers)
            self._update_display()

    def action_move_down(self) -> None:
        if self.mode == "list":
            self.selected_index = (self.selected_index + 1) % len(self.providers)
            self._update_display()

    def action_select_provider(self) -> None:
        if self.mode == "list":
            self._show_key_input()
        elif self.mode == "input" and self.input_widget:
            self._save_api_key(self.input_widget.value)

    def _show_key_input(self) -> None:
        """Show the API key input for the selected provider."""
        prov_info = self.providers[self.selected_index]
        provider = prov_info["provider"]

        if not provider.api_key_env_var:
            # This provider doesn't need an API key (e.g., local)
            return

        self.input_provider = provider
        self.mode = "input"

        if self.input_container:
            self.input_container.display = True

        label = self.query_one("#input-label", Static)
        label.update(f"Enter API key for {provider.name} ({provider.api_key_env_var}):")

        feedback = self.query_one("#input-feedback", Static)
        feedback.update("Press Enter to save, ESC to cancel")

        if self.input_widget:
            self.input_widget.value = ""
            self.input_widget.focus()

        if self.help_widget:
            self.help_widget.update("Enter save  ESC cancel")

    def _save_api_key(self, api_key: str) -> None:
        """Save the API key to the .env file."""
        if not api_key.strip() or not self.input_provider:
            self._hide_key_input()
            return

        env_key = self.input_provider.api_key_env_var
        provider_name = self.input_provider.name

        # Set in environment
        os.environ[env_key] = api_key

        # Save to .env file
        try:
            GLOBAL_ENV_FILE.path.parent.mkdir(parents=True, exist_ok=True)
            set_key(GLOBAL_ENV_FILE.path, env_key, api_key)

            feedback = self.query_one("#input-feedback", Static)
            feedback.update(f"✓ API key saved for {provider_name}")
            self._changed = True

            # Refresh provider status
            self.providers = self._get_providers_with_status()
            self._update_display()

        except OSError as e:
            feedback = self.query_one("#input-feedback", Static)
            feedback.update(f"✗ Error saving: {e}")

        self._hide_key_input()

    def _hide_key_input(self) -> None:
        """Hide the API key input."""
        self.mode = "list"
        self.input_provider = None

        if self.input_container:
            self.input_container.display = False

        if self.help_widget:
            self.help_widget.update("↑↓ navigate  Enter set key  ESC close")

        self.focus()

    def action_close(self) -> None:
        if self.mode == "input":
            self._hide_key_input()
        else:
            self.post_message(self.ProviderClosed(changed=self._changed))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.mode == "input":
            self._save_api_key(event.value)

    def key_escape(self) -> None:
        self.action_close()
