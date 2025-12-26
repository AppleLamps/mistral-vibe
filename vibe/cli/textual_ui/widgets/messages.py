from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownStream

from vibe.cli.textual_ui.widgets.spinner import SpinnerMixin, SpinnerType
from vibe.core.error_logger import log_error as persistent_log_error


logger = logging.getLogger(__name__)

# Maximum lines to show in a code block before truncating
MAX_CODE_BLOCK_LINES = 25
# Minimum interval between markdown stream writes (for debouncing)
MIN_WRITE_INTERVAL_MS = 50  # 50ms = max 20 writes/second
CODE_BLOCK_PATTERN = re.compile(r"(```[\w]*\n)(.*?)(```)", re.DOTALL)


def _truncate_code_block(match: re.Match) -> str:
    """Truncate a code block if it exceeds MAX_CODE_BLOCK_LINES."""
    opener = match.group(1)  # ```lang\n
    code = match.group(2)
    closer = match.group(3)  # ```

    lines = code.split("\n")
    if len(lines) <= MAX_CODE_BLOCK_LINES:
        return match.group(0)  # Return unchanged

    truncated_lines = lines[:MAX_CODE_BLOCK_LINES]
    remaining = len(lines) - MAX_CODE_BLOCK_LINES
    truncated_lines.append(f"\n... ({remaining} more lines truncated)")
    return opener + "\n".join(truncated_lines) + "\n" + closer


def truncate_code_blocks(content: str) -> str:
    """Truncate all code blocks in content that exceed the line limit."""
    return CODE_BLOCK_PATTERN.sub(_truncate_code_block, content)


class NonSelectableStatic(Static):
    @property
    def text_selection(self) -> None:
        return None

    @text_selection.setter
    def text_selection(self, value: Any) -> None:
        pass

    def get_selection(self, selection: Any) -> None:
        return None


class ExpandingBorder(NonSelectableStatic):
    def render(self) -> str:
        height = self.size.height
        return "\n".join(["⎢"] * (height - 1) + ["⎣"])

    def on_resize(self) -> None:
        self.refresh()


class UserMessage(Static):
    def __init__(self, content: str, pending: bool = False) -> None:
        super().__init__()
        self.add_class("user-message")
        self._content = content
        self._pending = pending

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-message-container"):
            yield NonSelectableStatic("> ", classes="user-message-prompt")
            yield Static(self._content, markup=False, classes="user-message-content")
            if self._pending:
                self.add_class("pending")

    async def set_pending(self, pending: bool) -> None:
        if pending == self._pending:
            return

        self._pending = pending

        if pending:
            self.add_class("pending")
            return

        self.remove_class("pending")


class StreamingMessageBase(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        # Debouncing for snappier UI
        self._last_write_time: float = 0.0
        self._pending_write: str = ""
        # Error recovery: track if streaming has failed
        self._stream_failed: bool = False

    def _get_markdown(self) -> Markdown:
        if self._markdown is None:
            raise RuntimeError(
                "Markdown widget not initialized. compose() must be called first."
            )
        return self._markdown

    def _ensure_stream(self) -> MarkdownStream | None:
        """Get or create the markdown stream. Returns None if streaming has failed."""
        if self._stream_failed:
            return None
        if self._stream is None:
            try:
                self._stream = Markdown.get_stream(self._get_markdown())
            except Exception as e:
                logger.warning(f"Failed to create markdown stream: {e}")
                persistent_log_error("Failed to create markdown stream", error=e)
                self._stream_failed = True
                return None
        return self._stream

    async def _fallback_update(self) -> None:
        """Fallback to direct markdown update when streaming fails."""
        try:
            markdown = self._get_markdown()
            await markdown.update(self._content)
        except Exception as e:
            logger.error(f"Fallback markdown update also failed: {e}")

    async def append_content(self, content: str) -> None:
        if not content:
            return

        self._content += content
        if not self._should_write_content():
            return

        # If streaming has failed, use fallback
        if self._stream_failed:
            await self._fallback_update()
            return

        # Accumulate content for debounced writing
        self._pending_write += content

        # Check if enough time has passed since last write
        current_time = time.monotonic() * 1000  # Convert to ms
        time_since_last = current_time - self._last_write_time

        if time_since_last >= MIN_WRITE_INTERVAL_MS:
            await self._flush_pending_write()

    async def _flush_pending_write(self) -> None:
        """Flush any pending content to the stream."""
        if not self._pending_write:
            return

        # If streaming has failed, use fallback
        if self._stream_failed:
            await self._fallback_update()
            self._pending_write = ""
            return

        stream = self._ensure_stream()
        if stream is None:
            # Stream creation failed, fallback
            await self._fallback_update()
            self._pending_write = ""
            return

        try:
            await stream.write(self._pending_write)
            self._pending_write = ""
            self._last_write_time = time.monotonic() * 1000
        except Exception as e:
            logger.warning(f"Stream write failed, falling back to direct update: {e}")
            persistent_log_error("Markdown stream write failed", error=e)
            self._stream_failed = True
            self._stream = None
            await self._fallback_update()
            self._pending_write = ""

    async def write_initial_content(self) -> None:
        if self._content and self._should_write_content():
            if self._stream_failed:
                await self._fallback_update()
                return

            stream = self._ensure_stream()
            if stream is None:
                await self._fallback_update()
                return

            try:
                await stream.write(self._content)
                self._last_write_time = time.monotonic() * 1000
            except Exception as e:
                logger.warning(f"Initial stream write failed: {e}")
                self._stream_failed = True
                self._stream = None
                await self._fallback_update()

    async def stop_stream(self) -> None:
        # Flush any remaining pending content before stopping
        await self._flush_pending_write()

        if self._stream is None:
            return

        try:
            await self._stream.stop()
        except Exception as e:
            logger.warning(f"Error stopping stream: {e}")
        finally:
            self._stream = None

    def _should_write_content(self) -> bool:
        return True


class AssistantMessage(StreamingMessageBase):
    """Assistant message with automatic code block truncation and debounced rendering."""

    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.add_class("assistant-message")
        self._code_block_buffer: str = ""  # Buffer for incomplete code blocks

    def compose(self) -> ComposeResult:
        with Horizontal(classes="assistant-message-container"):
            yield NonSelectableStatic("● ", classes="assistant-message-dot")
            with Vertical(classes="assistant-message-content"):
                markdown = Markdown("")
                self._markdown = markdown
                yield markdown

    async def append_content(self, content: str) -> None:
        """Append content with code block truncation and debounced rendering."""
        if not content:
            return

        self._content += content
        self._code_block_buffer += content

        if not self._should_write_content():
            return

        # If streaming has failed, use fallback from base class
        if self._stream_failed:
            await self._fallback_update()
            self._code_block_buffer = ""
            return

        try:
            # Check if we have any complete code blocks to process
            if "```" in self._code_block_buffer:
                parts = self._code_block_buffer.split("```")
                # If odd number of parts, we have complete blocks
                if len(parts) % 2 == 1 and len(parts) > 1:
                    # We have complete code blocks - truncate and queue for debounced write
                    truncated = truncate_code_blocks(self._code_block_buffer)
                    self._pending_write += truncated
                    self._code_block_buffer = ""

                    # Check debounce timing
                    current_time = time.monotonic() * 1000
                    if current_time - self._last_write_time >= MIN_WRITE_INTERVAL_MS:
                        await self._flush_pending_write()
                    return

            # No complete code blocks yet - check if we're inside one
            code_markers = self._code_block_buffer.count("```")
            if code_markers % 2 == 0:
                # Not inside a code block, queue for debounced write
                self._pending_write += self._code_block_buffer
                self._code_block_buffer = ""

                # Check debounce timing
                current_time = time.monotonic() * 1000
                if current_time - self._last_write_time >= MIN_WRITE_INTERVAL_MS:
                    await self._flush_pending_write()
        except Exception as e:
            logger.warning(f"Error in AssistantMessage append_content: {e}")
            self._stream_failed = True
            await self._fallback_update()
            self._code_block_buffer = ""

    async def stop_stream(self) -> None:
        """Stop stream and flush any pending content with truncation."""
        # Flush any remaining code block buffer
        if self._code_block_buffer and self._should_write_content():
            truncated = truncate_code_blocks(self._code_block_buffer)
            self._pending_write += truncated
            self._code_block_buffer = ""

        await super().stop_stream()


class ReasoningMessage(SpinnerMixin, StreamingMessageBase):
    SPINNER_TYPE = SpinnerType.LINE
    SPINNING_TEXT = "Thinking"
    COMPLETED_TEXT = "Thought"

    def __init__(self, content: str, collapsed: bool = True) -> None:
        super().__init__(content)
        self.add_class("reasoning-message")
        self.collapsed = collapsed
        self._indicator_widget: Static | None = None
        self._triangle_widget: Static | None = None
        self.init_spinner()

    def compose(self) -> ComposeResult:
        with Vertical(classes="reasoning-message-wrapper"):
            with Horizontal(classes="reasoning-message-header"):
                self._indicator_widget = NonSelectableStatic(
                    self._spinner.current_frame(), classes="reasoning-indicator"
                )
                yield self._indicator_widget
                self._status_text_widget = Static(
                    self.SPINNING_TEXT, markup=False, classes="reasoning-collapsed-text"
                )
                yield self._status_text_widget
                self._triangle_widget = NonSelectableStatic(
                    "▶" if self.collapsed else "▼", classes="reasoning-triangle"
                )
                yield self._triangle_widget
            markdown = Markdown("", classes="reasoning-message-content")
            markdown.display = not self.collapsed
            self._markdown = markdown
            yield markdown

    def on_mount(self) -> None:
        self.start_spinner_timer()

    def on_resize(self) -> None:
        self.refresh_spinner()

    async def on_click(self) -> None:
        await self._toggle_collapsed()

    async def _toggle_collapsed(self) -> None:
        await self.set_collapsed(not self.collapsed)

    def _should_write_content(self) -> bool:
        return not self.collapsed

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return

        self.collapsed = collapsed
        if self._triangle_widget:
            self._triangle_widget.update("▶" if collapsed else "▼")
        if self._markdown:
            self._markdown.display = not collapsed
            if not collapsed and self._content:
                try:
                    if self._stream is not None:
                        try:
                            await self._stream.stop()
                        except Exception as e:
                            logger.warning(f"Error stopping stream during collapse toggle: {e}")
                        finally:
                            self._stream = None
                    await self._markdown.update("")
                    stream = self._ensure_stream()
                    if stream is None:
                        # Streaming failed, use fallback
                        await self._fallback_update()
                    else:
                        await stream.write(self._content)
                except Exception as e:
                    logger.warning(f"Error expanding reasoning message: {e}")
                    self._stream_failed = True
                    await self._fallback_update()


class UserCommandMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.add_class("user-command-message")
        self._content = content

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-command-container"):
            yield ExpandingBorder(classes="user-command-border")
            with Vertical(classes="user-command-content"):
                yield Markdown(self._content)


class InterruptMessage(Static):
    def __init__(self) -> None:
        super().__init__()
        self.add_class("interrupt-message")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="interrupt-container"):
            yield ExpandingBorder(classes="interrupt-border")
            yield Static(
                "Interrupted · What should Vibe do instead?",
                markup=False,
                classes="interrupt-content",
            )


class BashOutputMessage(Static):
    def __init__(self, command: str, cwd: str, output: str, exit_code: int) -> None:
        super().__init__()
        self.add_class("bash-output-message")
        self._command = command
        self._cwd = cwd
        self._output = output
        self._exit_code = exit_code

    def compose(self) -> ComposeResult:
        with Vertical(classes="bash-output-container"):
            with Horizontal(classes="bash-cwd-line"):
                yield Static(self._cwd, markup=False, classes="bash-cwd")
                yield Static("", classes="bash-cwd-spacer")
                if self._exit_code == 0:
                    yield Static("✓", classes="bash-exit-success")
                else:
                    yield Static("✗", classes="bash-exit-failure")
                    yield Static(f" ({self._exit_code})", classes="bash-exit-code")
            with Horizontal(classes="bash-command-line"):
                yield Static("> ", classes="bash-chevron")
                yield Static(self._command, markup=False, classes="bash-command")
                yield Static("", classes="bash-command-spacer")
            yield Static(self._output, markup=False, classes="bash-output")


class ErrorMessage(Static):
    def __init__(self, error: str, collapsed: bool = True) -> None:
        super().__init__()
        self.add_class("error-message")
        self._error = error
        self.collapsed = collapsed
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="error-container"):
            yield ExpandingBorder(classes="error-border")
            self._content_widget = Static(
                self._get_text(), markup=False, classes="error-content"
            )
            yield self._content_widget

    def _get_text(self) -> str:
        if self.collapsed:
            return "Error. (ctrl+o to expand)"
        return f"Error: {self._error}"

    def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return

        self.collapsed = collapsed
        if self._content_widget:
            self._content_widget.update(self._get_text())


class WarningMessage(Static):
    def __init__(self, message: str, show_border: bool = True) -> None:
        super().__init__()
        self.add_class("warning-message")
        self._message = message
        self._show_border = show_border

    def compose(self) -> ComposeResult:
        with Horizontal(classes="warning-container"):
            if self._show_border:
                yield ExpandingBorder(classes="warning-border")
            yield Static(self._message, markup=False, classes="warning-content")


class ErrorBanner(Static):
    """A dismissible error notification banner displayed at the top of the UI.

    Supports auto-dismissal after a timeout and manual dismissal.
    Errors are color-coded by severity (error, warning, info).
    """

    # Default auto-dismiss timeout in seconds (0 = no auto-dismiss)
    DEFAULT_TIMEOUT = 10.0

    def __init__(self, id: str = "error-banner") -> None:
        super().__init__(id=id)
        self.add_class("error-banner")
        self._message: str = ""
        self._severity: str = "error"  # error, warning, info
        self._dismiss_timer: asyncio.TimerHandle | None = None
        self._content_widget: Static | None = None
        self._icon_widget: Static | None = None
        # Start hidden
        self.display = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="error-banner-container"):
            self._icon_widget = NonSelectableStatic("✗", classes="error-banner-icon")
            yield self._icon_widget
            self._content_widget = Static("", markup=False, classes="error-banner-content")
            yield self._content_widget
            yield NonSelectableStatic("(esc to dismiss)", classes="error-banner-dismiss-hint")

    def _get_icon(self) -> str:
        """Get icon based on severity."""
        if self._severity == "warning":
            return "⚠"
        elif self._severity == "info":
            return "ℹ"
        return "✗"

    def _update_classes(self) -> None:
        """Update CSS classes based on severity."""
        self.remove_class("severity-error", "severity-warning", "severity-info")
        self.add_class(f"severity-{self._severity}")

    async def show_error(
        self,
        message: str,
        severity: str = "error",
        timeout: float | None = None
    ) -> None:
        """Show an error message in the banner.

        Args:
            message: The error message to display
            severity: One of 'error', 'warning', 'info'
            timeout: Auto-dismiss timeout in seconds (None = use default, 0 = no auto-dismiss)
        """
        self._message = message
        self._severity = severity

        # Update content
        if self._content_widget:
            self._content_widget.update(message)
        if self._icon_widget:
            self._icon_widget.update(self._get_icon())

        self._update_classes()

        # Cancel any existing dismiss timer
        if self._dismiss_timer:
            self._dismiss_timer.cancel()
            self._dismiss_timer = None

        # Show the banner
        self.display = True

        # Set up auto-dismiss if timeout is specified
        effective_timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        if effective_timeout > 0:
            loop = asyncio.get_event_loop()
            self._dismiss_timer = loop.call_later(
                effective_timeout,
                lambda: asyncio.create_task(self.dismiss())
            )

    async def dismiss(self) -> None:
        """Dismiss/hide the error banner."""
        if self._dismiss_timer:
            self._dismiss_timer.cancel()
            self._dismiss_timer = None
        self.display = False
        self._message = ""

    def is_visible(self) -> bool:
        """Check if the banner is currently visible."""
        return self.display

    async def on_click(self) -> None:
        """Allow clicking to dismiss the banner."""
        await self.dismiss()
