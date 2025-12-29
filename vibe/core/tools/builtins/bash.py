from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
from typing import ClassVar, Literal, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.utils import is_windows


def _get_subprocess_encoding() -> str:
    if sys.platform == "win32":
        # Windows console uses OEM code page (e.g., cp850, cp1252)
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    return "utf-8"


def _get_base_env() -> dict[str, str]:
    base_env = {
        **os.environ,
        "CI": "true",
        "NONINTERACTIVE": "1",
        "NO_TTY": "1",
        "NO_COLOR": "1",
    }

    if is_windows():
        base_env["GIT_PAGER"] = "more"
        base_env["PAGER"] = "more"
    else:
        base_env["TERM"] = "dumb"
        base_env["DEBIAN_FRONTEND"] = "noninteractive"
        base_env["GIT_PAGER"] = "cat"
        base_env["PAGER"] = "cat"
        base_env["LESS"] = "-FX"
        base_env["LC_ALL"] = "en_US.UTF-8"

    return base_env


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return

    try:
        if sys.platform == "win32":
            try:
                subprocess_proc = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(proc.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await subprocess_proc.wait()
            except (FileNotFoundError, OSError):
                proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

        await proc.wait()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _get_default_allowlist() -> list[str]:
    common = ["echo", "find", "git diff", "git log", "git status", "tree", "whoami"]

    if is_windows():
        return common + ["dir", "findstr", "more", "type", "ver", "where"]
    else:
        return common + [
            "cat",
            "file",
            "head",
            "ls",
            "pwd",
            "stat",
            "tail",
            "uname",
            "wc",
            "which",
        ]


def _get_default_denylist() -> list[str]:
    common = ["gdb", "pdb", "passwd"]

    if is_windows():
        return common + ["cmd /k", "powershell -NoExit", "pwsh -NoExit", "notepad"]
    else:
        return common + [
            "nano",
            "vim",
            "vi",
            "emacs",
            "bash -i",
            "sh -i",
            "zsh -i",
            "fish -i",
            "dash -i",
            "screen",
            "tmux",
        ]


def _get_default_denylist_standalone() -> list[str]:
    common = ["python", "python3", "ipython"]

    if is_windows():
        return common + ["cmd", "powershell", "pwsh", "notepad"]
    else:
        return common + ["bash", "sh", "nohup", "vi", "vim", "emacs", "nano", "su"]


class BashToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    max_output_bytes: int = Field(
        default=16_000, description="Maximum bytes to capture from stdout and stderr."
    )
    default_timeout: int = Field(
        default=30, description="Default timeout for commands in seconds."
    )
    allowlist: list[str] = Field(
        default_factory=_get_default_allowlist,
        description="Command prefixes that are automatically allowed",
    )
    denylist: list[str] = Field(
        default_factory=_get_default_denylist,
        description="Command prefixes that are automatically denied",
    )
    denylist_standalone: list[str] = Field(
        default_factory=_get_default_denylist_standalone,
        description="Commands that are denied only when run without arguments",
    )


class BashArgs(BaseModel):
    command: str
    timeout: int | None = Field(
        default=None, description="Override the default command timeout."
    )


class BashResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int
    correction_hint: str | None = None


class Bash(BaseTool[BashArgs, BashResult, BashToolConfig, BaseToolState]):
    description: ClassVar[str] = "Run a one-off bash command and capture its output."
    modifies_state: ClassVar[bool] = True  # Can modify files via shell commands

    def check_allowlist_denylist(self, args: BashArgs) -> ToolPermission | None:
        command_parts = re.split(r"(?:&&|\|\||;|\|)", args.command)
        command_parts = [part.strip() for part in command_parts if part.strip()]

        if not command_parts:
            return None

        def is_denylisted(command: str) -> bool:
            return any(command.startswith(pattern) for pattern in self.config.denylist)

        def is_standalone_denylisted(command: str) -> bool:
            parts = command.split()
            if not parts:
                return False

            base_command = parts[0]
            has_args = len(parts) > 1

            if not has_args:
                command_name = os.path.basename(base_command)
                if command_name in self.config.denylist_standalone:
                    return True
                if base_command in self.config.denylist_standalone:
                    return True

            return False

        def is_allowlisted(command: str) -> bool:
            return any(command.startswith(pattern) for pattern in self.config.allowlist)

        for part in command_parts:
            if is_denylisted(part):
                return ToolPermission.NEVER
            if is_standalone_denylisted(part):
                return ToolPermission.NEVER

        if all(is_allowlisted(part) for part in command_parts):
            return ToolPermission.ALWAYS

        return None

    @final
    def _build_timeout_error(self, command: str, timeout: int) -> ToolError:
        return ToolError(f"Command timed out after {timeout}s: {command!r}")

    @final
    def _generate_correction_hint(
        self, command: str, stderr: str, returncode: int
    ) -> str:
        """Generate helpful correction hints based on common error patterns."""
        hints: list[str] = []
        stderr_lower = stderr.lower()

        # Command not found errors
        if "command not found" in stderr_lower or "not recognized" in stderr_lower:
            hints.append("Check if the command is installed and in PATH")
            hints.append("Try using the full path to the executable")
            if is_windows():
                hints.append("Use 'where <command>' to check if it exists")
            else:
                hints.append("Use 'which <command>' to check if it exists")

        # Permission denied
        elif "permission denied" in stderr_lower:
            hints.append("Check file/directory permissions")
            if not is_windows():
                hints.append("You may need to use 'chmod' to change permissions")

        # File/directory not found
        elif "no such file or directory" in stderr_lower or "cannot find" in stderr_lower:
            hints.append("Verify the file/directory path exists")
            hints.append("Check for typos in the path")
            hints.append("Use 'ls' or 'dir' to list directory contents")

        # Git errors
        elif "not a git repository" in stderr_lower:
            hints.append("Ensure you're in a git repository directory")
            hints.append("Run 'git init' to initialize a new repository")

        # Python/pip errors
        elif "modulenotfounderror" in stderr_lower or "no module named" in stderr_lower:
            hints.append("Install the missing package with pip/uv")
            hints.append("Check if you're using the correct Python environment")

        # npm/node errors
        elif "enoent" in stderr_lower and "npm" in command.lower():
            hints.append("Run 'npm install' to install dependencies")
            hints.append("Check if package.json exists in the directory")

        # Connection errors
        elif "connection refused" in stderr_lower or "could not resolve host" in stderr_lower:
            hints.append("Check network connectivity")
            hints.append("Verify the host/port is correct and accessible")

        # Default hints based on return code
        if not hints:
            if returncode == 1:
                hints.append("General error - check command syntax")
            elif returncode == 2:
                hints.append("Misuse of shell command - verify arguments")
            elif returncode == 126:
                hints.append("Command not executable - check permissions")
            elif returncode == 127:
                hints.append("Command not found - verify it's installed")
            elif returncode == 128:
                hints.append("Invalid exit argument")
            elif returncode > 128:
                signal_num = returncode - 128
                hints.append(f"Command killed by signal {signal_num}")

        if hints:
            return "Correction suggestions:\n- " + "\n- ".join(hints)
        return ""

    @final
    def _build_result(
        self, *, command: str, stdout: str, stderr: str, returncode: int
    ) -> BashResult:
        if returncode != 0:
            correction_hint = self._generate_correction_hint(command, stderr, returncode)

            error_msg = f"Command failed: {command!r}\n"
            error_msg += f"Return code: {returncode}"
            if stderr:
                error_msg += f"\nStderr: {stderr}"
            if stdout:
                error_msg += f"\nStdout: {stdout}"
            if correction_hint:
                error_msg += f"\n\n{correction_hint}"
            raise ToolError(error_msg.strip())

        return BashResult(stdout=stdout, stderr=stderr, returncode=returncode)

    async def run(self, args: BashArgs) -> BashResult:
        timeout = args.timeout or self.config.default_timeout
        max_bytes = self.config.max_output_bytes

        proc = None
        try:
            # start_new_session is Unix-only, on Windows it's ignored
            kwargs: dict[Literal["start_new_session"], bool] = (
                {} if is_windows() else {"start_new_session": True}
            )

            proc = await asyncio.create_subprocess_shell(
                args.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=self.config.effective_workdir,
                env=_get_base_env(),
                **kwargs,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except TimeoutError:
                await _kill_process_tree(proc)
                raise self._build_timeout_error(args.command, timeout)

            encoding = _get_subprocess_encoding()
            stdout = (
                stdout_bytes.decode(encoding, errors="replace")[:max_bytes]
                if stdout_bytes
                else ""
            )
            stderr = (
                stderr_bytes.decode(encoding, errors="replace")[:max_bytes]
                if stderr_bytes
                else ""
            )

            returncode = proc.returncode or 0

            return self._build_result(
                command=args.command,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
            )

        except (ToolError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise ToolError(f"Error running command {args.command!r}: {exc}") from exc
        finally:
            if proc is not None:
                await _kill_process_tree(proc)
