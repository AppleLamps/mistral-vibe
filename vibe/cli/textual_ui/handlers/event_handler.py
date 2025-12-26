from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.widgets import Static

from vibe.cli.textual_ui.widgets.compact import CompactMessage
from vibe.cli.textual_ui.widgets.messages import AssistantMessage, ReasoningMessage
from vibe.cli.textual_ui.widgets.tools import ToolCallMessage, ToolResultMessage
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from vibe.core.utils import TaggedText

if TYPE_CHECKING:
    from vibe.cli.textual_ui.widgets.loading import LoadingWidget


class EventHandler:
    # Content patterns to detect for status updates
    CODE_BLOCK_PATTERN = "```"
    CODE_INDICATORS = ("def ", "class ", "function ", "const ", "import ", "from ")

    def __init__(
        self,
        mount_callback: Callable,
        scroll_callback: Callable,
        todo_area_callback: Callable,
        get_tools_collapsed: Callable[[], bool],
        get_todos_collapsed: Callable[[], bool],
    ) -> None:
        self.mount_callback = mount_callback
        self.scroll_callback = scroll_callback
        self.todo_area_callback = todo_area_callback
        self.get_tools_collapsed = get_tools_collapsed
        self.get_todos_collapsed = get_todos_collapsed
        self.current_tool_call: ToolCallMessage | None = None
        self.current_compact: CompactMessage | None = None
        self._accumulated_content: str = ""
        self._last_status: str | None = None

    async def handle_event(
        self,
        event: BaseEvent,
        loading_active: bool = False,
        loading_widget: LoadingWidget | None = None,
    ) -> ToolCallMessage | None:
        match event:
            case ToolCallEvent():
                # Reset accumulated content when a new tool is called
                self._accumulated_content = ""
                self._last_status = None
                return await self._handle_tool_call(event, loading_widget)
            case ToolResultEvent():
                sanitized_event = self._sanitize_event(event)
                await self._handle_tool_result(sanitized_event)
            case ReasoningEvent():
                await self._handle_reasoning_message(event, loading_widget)
            case AssistantEvent():
                await self._handle_assistant_message(event, loading_widget)
            case CompactStartEvent():
                await self._handle_compact_start()
            case CompactEndEvent():
                await self._handle_compact_end(event)
            case _:
                await self._handle_unknown_event(event)
        return None

    def _sanitize_event(self, event: ToolResultEvent) -> ToolResultEvent:
        if isinstance(event, ToolResultEvent):
            return ToolResultEvent(
                tool_name=event.tool_name,
                tool_class=event.tool_class,
                result=event.result,
                error=TaggedText.from_string(event.error).message
                if event.error
                else None,
                skipped=event.skipped,
                skip_reason=TaggedText.from_string(event.skip_reason).message
                if event.skip_reason
                else None,
                duration=event.duration,
                tool_call_id=event.tool_call_id,
            )
        return event

    async def _handle_tool_call(
        self, event: ToolCallEvent, loading_widget: LoadingWidget | None = None
    ) -> ToolCallMessage | None:
        tool_call = ToolCallMessage(event)

        if loading_widget and event.tool_class:
            from vibe.core.tools.ui import ToolUIDataAdapter

            adapter = ToolUIDataAdapter(event.tool_class)
            status_text = adapter.get_status_text()
            loading_widget.set_status(status_text)

        # Don't show todo in messages
        if event.tool_name != "todo":
            await self.mount_callback(tool_call)

        self.current_tool_call = tool_call
        return tool_call

    async def _handle_tool_result(self, event: ToolResultEvent) -> None:
        if event.tool_name == "todo":
            todos_collapsed = self.get_todos_collapsed()
            tool_result = ToolResultMessage(
                event, self.current_tool_call, collapsed=todos_collapsed
            )
            # Show in todo area
            todo_area = self.todo_area_callback()
            await todo_area.remove_children()
            await todo_area.mount(tool_result)
        else:
            tools_collapsed = self.get_tools_collapsed()
            tool_result = ToolResultMessage(
                event, self.current_tool_call, collapsed=tools_collapsed
            )
            await self.mount_callback(tool_result)

        self.current_tool_call = None

    def _detect_content_status(self, content: str) -> str | None:
        """Detect content type and return appropriate status text."""
        # Check for code blocks
        if self.CODE_BLOCK_PATTERN in content:
            return "Writing code"

        # Check for code-like content
        for indicator in self.CODE_INDICATORS:
            if indicator in content:
                return "Generating code"

        # Check for planning indicators
        planning_indicators = ("Step ", "1.", "First,", "Plan:", "approach")
        for indicator in planning_indicators:
            if indicator in content:
                return "Planning"

        return None

    def _update_loading_status(
        self, loading_widget: LoadingWidget | None, content: str
    ) -> None:
        """Update loading widget status based on accumulated content."""
        if not loading_widget:
            return

        self._accumulated_content += content

        # Only check periodically to avoid too many updates
        if len(self._accumulated_content) % 50 != 0:
            return

        new_status = self._detect_content_status(self._accumulated_content)
        if new_status and new_status != self._last_status:
            self._last_status = new_status
            loading_widget.set_status(new_status)

    async def _handle_assistant_message(
        self, event: AssistantEvent, loading_widget: LoadingWidget | None = None
    ) -> None:
        self._update_loading_status(loading_widget, event.content)
        await self.mount_callback(AssistantMessage(event.content))

    async def _handle_reasoning_message(
        self, event: ReasoningEvent, loading_widget: LoadingWidget | None = None
    ) -> None:
        if loading_widget and self._last_status != "Thinking":
            loading_widget.set_status("Thinking")
            self._last_status = "Thinking"
        tools_collapsed = self.get_tools_collapsed()
        await self.mount_callback(
            ReasoningMessage(event.content, collapsed=tools_collapsed)
        )

    async def _handle_compact_start(self) -> None:
        compact_msg = CompactMessage()
        self.current_compact = compact_msg
        await self.mount_callback(compact_msg)

    async def _handle_compact_end(self, event: CompactEndEvent) -> None:
        if self.current_compact:
            self.current_compact.set_complete(
                old_tokens=event.old_context_tokens, new_tokens=event.new_context_tokens
            )
            self.current_compact = None

    async def _handle_unknown_event(self, event: BaseEvent) -> None:
        await self.mount_callback(
            Static(str(event), markup=False, classes="unknown-event")
        )

    def stop_current_tool_call(self) -> None:
        if self.current_tool_call:
            self.current_tool_call.stop_spinning()
            self.current_tool_call = None

    def stop_current_compact(self) -> None:
        if self.current_compact:
            self.current_compact.stop_spinning(success=False)
            self.current_compact = None

    def reset_content_tracking(self) -> None:
        """Reset accumulated content and status tracking."""
        self._accumulated_content = ""
        self._last_status = None
