"""ListDirectory tool for listing files and directories with metadata."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

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


class ListDirConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS

    max_entries: int = Field(
        default=500, description="Maximum number of entries to return."
    )
    max_depth: int = Field(
        default=3, description="Maximum directory depth for recursive listing."
    )
    exclude_patterns: list[str] = Field(
        default=[
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".pytest_cache",
            ".mypy_cache",
            ".tox",
            ".nox",
            "dist",
            "build",
            "*.egg-info",
        ],
        description="Patterns to exclude from listing.",
    )


class ListDirState(BaseToolState):
    pass


class ListDirArgs(BaseModel):
    path: str = Field(
        default=".",
        description="Path to list. Can be a directory or a glob pattern.",
    )
    recursive: bool = Field(
        default=False,
        description="If True, list directories recursively up to max_depth.",
    )
    include_hidden: bool = Field(
        default=False,
        description="If True, include hidden files (starting with .).",
    )
    show_size: bool = Field(
        default=True,
        description="If True, include file sizes in the output.",
    )
    max_depth: int | None = Field(
        default=None,
        description="Override the default max depth for recursive listing.",
    )


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified: str | None = None


class ListDirResult(BaseModel):
    entries: list[FileEntry]
    total_files: int
    total_dirs: int
    was_truncated: bool = False
    base_path: str


def _format_size(size: int) -> str:
    """Format size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f}{unit}" if unit != "B" else f"{size}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def _should_exclude(name: str, exclude_patterns: list[str]) -> bool:
    """Check if a name matches any exclusion pattern."""
    import fnmatch

    for pattern in exclude_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


class ListDir(
    BaseTool[ListDirArgs, ListDirResult, ListDirConfig, ListDirState],
    ToolUIData[ListDirArgs, ListDirResult],
):
    description: ClassVar[str] = (
        "List files and directories with metadata (size, modification date). "
        "Supports recursive listing, hidden files, and glob patterns. "
        "Use this instead of running 'ls' through bash for better structured output."
    )

    async def run(self, args: ListDirArgs) -> ListDirResult:
        base_path = Path(args.path).expanduser()
        if not base_path.is_absolute():
            base_path = self.config.effective_workdir / base_path

        if not base_path.exists():
            raise ToolError(f"Path does not exist: {args.path}")

        # Handle glob patterns
        if "*" in args.path or "?" in args.path:
            return await self._list_glob(args, base_path)

        if not base_path.is_dir():
            # Single file
            return self._single_file_result(base_path, args)

        return await self._list_directory(args, base_path)

    async def _list_glob(
        self, args: ListDirArgs, base_path: Path
    ) -> ListDirResult:
        """List files matching a glob pattern."""
        import glob

        pattern = str(base_path)
        if not base_path.is_absolute():
            pattern = str(self.config.effective_workdir / args.path)

        entries: list[FileEntry] = []
        total_files = 0
        total_dirs = 0
        was_truncated = False

        for match_path in glob.glob(pattern, recursive=args.recursive):
            if len(entries) >= self.config.max_entries:
                was_truncated = True
                break

            path_obj = Path(match_path)
            name = path_obj.name

            # Skip hidden files if not requested
            if not args.include_hidden and name.startswith("."):
                continue

            # Skip excluded patterns
            if _should_exclude(name, self.config.exclude_patterns):
                continue

            entry = self._create_entry(path_obj, args.show_size)
            entries.append(entry)

            if entry.is_dir:
                total_dirs += 1
            else:
                total_files += 1

        return ListDirResult(
            entries=entries,
            total_files=total_files,
            total_dirs=total_dirs,
            was_truncated=was_truncated,
            base_path=str(self.config.effective_workdir),
        )

    async def _list_directory(
        self, args: ListDirArgs, base_path: Path
    ) -> ListDirResult:
        """List contents of a directory."""
        max_depth = args.max_depth if args.max_depth is not None else self.config.max_depth

        entries: list[FileEntry] = []
        total_files = 0
        total_dirs = 0
        was_truncated = False

        def collect_entries(dir_path: Path, current_depth: int) -> bool:
            nonlocal total_files, total_dirs, was_truncated

            if current_depth > max_depth:
                return True

            try:
                items = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return True
            except OSError:
                return True

            for item in items:
                if len(entries) >= self.config.max_entries:
                    was_truncated = True
                    return False

                name = item.name

                # Skip hidden files if not requested
                if not args.include_hidden and name.startswith("."):
                    continue

                # Skip excluded patterns
                if _should_exclude(name, self.config.exclude_patterns):
                    continue

                entry = self._create_entry(item, args.show_size, base_path)
                entries.append(entry)

                if entry.is_dir:
                    total_dirs += 1
                    if args.recursive and current_depth < max_depth:
                        if not collect_entries(item, current_depth + 1):
                            return False
                else:
                    total_files += 1

            return True

        collect_entries(base_path, 0)

        return ListDirResult(
            entries=entries,
            total_files=total_files,
            total_dirs=total_dirs,
            was_truncated=was_truncated,
            base_path=str(base_path),
        )

    def _single_file_result(self, path: Path, args: ListDirArgs) -> ListDirResult:
        """Create result for a single file."""
        entry = self._create_entry(path, args.show_size)
        return ListDirResult(
            entries=[entry],
            total_files=1,
            total_dirs=0,
            was_truncated=False,
            base_path=str(path.parent),
        )

    def _create_entry(
        self, path: Path, show_size: bool, base_path: Path | None = None
    ) -> FileEntry:
        """Create a FileEntry from a path."""
        try:
            stat = path.stat()
            size = stat.st_size if not path.is_dir() else None
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except (OSError, PermissionError):
            size = None
            modified = None

        # Make path relative to base_path if provided
        display_path = str(path)
        if base_path:
            try:
                display_path = str(path.relative_to(base_path))
            except ValueError:
                pass

        return FileEntry(
            name=path.name,
            path=display_path,
            is_dir=path.is_dir(),
            size=size if show_size else None,
            modified=modified,
        )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, ListDirArgs):
            return ToolCallDisplay(summary="list_dir")

        summary = f"list_dir: {event.args.path}"
        if event.args.recursive:
            summary += " (recursive)"
        if event.args.include_hidden:
            summary += " [hidden]"

        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ListDirResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        message = f"{result.total_files} files, {result.total_dirs} directories"
        if result.was_truncated:
            message += " (truncated)"

        # Format entries for display
        lines = []
        for entry in result.entries[:20]:  # Show first 20 entries
            prefix = "d " if entry.is_dir else "f "
            size_str = ""
            if entry.size is not None:
                size_str = f" ({_format_size(entry.size)})"
            lines.append(f"{prefix}{entry.path}{size_str}")

        if len(result.entries) > 20:
            lines.append(f"... and {len(result.entries) - 20} more entries")

        details = "\n".join(lines) if lines else None

        warnings = []
        if result.was_truncated:
            warnings.append("Output was truncated due to entry limit")

        return ToolResultDisplay(
            success=True,
            message=message,
            details=details,
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Listing directory"
