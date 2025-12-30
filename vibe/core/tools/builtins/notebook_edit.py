from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, final

import aiofiles
from pydantic import BaseModel, Field

from vibe.core.path_security import PathSecurityError, validate_safe_path
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


CellType = Literal["code", "markdown", "raw"]
EditMode = Literal["replace", "insert", "delete"]


class NotebookEditArgs(BaseModel):
    path: str = Field(description="Path to the Jupyter notebook (.ipynb file).")
    cell_index: int = Field(
        description="Index of the cell to edit (0-based). For 'insert', this is the position to insert at.",
    )
    mode: EditMode = Field(
        default="replace",
        description="Edit mode: 'replace' to update cell content, 'insert' to add a new cell, 'delete' to remove a cell.",
    )
    cell_type: CellType | None = Field(
        default=None,
        description="Cell type (code, markdown, raw). Required for 'insert', optional for 'replace'.",
    )
    source: str | None = Field(
        default=None,
        description="New cell content. Required for 'replace' and 'insert' modes.",
    )


class NotebookEditResult(BaseModel):
    path: str
    mode: str
    cell_index: int
    cell_type: str
    total_cells: int
    source_preview: str = Field(description="Preview of the cell content (first 200 chars).")


class NotebookEditConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    create_backup: bool = Field(
        default=True,
        description="Create a backup before editing.",
    )


class NotebookEditState(BaseToolState):
    edited_notebooks: list[str] = Field(default_factory=list)

    modifies_state: ClassVar[bool] = True


def _create_cell(cell_type: CellType, source: str) -> dict[str, Any]:
    """Create a new notebook cell structure."""
    cell: dict[str, Any] = {
        "cell_type": cell_type,
        "metadata": {},
        "source": source.split("\n") if source else [],
    }

    # Add execution count for code cells
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []

    return cell


def _get_cell_source(cell: dict[str, Any]) -> str:
    """Extract source from a cell, handling both list and string formats."""
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return source


class NotebookEdit(
    BaseTool[NotebookEditArgs, NotebookEditResult, NotebookEditConfig, NotebookEditState],
    ToolUIData[NotebookEditArgs, NotebookEditResult],
):
    description: ClassVar[str] = (
        "Edit Jupyter notebook (.ipynb) cells. Can replace cell content, insert new cells, "
        "or delete cells. Supports code, markdown, and raw cell types."
    )

    modifies_state: ClassVar[bool] = True

    @final
    async def run(self, args: NotebookEditArgs) -> NotebookEditResult:
        # Validate path
        if not args.path.strip():
            raise ToolError("Path cannot be empty")

        file_path = Path(args.path).expanduser()
        if not file_path.is_absolute():
            file_path = self.config.effective_workdir / file_path

        try:
            resolved_path = file_path.resolve()
        except ValueError:
            raise ToolError(f"Invalid file path: {file_path}")

        project_root = self.config.effective_workdir.resolve()
        try:
            validate_safe_path(resolved_path, project_root)
        except PathSecurityError as e:
            raise ToolError(str(e))

        # Check extension
        if resolved_path.suffix.lower() != ".ipynb":
            raise ToolError(f"Not a notebook file: {resolved_path.suffix}")

        # Validate mode-specific requirements
        if args.mode in ("replace", "insert") and args.source is None:
            raise ToolError(f"'source' is required for '{args.mode}' mode")

        if args.mode == "insert" and args.cell_type is None:
            raise ToolError("'cell_type' is required for 'insert' mode")

        # Read notebook
        if not resolved_path.exists():
            if args.mode == "insert" and args.cell_index == 0:
                # Create new notebook
                notebook = {
                    "cells": [],
                    "metadata": {
                        "kernelspec": {
                            "display_name": "Python 3",
                            "language": "python",
                            "name": "python3",
                        },
                        "language_info": {"name": "python", "version": "3.10.0"},
                    },
                    "nbformat": 4,
                    "nbformat_minor": 5,
                }
            else:
                raise ToolError(f"Notebook not found: {resolved_path}")
        else:
            try:
                async with aiofiles.open(resolved_path, encoding="utf-8") as f:
                    content = await f.read()
                notebook = json.loads(content)
            except json.JSONDecodeError as e:
                raise ToolError(f"Invalid notebook JSON: {e}")

        cells = notebook.get("cells", [])
        num_cells = len(cells)

        # Validate cell index
        if args.mode == "delete":
            if args.cell_index < 0 or args.cell_index >= num_cells:
                raise ToolError(
                    f"Cell index {args.cell_index} out of range (0-{num_cells - 1})"
                )
        elif args.mode == "replace":
            if args.cell_index < 0 or args.cell_index >= num_cells:
                raise ToolError(
                    f"Cell index {args.cell_index} out of range (0-{num_cells - 1})"
                )
        elif args.mode == "insert":
            if args.cell_index < 0 or args.cell_index > num_cells:
                raise ToolError(
                    f"Insert index {args.cell_index} out of range (0-{num_cells})"
                )

        # Create backup if configured
        if self.config.create_backup and resolved_path.exists():
            backup_path = resolved_path.with_suffix(".ipynb.backup")
            async with aiofiles.open(resolved_path, "rb") as src:
                async with aiofiles.open(backup_path, "wb") as dst:
                    await dst.write(await src.read())

        # Perform edit
        result_cell_type: str
        source_preview: str

        if args.mode == "delete":
            deleted_cell = cells.pop(args.cell_index)
            result_cell_type = deleted_cell.get("cell_type", "unknown")
            source_preview = _get_cell_source(deleted_cell)[:200]

        elif args.mode == "replace":
            cell = cells[args.cell_index]
            # Update cell type if specified
            if args.cell_type:
                cell["cell_type"] = args.cell_type
                # Add/remove code-specific fields
                if args.cell_type == "code":
                    cell.setdefault("execution_count", None)
                    cell.setdefault("outputs", [])
                else:
                    cell.pop("execution_count", None)
                    cell.pop("outputs", None)

            # Update source
            cell["source"] = args.source.split("\n") if args.source else []
            result_cell_type = cell["cell_type"]
            source_preview = (args.source or "")[:200]

        else:  # insert
            assert args.cell_type is not None
            assert args.source is not None
            new_cell = _create_cell(args.cell_type, args.source)
            cells.insert(args.cell_index, new_cell)
            result_cell_type = args.cell_type
            source_preview = args.source[:200]

        # Write notebook
        notebook["cells"] = cells
        async with aiofiles.open(resolved_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(notebook, indent=1, ensure_ascii=False))

        # Update state
        self.state.edited_notebooks.append(str(resolved_path))
        if len(self.state.edited_notebooks) > 10:
            self.state.edited_notebooks.pop(0)

        return NotebookEditResult(
            path=str(resolved_path),
            mode=args.mode,
            cell_index=args.cell_index,
            cell_type=result_cell_type,
            total_cells=len(cells),
            source_preview=source_preview,
        )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, NotebookEditArgs):
            return ToolCallDisplay(summary="notebook_edit")

        path = Path(event.args.path)
        mode = event.args.mode
        idx = event.args.cell_index

        return ToolCallDisplay(
            summary=f"notebook_edit: {mode} cell {idx} in {path.name}"
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, NotebookEditResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        mode_verbs = {"replace": "Updated", "insert": "Inserted", "delete": "Deleted"}
        verb = mode_verbs.get(result.mode, result.mode.capitalize())

        message = f"{verb} {result.cell_type} cell {result.cell_index} ({result.total_cells} cells total)"

        return ToolResultDisplay(success=True, message=message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Editing notebook"
