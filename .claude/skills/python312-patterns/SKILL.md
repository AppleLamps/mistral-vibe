---
name: python312-patterns
description: |
  Modern Python 3.12+ coding patterns for this project. Use when writing new Python code,
  refactoring existing code, or when user mentions "modern Python", "type hints", "match-case",
  "walrus operator", or asks about Python best practices.
allowed-tools: Read, Grep, Glob
---

# Python 3.12+ Patterns

Apply modern Python 3.12+ idioms consistently throughout this codebase.

## Instructions

1. **Always start files with future annotations**:
   ```python
   from __future__ import annotations
   ```

2. **Use modern type hints** (never deprecated typing module):
   ```python
   # Correct
   def process(items: list[str]) -> dict[str, int]: ...
   def get_value() -> str | None: ...

   # Wrong - do not use
   from typing import List, Dict, Optional, Union
   ```

3. **Prefer match-case over if/elif chains**:
   ```python
   match event.type:
       case "click":
           handle_click(event)
       case "hover":
           handle_hover(event)
       case _:
           log_unknown(event)
   ```

4. **Use walrus operator when it improves clarity**:
   ```python
   if (result := expensive_call()) is not None:
       process(result)
   ```

5. **Follow "never nester" principle** - use early returns:
   ```python
   def process(data: Data | None) -> Result:
       if data is None:
           return Result.empty()
       if not data.is_valid:
           return Result.invalid()
       # Main logic at minimal nesting
       return Result.from_data(data)
   ```

6. **Use pathlib.Path over os.path**:
   ```python
   from pathlib import Path

   config_file = Path.home() / ".config" / "app.toml"
   if config_file.exists():
       content = config_file.read_text()
   ```

7. **Use StrEnum with auto() for string enums**:
   ```python
   from enum import StrEnum, auto

   class Status(StrEnum):
       PENDING = auto()
       ACTIVE = auto()
       DONE = auto()
   ```

8. **No inline ignores** - fix types at the source:
   ```python
   # Wrong
   result = get_data()  # type: ignore[return-value]

   # Correct - use isinstance guard or typing.cast
   result = get_data()
   if isinstance(result, ExpectedType):
       process(result)
   ```

## Commands

Run type checker: `uv run pyright`
Run linter: `uv run ruff check vibe/ tests/`

## Examples

- "Write a function to parse config" → Apply all patterns above
- "Refactor this if/elif chain" → Convert to match-case
- "Fix the type errors" → Use modern hints, add guards

## Guardrails

- Read-only analysis unless user confirms writes
- Never use bare `python` or `pip` - always `uv run`
- Reference AGENTS.md for project-specific conventions
