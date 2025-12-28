---
name: vibe-tool-creation
description: |
  Create custom tools for the vibe agent. Use when user wants to "add a tool", "create a tool",
  "extend vibe capabilities", or mentions "BaseTool", "ToolArgs", "ToolResult".
---

# Vibe Tool Creation

Guide for creating custom tools that integrate with the vibe agent system.

## Instructions

1. **Follow the BaseTool pattern**:
   ```python
   from __future__ import annotations

   from typing import ClassVar
   from pydantic import BaseModel, Field
   from vibe.core.tools.base import (
       BaseTool, BaseToolConfig, BaseToolState,
       ToolError, ToolPermission
   )

   class MyToolArgs(BaseModel):
       """Arguments for MyTool - shown to LLM."""
       query: str = Field(description="Search query to execute")
       limit: int = Field(default=10, ge=1, le=100)

   class MyToolResult(BaseModel):
       """Result from MyTool execution."""
       matches: list[str]
       count: int

   class MyToolConfig(BaseToolConfig):
       """Configuration for MyTool."""
       permission: ToolPermission = ToolPermission.ASK

   class MyTool(BaseTool[MyToolArgs, MyToolResult, MyToolConfig, None]):
       """Search for items matching query."""

       description: ClassVar[str] = (
           "Search through items and return matches. "
           "Use when user needs to find specific items."
       )

       async def run(self, args: MyToolArgs) -> MyToolResult:
           # Implementation
           matches = await self._search(args.query, args.limit)
           return MyToolResult(matches=matches, count=len(matches))
   ```

2. **Tool file locations**:
   - Project tools: `.vibe/tools/<name>.py`
   - Global tools: `~/.vibe/tools/<name>.py`
   - Builtin examples: `vibe/core/tools/builtins/`

3. **Add UI display (optional)**:
   ```python
   from vibe.core.tools.ui import (
       ToolCallDisplay, ToolResultDisplay, ToolUIData
   )

   class MyTool(
       BaseTool[MyToolArgs, MyToolResult, MyToolConfig, None],
       ToolUIData[MyToolArgs, MyToolResult]
   ):
       @classmethod
       def get_call_display(cls, event) -> ToolCallDisplay:
           return ToolCallDisplay(summary=f"search: {event.args.query}")

       @classmethod
       def get_result_display(cls, event) -> ToolResultDisplay:
           result = event.result
           return ToolResultDisplay(
               success=True,
               message=f"Found {result.count} matches"
           )
   ```

4. **Handle errors gracefully**:
   ```python
   async def run(self, args: MyToolArgs) -> MyToolResult:
       try:
           result = await external_api(args.query)
       except ConnectionError as e:
           raise ToolError(f"API unavailable: {e}") from e
       return MyToolResult(...)
   ```

5. **Use config for dangerous operations**:
   ```python
   class DangerousToolConfig(BaseToolConfig):
       permission: ToolPermission = ToolPermission.ASK  # Always ask
       denylist: list[str] = Field(default_factory=lambda: ["rm", "delete"])
   ```

## Reference Implementations

| Tool | Pattern | Path |
|------|---------|------|
| bash | Subprocess exec | `vibe/core/tools/builtins/bash.py` |
| grep | File search | `vibe/core/tools/builtins/grep.py` |
| read_file | File read | `vibe/core/tools/builtins/read_file.py` |
| search_replace | File edit | `vibe/core/tools/builtins/search_replace.py` |
| task | Subagent spawn | `vibe/core/tools/builtins/task.py` |

## Validation Commands

```bash
uv run python -m py_compile .vibe/tools/my_tool.py
uv run pyright .vibe/tools/my_tool.py
```

## Examples

- "Create a tool to fetch weather" → HTTP client tool
- "Add a database query tool" → Async DB tool
- "Make a file watcher tool" → Filesystem tool

## Guardrails

- All tool methods must be `async def`
- Provide clear `description` ClassVar for LLM
- Use `Field(description=...)` for all args
- Use ToolPermission.ASK for destructive operations
- Never hardcode secrets - use env vars or config
