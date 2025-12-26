from __future__ import annotations

import difflib
from enum import StrEnum, auto
from pathlib import Path
from typing import ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins.code_intel import get_language_for_file, get_parser
from vibe.core.tools.builtins.code_intel.ast_utils import find_references
from vibe.core.tools.builtins.code_intel.languages import is_supported_file
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent


class RefactorOp(StrEnum):
    """Refactoring operations."""

    RENAME = auto()  # Rename a symbol across files
    PREVIEW = auto()  # Preview changes without applying


class RefactorArgs(BaseModel):
    """Arguments for refactoring."""

    operation: RefactorOp = Field(
        default=RefactorOp.PREVIEW,
        description="Operation: 'rename' to apply changes, 'preview' to see diff",
    )
    old_name: str = Field(description="Current symbol name")
    new_name: str = Field(description="New symbol name")
    scope: str = Field(
        default="project",
        description="Scope: 'project', 'file:<path>', or 'directory:<path>'",
    )


class Change(BaseModel):
    """A single text change."""

    line: int
    column: int
    old_text: str
    new_text: str


class FileChanges(BaseModel):
    """Changes for a single file."""

    file: str
    changes: list[Change]
    diff: str


class RefactorResult(BaseModel):
    """Result of refactoring operation."""

    operation: str
    old_name: str
    new_name: str
    files_modified: int
    total_changes: int
    file_changes: list[FileChanges]
    applied: bool = False


class RefactorConfig(BaseToolConfig):
    """Configuration for refactor tool."""

    permission: ToolPermission = ToolPermission.ASK  # Requires confirmation
    max_files: int = Field(
        default=100, description="Maximum files to modify in one operation"
    )
    backup_files: bool = Field(
        default=False, description="Create .bak backup before modifying"
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/.venv/**",
            "**/__pycache__/**",
        ],
        description="Patterns to exclude from refactoring",
    )


class RefactorState(BaseToolState):
    """State for refactor tool."""

    last_refactor: dict | None = None


class Refactor(
    BaseTool[RefactorArgs, RefactorResult, RefactorConfig, RefactorState],
    ToolUIData[RefactorArgs, RefactorResult],
):
    """Rename symbols across multiple files safely."""

    description: ClassVar[str] = (
        "Rename symbols (functions, classes, variables) across the codebase. "
        "Use operation='preview' to see changes first (recommended), "
        "then operation='rename' to apply. "
        "Supports Python, JavaScript, and TypeScript."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, RefactorArgs):
            return ToolCallDisplay(summary="refactor")

        args = event.args
        if args.operation == RefactorOp.PREVIEW:
            return ToolCallDisplay(
                summary=f"Preview: rename '{args.old_name}' → '{args.new_name}'",
            )
        return ToolCallDisplay(
            summary=f"Renaming '{args.old_name}' → '{args.new_name}'",
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, RefactorResult):
            return ToolResultDisplay(
                success=False, message=event.error or "Refactor failed"
            )

        result = event.result
        action = "Applied" if result.applied else "Preview"
        msg = f"{action}: {result.total_changes} change(s) in {result.files_modified} file(s)"

        return ToolResultDisplay(success=True, message=msg)

    @classmethod
    def get_status_text(cls) -> str:
        return "Refactoring code"

    @final
    async def run(self, args: RefactorArgs) -> RefactorResult:
        """Execute refactoring."""
        parser = get_parser()

        if not parser.is_available():
            raise ToolError(
                "tree-sitter is not available. "
                "Install tree-sitter and language modules to use refactoring."
            )

        # Validate names
        if not args.old_name or not args.old_name.strip():
            raise ToolError("old_name cannot be empty")
        if not args.new_name or not args.new_name.strip():
            raise ToolError("new_name cannot be empty")
        if args.old_name == args.new_name:
            raise ToolError("old_name and new_name are the same")

        # Collect files to search
        files = self._get_files(args.scope)

        if not files:
            return RefactorResult(
                operation=args.operation.value,
                old_name=args.old_name,
                new_name=args.new_name,
                files_modified=0,
                total_changes=0,
                file_changes=[],
                applied=False,
            )

        # Find all occurrences and compute changes
        file_changes = self._compute_changes(files, args.old_name, args.new_name, parser)

        # Apply changes if not preview
        applied = False
        if args.operation == RefactorOp.RENAME and file_changes:
            self._apply_changes(file_changes)
            applied = True

        # Store for potential undo
        self.state.last_refactor = {
            "old_name": args.old_name,
            "new_name": args.new_name,
            "file_changes": [fc.model_dump() for fc in file_changes],
        }

        return RefactorResult(
            operation=args.operation.value,
            old_name=args.old_name,
            new_name=args.new_name,
            files_modified=len(file_changes),
            total_changes=sum(len(fc.changes) for fc in file_changes),
            file_changes=file_changes,
            applied=applied,
        )

    def _get_files(self, scope: str) -> list[Path]:
        """Get files to search based on scope."""
        import fnmatch
        import os

        project_root = self.config.effective_workdir

        if scope.startswith("file:"):
            file_path = Path(scope[5:])
            if not file_path.is_absolute():
                file_path = project_root / file_path
            if file_path.exists() and is_supported_file(file_path):
                return [file_path]
            return []

        elif scope.startswith("directory:"):
            search_root = Path(scope[10:])
            if not search_root.is_absolute():
                search_root = project_root / search_root
        else:
            search_root = project_root

        if not search_root.exists():
            return []

        files = []
        for dirpath, dirnames, filenames in os.walk(search_root):
            # Filter excluded directories
            dirnames[:] = [
                d
                for d in dirnames
                if not any(
                    fnmatch.fnmatch(os.path.join(dirpath, d), pat)
                    for pat in self.config.exclude_patterns
                )
            ]

            for filename in filenames:
                file_path = Path(dirpath) / filename

                if not is_supported_file(file_path):
                    continue

                if any(
                    fnmatch.fnmatch(str(file_path), pat)
                    for pat in self.config.exclude_patterns
                ):
                    continue

                files.append(file_path)

                if len(files) >= self.config.max_files:
                    return files

        return files

    def _compute_changes(
        self,
        files: list[Path],
        old_name: str,
        new_name: str,
        parser: object,
    ) -> list[FileChanges]:
        """Compute all changes needed for the rename."""
        from vibe.core.tools.builtins.code_intel.parser import CodeParser

        if not isinstance(parser, CodeParser):
            return []

        all_changes: list[FileChanges] = []

        for file_path in files:
            tree = parser.parse_file(file_path)
            if tree is None:
                continue

            language = get_language_for_file(file_path)
            if language is None:
                continue

            try:
                source = file_path.read_bytes()
                source_text = source.decode("utf-8", errors="replace")
            except OSError:
                continue

            # Find all references
            refs = find_references(tree, language, source, old_name)

            if not refs:
                continue

            # Convert references to changes
            changes = []
            for ref in refs:
                changes.append(
                    Change(
                        line=ref["line"],
                        column=ref["column"],
                        old_text=old_name,
                        new_text=new_name,
                    )
                )

            # Generate diff
            new_source = self._apply_changes_to_text(source_text, changes)
            diff = self._generate_diff(
                source_text,
                new_source,
                str(file_path.relative_to(self.config.effective_workdir)),
            )

            all_changes.append(
                FileChanges(
                    file=str(file_path.relative_to(self.config.effective_workdir)),
                    changes=changes,
                    diff=diff,
                )
            )

        return all_changes

    def _apply_changes_to_text(self, text: str, changes: list[Change]) -> str:
        """Apply changes to text, handling overlapping edits."""
        lines = text.split("\n")

        # Group changes by line
        changes_by_line: dict[int, list[Change]] = {}
        for change in changes:
            line_num = change.line
            if line_num not in changes_by_line:
                changes_by_line[line_num] = []
            changes_by_line[line_num].append(change)

        # Apply changes line by line, sorted by column (reverse to preserve positions)
        for line_num, line_changes in changes_by_line.items():
            if line_num < 1 or line_num > len(lines):
                continue

            line_idx = line_num - 1
            line = lines[line_idx]

            # Sort by column descending so we can apply from right to left
            sorted_changes = sorted(line_changes, key=lambda c: c.column, reverse=True)

            for change in sorted_changes:
                col = change.column
                end_col = col + len(change.old_text)
                line = line[:col] + change.new_text + line[end_col:]

            lines[line_idx] = line

        return "\n".join(lines)

    def _generate_diff(self, old_text: str, new_text: str, filename: str) -> str:
        """Generate a unified diff between old and new text."""
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )

        return "".join(diff)

    def _apply_changes(self, file_changes: list[FileChanges]) -> None:
        """Apply changes to files."""
        import shutil

        project_root = self.config.effective_workdir

        for fc in file_changes:
            file_path = project_root / fc.file

            try:
                source_text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                raise ToolError(f"Failed to read {fc.file}: {e}") from e

            # Create backup if configured
            if self.config.backup_files:
                backup_path = file_path.with_suffix(file_path.suffix + ".bak")
                shutil.copy2(file_path, backup_path)

            # Apply changes
            new_text = self._apply_changes_to_text(source_text, fc.changes)

            try:
                file_path.write_text(new_text, encoding="utf-8")
            except OSError as e:
                raise ToolError(f"Failed to write {fc.file}: {e}") from e
