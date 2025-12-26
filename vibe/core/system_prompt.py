from __future__ import annotations

import asyncio
from collections.abc import Generator
import fnmatch
from functools import lru_cache
import html
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from vibe.core.config import PROJECT_DOC_FILENAMES
from vibe.core.llm.format import get_active_tool_classes
from vibe.core.paths.config_paths import INSTRUCTIONS_FILE
from vibe.core.prompts import UtilityPrompt
from vibe.core.utils import is_dangerous_directory, is_windows

if TYPE_CHECKING:
    from vibe.core.config import ProjectContextConfig, VibeConfig
    from vibe.core.skills.manager import SkillManager
    from vibe.core.tools.manager import ToolManager


def _load_user_instructions() -> str:
    try:
        return INSTRUCTIONS_FILE.path.read_text("utf-8", errors="ignore")
    except (FileNotFoundError, OSError):
        return ""


def _load_project_doc(workdir: Path, max_bytes: int) -> str:
    for name in PROJECT_DOC_FILENAMES:
        path = workdir / name
        try:
            return path.read_text("utf-8", errors="ignore")[:max_bytes]
        except (FileNotFoundError, OSError):
            continue
    return ""


class ProjectContextProvider:
    def __init__(
        self, config: ProjectContextConfig, root_path: str | Path = "."
    ) -> None:
        self.root_path = Path(root_path).resolve()
        self.config = config
        self.gitignore_patterns = self._load_gitignore_patterns()
        self._compiled_patterns = self._compile_patterns()
        self._file_count = 0
        self._start_time = 0.0

    def _load_gitignore_patterns(self) -> list[str]:
        gitignore_path = self.root_path / ".gitignore"
        patterns = []

        if gitignore_path.exists():
            try:
                patterns.extend(
                    line.strip()
                    for line in gitignore_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")
                )
            except Exception as e:
                print(f"Warning: Could not read .gitignore: {e}", file=sys.stderr)

        default_patterns = [
            ".git",
            ".git/*",
            "*.pyc",
            "__pycache__",
            "node_modules",
            "node_modules/*",
            ".env",
            ".DS_Store",
            "*.log",
            ".vscode/settings.json",
            ".idea/*",
            "dist",
            "build",
            "target",
            ".next",
            ".nuxt",
            "coverage",
            ".nyc_output",
            "*.egg-info",
            ".pytest_cache",
            ".tox",
            "vendor",
            "third_party",
            "deps",
            "*.min.js",
            "*.min.css",
            "*.bundle.js",
            "*.chunk.js",
            ".cache",
            "tmp",
            "temp",
            "logs",
        ]

        return patterns + default_patterns

    def _compile_patterns(self) -> list[tuple[re.Pattern[str], bool]]:
        """Compile gitignore patterns to regex for fast matching.

        Returns list of (compiled_pattern, is_dir_only) tuples.
        This optimization reduces repeated fnmatch calls from O(n*m) to O(m)
        where n is patterns and m is files checked.
        """
        compiled = []
        for pattern in self.gitignore_patterns:
            # Check if pattern is directory-only (ends with /)
            is_dir_only = pattern.endswith("/")
            clean_pattern = pattern.rstrip("/")

            # Convert fnmatch pattern to regex
            # fnmatch.translate converts shell-style wildcards to regex
            regex_pattern = fnmatch.translate(clean_pattern)
            try:
                compiled.append((re.compile(regex_pattern), is_dir_only))
            except re.error:
                # If pattern compilation fails, skip it
                continue

        return compiled

    def _is_ignored(self, path: Path) -> bool:
        """Check if a path should be ignored using pre-compiled patterns.

        Optimized to use compiled regex patterns instead of repeated fnmatch calls.
        This reduces CPU usage significantly during directory traversal.
        """
        try:
            relative_path = path.relative_to(self.root_path)
            path_str = str(relative_path)
            is_dir = path.is_dir()

            # Use compiled patterns for fast matching
            for compiled_pattern, is_dir_only in self._compiled_patterns:
                # Skip directory-only patterns if this is a file
                if is_dir_only and not is_dir:
                    continue

                # Use compiled regex for fast matching
                if compiled_pattern.match(path_str):
                    return True

            return False
        except (ValueError, OSError):
            return True

    def _should_stop(self) -> bool:
        return (
            self._file_count >= self.config.max_files
            or (time.time() - self._start_time) > self.config.timeout_seconds
        )

    def _build_tree_structure_iterative(self) -> Generator[str]:
        self._start_time = time.time()
        self._file_count = 0

        yield from self._process_directory(self.root_path, "", 0, is_root=True)

    def _process_directory(
        self, path: Path, prefix: str, depth: int, is_root: bool = False
    ) -> Generator[str]:
        """Process a directory and yield tree structure lines.

        Optimized to avoid creating unnecessary intermediate list.
        Filters and counts in a single pass instead of materializing all items first.
        """
        if depth > self.config.max_depth or self._should_stop():
            return

        try:
            # Filter items while counting total (avoids storing all items in memory)
            items = []
            total_item_count = 0
            for item in path.iterdir():
                total_item_count += 1
                if not self._is_ignored(item):
                    items.append(item)

            items.sort(key=lambda p: (not p.is_dir(), p.name.lower()))

            show_truncation = len(items) > self.config.max_dirs_per_level
            if show_truncation:
                items = items[: self.config.max_dirs_per_level]

            for i, item in enumerate(items):
                if self._should_stop():
                    break

                is_last = i == len(items) - 1 and not show_truncation
                connector = "└── " if is_last else "├── "
                name = f"{item.name}{'/' if item.is_dir() else ''}"

                yield f"{prefix}{connector}{name}"
                self._file_count += 1

                if item.is_dir() and depth < self.config.max_depth:
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    yield from self._process_directory(item, child_prefix, depth + 1)

            if show_truncation and not self._should_stop():
                remaining = total_item_count - len(items)
                yield f"{prefix}└── ... ({remaining} more items)"

        except (PermissionError, OSError):
            pass

    def get_directory_structure(self) -> str:
        lines = []
        header = f"Directory structure of {self.root_path.name} (depth≤{self.config.max_depth}, max {self.config.max_files} items):\n"

        try:
            for line in self._build_tree_structure_iterative():
                lines.append(line)

                current_text = header + "\n".join(lines)
                if (
                    len(current_text)
                    > self.config.max_chars - self.config.truncation_buffer
                ):
                    break

        except Exception as e:
            lines.append(f"Error building structure: {e}")

        structure = header + "\n".join(lines)

        if self._file_count >= self.config.max_files:
            structure += f"\n... (truncated at {self.config.max_files} files limit)"
        elif (time.time() - self._start_time) > self.config.timeout_seconds:
            structure += (
                f"\n... (truncated due to {self.config.timeout_seconds}s timeout)"
            )
        elif len(structure) > self.config.max_chars:
            structure += f"\n... (truncated at {self.config.max_chars} characters)"

        return structure

    async def _run_git_command_async(
        self, args: list[str], timeout: float
    ) -> tuple[bool, str]:
        """Run a git command asynchronously.

        Returns (success, output) tuple.
        """
        try:
            if is_windows():
                # On Windows, need to handle stdin differently
                process = await asyncio.create_subprocess_exec(
                    "git",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL,
                    cwd=self.root_path,
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    "git",
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.root_path,
                )

            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            return (process.returncode == 0, stdout.decode("utf-8", errors="ignore"))
        except asyncio.TimeoutError:
            return (False, "")
        except Exception:
            return (False, "")

    async def _get_git_status_async(self) -> str:
        """Get git status by running multiple git commands concurrently.

        Optimized to run 4 git commands in parallel instead of sequentially.
        This reduces total time from sum(all_commands) to max(slowest_command).
        """
        try:
            timeout = min(self.config.timeout_seconds, 10.0)
            num_commits = self.config.default_commit_count

            # Run all git commands concurrently
            results = await asyncio.gather(
                self._run_git_command_async(["branch", "--show-current"], timeout),
                self._run_git_command_async(["branch", "-r"], timeout),
                self._run_git_command_async(["status", "--porcelain"], timeout),
                self._run_git_command_async(
                    ["log", "--oneline", f"-{num_commits}", "--decorate"], timeout
                ),
                return_exceptions=True,
            )

            # Unpack results
            branch_success, current_branch = results[0] if not isinstance(results[0], Exception) else (False, "")
            branches_success, branches_output = results[1] if not isinstance(results[1], Exception) else (False, "")
            status_success, status_output = results[2] if not isinstance(results[2], Exception) else (False, "")
            log_success, log_output = results[3] if not isinstance(results[3], Exception) else (False, "")

            if not branch_success:
                return "Not a git repository or git not available"

            current_branch = current_branch.strip()

            # Determine main branch
            main_branch = "main"
            if branches_success and "origin/master" in branches_output:
                main_branch = "master"

            # Process status output
            if status_success and status_output.strip():
                status_lines = status_output.strip().splitlines()
                MAX_GIT_STATUS_SIZE = 50
                if len(status_lines) > MAX_GIT_STATUS_SIZE:
                    status = (
                        f"({len(status_lines)} changes - use 'git status' for details)"
                    )
                else:
                    status = f"({len(status_lines)} changes)"
            else:
                status = "(clean)"

            # Process log output
            recent_commits = []
            if log_success:
                for line in log_output.split("\n"):
                    if not (line := line.strip()):
                        continue

                    if " " in line:
                        commit_hash, commit_msg = line.split(" ", 1)
                        if (
                            "(" in commit_msg
                            and ")" in commit_msg
                            and (paren_index := commit_msg.rfind("(")) > 0
                        ):
                            commit_msg = commit_msg[:paren_index].strip()
                        recent_commits.append(f"{commit_hash} {commit_msg}")
                    else:
                        recent_commits.append(line)

            git_info_parts = [
                f"Current branch: {current_branch}",
                f"Main branch (you will usually use this for PRs): {main_branch}",
                f"Status: {status}",
            ]

            if recent_commits:
                git_info_parts.append("Recent commits:")
                git_info_parts.extend(recent_commits)

            return "\n".join(git_info_parts)

        except Exception as e:
            return f"Error getting git status: {e}"

    def get_git_status(self) -> str:
        """Get git status information.

        Runs multiple git commands concurrently for better performance.
        Falls back gracefully if git is not available or times out.
        """
        try:
            # Try to get or create an event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Run the async git operations
            return loop.run_until_complete(self._get_git_status_async())
        except Exception as e:
            return f"Error getting git status: {e}"

    def get_full_context(self) -> str:
        structure = self.get_directory_structure()
        git_status = self.get_git_status()

        large_repo_warning = ""
        if len(structure) >= self.config.max_chars - self.config.truncation_buffer:
            large_repo_warning = (
                f" Large repository detected - showing summary view with depth limit {self.config.max_depth}. "
                f"Use the LS tool (passing a specific path), Bash tool, and other tools to explore nested directories in detail."
            )

        template = UtilityPrompt.PROJECT_CONTEXT.read()
        return template.format(
            large_repo_warning=large_repo_warning,
            structure=structure,
            abs_path=self.root_path,
            git_status=git_status,
        )


def _get_platform_name() -> str:
    platform_names = {
        "win32": "Windows",
        "darwin": "macOS",
        "linux": "Linux",
        "freebsd": "FreeBSD",
        "openbsd": "OpenBSD",
        "netbsd": "NetBSD",
    }
    return platform_names.get(sys.platform, "Unix-like")


def _get_default_shell() -> str:
    """Get the default shell used by asyncio.create_subprocess_shell.

    On Unix, this is always 'sh'.
    On Windows, this is COMSPEC or cmd.exe.
    """
    if is_windows():
        return os.environ.get("COMSPEC", "cmd.exe")
    return "sh"


def _get_os_system_prompt() -> str:
    shell = _get_default_shell()
    platform_name = _get_platform_name()
    prompt = f"The operating system is {platform_name} with shell `{shell}`"

    if is_windows():
        prompt += "\n" + _get_windows_system_prompt()
    return prompt


def _get_windows_system_prompt() -> str:
    return (
        "### COMMAND COMPATIBILITY RULES (MUST FOLLOW):\n"
        "- DO NOT use Unix commands like `ls`, `grep`, `cat` - they won't work on Windows\n"
        "- Use: `dir` (Windows) for directory listings\n"
        "- Use: backslashes (\\\\) for paths\n"
        "- Check command availability with: `where command` (Windows)\n"
        "- Script shebang: Not applicable on Windows\n"
        "### ALWAYS verify commands work on the detected platform before suggesting them"
    )


def _add_commit_signature() -> str:
    return (
        "When you want to commit changes, you will always use the 'git commit' bash command.\n"
        "It will always be suffixed with a line telling it was generated by Mistral Vibe with the appropriate co-authoring information.\n"
        "The format you will always uses is the following heredoc.\n\n"
        "```bash\n"
        "git commit -m <Commit message here>\n\n"
        "Generated by Mistral Vibe.\n"
        "Co-Authored-By: Mistral Vibe <vibe@mistral.ai>\n"
        "```"
    )


def _get_available_skills_section(skill_manager: SkillManager | None) -> str:
    if skill_manager is None:
        return ""

    skills = skill_manager.available_skills
    if not skills:
        return ""

    lines = [
        "# Available Skills",
        "",
        "You have access to the following skills. When a task matches a skill's description,",
        "read the full SKILL.md file to load detailed instructions.",
        "",
        "<available_skills>",
    ]

    for name, info in sorted(skills.items()):
        lines.append("  <skill>")
        lines.append(f"    <name>{html.escape(str(name))}</name>")
        lines.append(
            f"    <description>{html.escape(str(info.description))}</description>"
        )
        lines.append(f"    <path>{html.escape(str(info.skill_path))}</path>")
        lines.append("  </skill>")

    lines.append("</available_skills>")

    return "\n".join(lines)


# Cache for get_universal_system_prompt to avoid expensive directory traversal
_system_prompt_cache: dict[tuple, str] = {}


def get_universal_system_prompt(
    tool_manager: ToolManager,
    config: VibeConfig,
    skill_manager: SkillManager | None = None,
) -> str:
    """Generate universal system prompt with caching.

    Caches the expensive directory traversal and git operations based on
    the state of tools, config, skills, and working directory.
    """
    # Create cache key from relevant state
    active_tools = get_active_tool_classes(tool_manager, config)
    tool_names = tuple(sorted(tool_class.get_name() for tool_class in active_tools))
    skill_names = (
        tuple(sorted(skill_manager.list_skills().keys()))
        if skill_manager
        else ()
    )

    # Key includes: tools, config fields, skills, workdir
    cache_key = (
        tool_names,
        config.system_prompt,
        config.include_commit_signature,
        config.include_model_info,
        config.active_model,
        config.include_prompt_detail,
        config.instructions,
        config.include_project_context,
        str(config.effective_workdir),
        skill_names,
    )

    # Return cached result if available
    if cache_key in _system_prompt_cache:
        return _system_prompt_cache[cache_key]

    # Generate system prompt (expensive operations below)
    result = _generate_system_prompt_uncached(
        tool_manager, config, skill_manager, active_tools
    )

    # Cache the result
    _system_prompt_cache[cache_key] = result

    # Limit cache size to prevent unbounded growth
    if len(_system_prompt_cache) > 100:
        # Remove oldest entry (FIFO eviction)
        _system_prompt_cache.pop(next(iter(_system_prompt_cache)))

    return result


def _generate_system_prompt_uncached(
    tool_manager: ToolManager,
    config: VibeConfig,
    skill_manager: SkillManager | None,
    active_tools: list,
) -> str:
    """Generate system prompt without caching (internal helper)."""
    sections = [config.system_prompt]

    if config.include_commit_signature:
        sections.append(_add_commit_signature())

    if config.include_model_info:
        sections.append(f"Your model name is: `{config.active_model}`")

    if config.include_prompt_detail:
        sections.append(_get_os_system_prompt())
        tool_prompts = []
        # Use pre-computed active_tools to avoid redundant call
        for tool_class in active_tools:
            if prompt := tool_class.get_tool_prompt():
                tool_prompts.append(prompt)
        if tool_prompts:
            sections.append("\n---\n".join(tool_prompts))

        user_instructions = config.instructions.strip() or _load_user_instructions()
        if user_instructions.strip():
            sections.append(user_instructions)

        skills_section = _get_available_skills_section(skill_manager)
        if skills_section:
            sections.append(skills_section)

    if config.include_project_context:
        is_dangerous, reason = is_dangerous_directory()
        if is_dangerous:
            template = UtilityPrompt.DANGEROUS_DIRECTORY.read()
            context = template.format(
                reason=reason.lower(), abs_path=Path(".").resolve()
            )
        else:
            context = ProjectContextProvider(
                config=config.project_context, root_path=config.effective_workdir
            ).get_full_context()

        sections.append(context)

        project_doc = _load_project_doc(
            config.effective_workdir, config.project_context.max_doc_bytes
        )
        if project_doc.strip():
            sections.append(project_doc)

    return "\n\n".join(sections)
