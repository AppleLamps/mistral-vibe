"""Diff tool for showing differences between files or git changes."""

from __future__ import annotations

import asyncio
import difflib
from enum import StrEnum, auto
from pathlib import Path
import shutil
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


class DiffMode(StrEnum):
    FILES = auto()  # Compare two files
    GIT = auto()  # Show git diff for a file or all changes
    GIT_STAGED = auto()  # Show only staged git changes


class DiffConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS

    context_lines: int = Field(
        default=3, description="Number of context lines around changes."
    )
    max_output_lines: int = Field(
        default=500, description="Maximum number of lines to return."
    )
    timeout: int = Field(
        default=30, description="Timeout for git commands in seconds."
    )


class DiffState(BaseToolState):
    pass


class DiffArgs(BaseModel):
    mode: DiffMode = Field(
        default=DiffMode.GIT,
        description="Diff mode: 'files' to compare two files, 'git' for uncommitted changes, 'git_staged' for staged changes.",
    )
    path: str | None = Field(
        default=None,
        description="File path for git diff, or first file for file comparison.",
    )
    path2: str | None = Field(
        default=None,
        description="Second file path for file comparison (only used in 'files' mode).",
    )
    context_lines: int | None = Field(
        default=None,
        description="Override default number of context lines.",
    )


class DiffResult(BaseModel):
    diff: str
    additions: int
    deletions: int
    files_changed: int
    was_truncated: bool = False
    mode: str


class Diff(
    BaseTool[DiffArgs, DiffResult, DiffConfig, DiffState],
    ToolUIData[DiffArgs, DiffResult],
):
    description: ClassVar[str] = (
        "Show differences between files or git changes. "
        "Modes: 'files' compares two files, 'git' shows uncommitted changes, "
        "'git_staged' shows only staged changes. "
        "Useful for reviewing changes before committing or comparing file versions."
    )

    async def run(self, args: DiffArgs) -> DiffResult:
        if args.mode == DiffMode.FILES:
            return await self._diff_files(args)
        elif args.mode == DiffMode.GIT:
            return await self._diff_git(args, staged_only=False)
        elif args.mode == DiffMode.GIT_STAGED:
            return await self._diff_git(args, staged_only=True)
        else:
            raise ToolError(f"Unknown diff mode: {args.mode}")

    async def _diff_files(self, args: DiffArgs) -> DiffResult:
        """Compare two files using Python's difflib."""
        if not args.path:
            raise ToolError("path is required for file comparison")
        if not args.path2:
            raise ToolError("path2 is required for file comparison")

        path1 = self._resolve_path(args.path)
        path2 = self._resolve_path(args.path2)

        if not path1.is_file():
            raise ToolError(f"File not found: {args.path}")
        if not path2.is_file():
            raise ToolError(f"File not found: {args.path2}")

        try:
            content1 = path1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            content2 = path2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError as e:
            raise ToolError(f"Error reading files: {e}")

        context = args.context_lines if args.context_lines is not None else self.config.context_lines

        diff_lines = list(difflib.unified_diff(
            content1,
            content2,
            fromfile=str(path1),
            tofile=str(path2),
            n=context,
        ))

        return self._process_diff_output(diff_lines, DiffMode.FILES)

    async def _diff_git(self, args: DiffArgs, staged_only: bool) -> DiffResult:
        """Show git diff for a file or all changes."""
        if not shutil.which("git"):
            raise ToolError("Git is not installed or not in PATH")

        context = args.context_lines if args.context_lines is not None else self.config.context_lines

        cmd = ["git", "diff", f"-U{context}"]

        if staged_only:
            cmd.append("--staged")

        if args.path:
            path = self._resolve_path(args.path)
            if not path.exists():
                raise ToolError(f"Path not found: {args.path}")
            cmd.append("--")
            cmd.append(str(path))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.config.effective_workdir),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ToolError(f"Git diff timed out after {self.config.timeout}s")

            if proc.returncode != 0:
                stderr = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""
                # Check if not a git repo
                if "not a git repository" in stderr.lower():
                    raise ToolError("Not a git repository")
                raise ToolError(f"Git error: {stderr}")

            stdout = stdout_bytes.decode("utf-8", errors="ignore") if stdout_bytes else ""
            diff_lines = stdout.splitlines(keepends=True)

            mode = DiffMode.GIT_STAGED if staged_only else DiffMode.GIT
            return self._process_diff_output(diff_lines, mode)

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Error running git diff: {e}")

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path relative to the working directory."""
        path = Path(path_str).expanduser()
        if not path.is_absolute():
            path = self.config.effective_workdir / path
        return path

    def _process_diff_output(
        self, diff_lines: list[str], mode: DiffMode
    ) -> DiffResult:
        """Process diff output and calculate statistics."""
        additions = 0
        deletions = 0
        files_changed = 0
        was_truncated = False

        for line in diff_lines:
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
            elif line.startswith("diff ") or line.startswith("--- "):
                files_changed += 1

        # Handle file comparison (counts diff headers, not actual files)
        if mode == DiffMode.FILES:
            files_changed = 1 if diff_lines else 0

        # Truncate if needed
        if len(diff_lines) > self.config.max_output_lines:
            diff_lines = diff_lines[: self.config.max_output_lines]
            diff_lines.append("\n... (output truncated)\n")
            was_truncated = True

        diff_output = "".join(diff_lines)
        if not diff_output.strip():
            diff_output = "(no differences)"

        return DiffResult(
            diff=diff_output,
            additions=additions,
            deletions=deletions,
            files_changed=files_changed,
            was_truncated=was_truncated,
            mode=mode.value,
        )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, DiffArgs):
            return ToolCallDisplay(summary="diff")

        args = event.args

        if args.mode == DiffMode.FILES:
            summary = f"diff: {args.path} vs {args.path2}"
        elif args.mode == DiffMode.GIT_STAGED:
            if args.path:
                summary = f"git diff --staged: {args.path}"
            else:
                summary = "git diff --staged (all files)"
        else:
            if args.path:
                summary = f"git diff: {args.path}"
            else:
                summary = "git diff (all changes)"

        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, DiffResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result

        if result.diff == "(no differences)":
            message = "No differences found"
        else:
            message = f"+{result.additions} -{result.deletions}"
            if result.files_changed > 0:
                message += f" ({result.files_changed} file{'s' if result.files_changed > 1 else ''})"

        warnings = []
        if result.was_truncated:
            warnings.append("Output was truncated due to size limit")

        # Show diff preview
        details = result.diff if result.diff != "(no differences)" else None

        return ToolResultDisplay(
            success=True,
            message=message,
            details=details,
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Computing diff"
