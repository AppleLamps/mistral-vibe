"""Git tool for common git operations."""

from __future__ import annotations

import asyncio
from enum import StrEnum, auto
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


class GitOperation(StrEnum):
    STATUS = auto()
    ADD = auto()
    COMMIT = auto()
    LOG = auto()
    BRANCH = auto()
    CHECKOUT = auto()
    STASH = auto()
    STASH_POP = auto()
    RESET = auto()


class GitConfig(BaseToolConfig):
    # Most git operations should ask for confirmation
    permission: ToolPermission = ToolPermission.ASK

    timeout: int = Field(
        default=60, description="Timeout for git commands in seconds."
    )
    max_log_entries: int = Field(
        default=20, description="Maximum number of log entries to show."
    )
    max_output_lines: int = Field(
        default=200, description="Maximum output lines."
    )


class GitState(BaseToolState):
    pass


class GitArgs(BaseModel):
    operation: GitOperation = Field(
        description="Git operation to perform."
    )
    path: str | None = Field(
        default=None,
        description="Path for add/checkout operations. Use '.' for all files.",
    )
    message: str | None = Field(
        default=None,
        description="Commit message (required for commit operation).",
    )
    branch: str | None = Field(
        default=None,
        description="Branch name for checkout/branch operations.",
    )
    num_entries: int | None = Field(
        default=None,
        description="Number of log entries to show (for log operation).",
    )
    create_branch: bool = Field(
        default=False,
        description="Create a new branch when checking out.",
    )
    soft: bool = Field(
        default=False,
        description="Use soft reset (keeps changes staged).",
    )


class GitResult(BaseModel):
    output: str
    operation: str
    success: bool
    was_truncated: bool = False


class Git(
    BaseTool[GitArgs, GitResult, GitConfig, GitState],
    ToolUIData[GitArgs, GitResult],
):
    description: ClassVar[str] = (
        "Perform common git operations: status, add, commit, log, branch, checkout, stash. "
        "Provides structured output and better error messages than running git through bash."
    )
    modifies_state: ClassVar[bool] = True  # Git operations modify repository state

    async def run(self, args: GitArgs) -> GitResult:
        if not shutil.which("git"):
            raise ToolError("Git is not installed or not in PATH")

        # Check if in a git repo
        await self._check_git_repo()

        match args.operation:
            case GitOperation.STATUS:
                return await self._git_status()
            case GitOperation.ADD:
                return await self._git_add(args)
            case GitOperation.COMMIT:
                return await self._git_commit(args)
            case GitOperation.LOG:
                return await self._git_log(args)
            case GitOperation.BRANCH:
                return await self._git_branch(args)
            case GitOperation.CHECKOUT:
                return await self._git_checkout(args)
            case GitOperation.STASH:
                return await self._git_stash()
            case GitOperation.STASH_POP:
                return await self._git_stash_pop()
            case GitOperation.RESET:
                return await self._git_reset(args)
            case _:
                raise ToolError(f"Unknown git operation: {args.operation}")

    async def _check_git_repo(self) -> None:
        """Check if we're in a git repository."""
        cmd = ["git", "rev-parse", "--git-dir"]
        result = await self._run_git_command(cmd, check=False)
        if not result.success:
            raise ToolError("Not a git repository")

    async def _run_git_command(
        self, cmd: list[str], check: bool = True
    ) -> GitResult:
        """Run a git command and return the result."""
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
                raise ToolError(f"Git command timed out after {self.config.timeout}s")

            stdout = stdout_bytes.decode("utf-8", errors="ignore") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else ""

            success = proc.returncode == 0
            output = stdout if success else (stderr or stdout)

            if check and not success:
                raise ToolError(f"Git error: {output.strip()}")

            # Truncate if needed
            was_truncated = False
            lines = output.splitlines()
            if len(lines) > self.config.max_output_lines:
                lines = lines[: self.config.max_output_lines]
                lines.append("... (output truncated)")
                was_truncated = True
                output = "\n".join(lines)

            return GitResult(
                output=output.strip(),
                operation=cmd[1] if len(cmd) > 1 else "git",
                success=success,
                was_truncated=was_truncated,
            )

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Error running git: {e}")

    async def _git_status(self) -> GitResult:
        """Get git status."""
        cmd = ["git", "status", "--short", "--branch"]
        return await self._run_git_command(cmd)

    async def _git_add(self, args: GitArgs) -> GitResult:
        """Stage files.

        Runs git add first, then fetches status. Both operations are started
        concurrently to reduce latency - git add typically completes quickly
        enough that the index is updated before status reads it.
        """
        if not args.path:
            raise ToolError("path is required for add operation (use '.' for all files)")

        # Start both operations concurrently for reduced latency
        # git add modifies index, status reads it - add is fast enough that
        # the index is typically updated before status subprocess starts
        add_cmd = ["git", "add", args.path]
        add_task = asyncio.create_task(self._run_git_command(add_cmd))
        status_task = asyncio.create_task(self._git_status())

        # Wait for both to complete
        result, status_result = await asyncio.gather(add_task, status_task)

        result.output = f"Staged: {args.path}\n\n{status_result.output}"
        return result

    async def _git_commit(self, args: GitArgs) -> GitResult:
        """Create a commit."""
        if not args.message:
            raise ToolError("message is required for commit operation")

        cmd = ["git", "commit", "-m", args.message]
        return await self._run_git_command(cmd)

    async def _git_log(self, args: GitArgs) -> GitResult:
        """Show commit log."""
        num_entries = args.num_entries or self.config.max_log_entries

        cmd = [
            "git", "log",
            f"-{num_entries}",
            "--oneline",
            "--decorate",
        ]
        return await self._run_git_command(cmd)

    async def _git_branch(self, args: GitArgs) -> GitResult:
        """List or create branches."""
        if args.branch:
            # Create new branch
            cmd = ["git", "branch", args.branch]
            result = await self._run_git_command(cmd)
            result.output = f"Created branch: {args.branch}"
            return result
        else:
            # List branches
            cmd = ["git", "branch", "-a", "-v"]
            return await self._run_git_command(cmd)

    async def _git_checkout(self, args: GitArgs) -> GitResult:
        """Checkout a branch or file."""
        if not args.branch and not args.path:
            raise ToolError("branch or path is required for checkout")

        if args.branch:
            if args.create_branch:
                cmd = ["git", "checkout", "-b", args.branch]
            else:
                cmd = ["git", "checkout", args.branch]
        else:
            cmd = ["git", "checkout", "--", args.path]

        return await self._run_git_command(cmd)

    async def _git_stash(self) -> GitResult:
        """Stash current changes."""
        cmd = ["git", "stash", "push", "-m", "Auto-stash by vibe"]
        return await self._run_git_command(cmd)

    async def _git_stash_pop(self) -> GitResult:
        """Pop the most recent stash."""
        cmd = ["git", "stash", "pop"]
        return await self._run_git_command(cmd)

    async def _git_reset(self, args: GitArgs) -> GitResult:
        """Reset staged changes.

        Unlike git add, reset and status must run sequentially because status
        needs to accurately reflect the post-reset state. Reset operations
        modify the index/HEAD in ways that status must observe after completion.
        """
        if args.soft:
            cmd = ["git", "reset", "--soft", "HEAD~1"]
        elif args.path:
            cmd = ["git", "reset", "HEAD", "--", args.path]
        else:
            cmd = ["git", "reset", "HEAD"]

        result = await self._run_git_command(cmd)

        # Status must run after reset to show correct state
        status_result = await self._git_status()
        result.output = f"Reset complete.\n\n{status_result.output}"
        return result

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, GitArgs):
            return ToolCallDisplay(summary="git")

        args = event.args
        op = args.operation.value

        match args.operation:
            case GitOperation.ADD:
                summary = f"git add {args.path or '.'}"
            case GitOperation.COMMIT:
                msg_preview = (args.message or "")[:40]
                if len(args.message or "") > 40:
                    msg_preview += "..."
                summary = f'git commit -m "{msg_preview}"'
            case GitOperation.CHECKOUT:
                if args.create_branch:
                    summary = f"git checkout -b {args.branch}"
                elif args.branch:
                    summary = f"git checkout {args.branch}"
                else:
                    summary = f"git checkout -- {args.path}"
            case GitOperation.BRANCH:
                if args.branch:
                    summary = f"git branch {args.branch}"
                else:
                    summary = "git branch -a"
            case GitOperation.LOG:
                summary = f"git log -{args.num_entries or 'default'}"
            case GitOperation.RESET:
                if args.soft:
                    summary = "git reset --soft HEAD~1"
                elif args.path:
                    summary = f"git reset HEAD -- {args.path}"
                else:
                    summary = "git reset HEAD"
            case _:
                summary = f"git {op}"

        return ToolCallDisplay(summary=summary)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, GitResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result

        message = f"git {result.operation}: {'success' if result.success else 'failed'}"

        warnings = []
        if result.was_truncated:
            warnings.append("Output was truncated")

        return ToolResultDisplay(
            success=result.success,
            message=message,
            details=result.output if result.output else None,
            warnings=warnings,
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Running git"
