r"""Path security utilities for validating file access within project boundaries.

This module provides centralized path validation to protect against:
- Path traversal attacks (../ escapes)
- Windows device paths (\\.\COM1, \\?\Device\...)
- UNC network paths (\\server\share)
- Symlink escapes (symlinks pointing outside project root)
"""

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path


class PathSecurityError(Exception):
    """Raised when a path fails security validation."""


def is_windows() -> bool:
    """Check if running on Windows."""
    return sys.platform == "win32"


def validate_safe_path(
    path: Path,
    project_root: Path,
    *,
    check_symlinks: bool = True,
) -> None:
    r"""Validate that a resolved path is safe to access.

    Performs the following checks:
    1. Rejects Windows device paths (\\.\, \\?\)
    2. Rejects UNC network paths (\\server\share)
    3. Validates path is within project root
    4. Optionally checks symlinks don't escape project root

    Args:
        path: The resolved path to validate
        project_root: The resolved project root directory
        check_symlinks: If True, verify symlink targets are within root

    Raises:
        PathSecurityError: If validation fails
    """
    path_str = str(path)

    # Windows-specific checks
    if is_windows():
        _reject_windows_device_paths(path_str)
        _reject_unc_paths(path_str)

    # Universal checks
    _validate_path_within_root(path, project_root)

    if check_symlinks:
        _validate_symlink_targets(path, project_root)


def _reject_windows_device_paths(path_str: str) -> None:
    r"""Reject Windows device paths like \\.\COM1 or \\?\Device\..."""
    # Match \\.\, \\?\, or forward-slash variants
    device_pattern = r"^(\\\\|//)[.?](\\|/)"
    if re.match(device_pattern, path_str, re.IGNORECASE):
        raise PathSecurityError(f"Device paths are not allowed: {path_str}")


def _reject_unc_paths(path_str: str) -> None:
    r"""Reject UNC network paths like \\server\share."""
    # UNC paths start with \\ followed by a server name (not . or ?)
    # Already resolved paths won't have UNC prefixes unless they're actual network paths
    unc_pattern = r"^(\\\\|//)[^.?\\/]"
    if re.match(unc_pattern, path_str):
        raise PathSecurityError(f"Network (UNC) paths are not allowed: {path_str}")


def _validate_path_within_root(path: Path, project_root: Path) -> None:
    """Validate that path is within project root using relative_to."""
    try:
        path.relative_to(project_root)
    except ValueError:
        raise PathSecurityError(
            f"Cannot access path outside project directory: {path}"
        )


def _validate_symlink_targets(path: Path, project_root: Path) -> None:
    """Validate that symlinks in path don't point outside project root.

    Walks up the path checking each component. If any component is a symlink,
    verifies its resolved target is within the project root.
    """
    # Build list of path components to check
    parts_to_check: list[Path] = []
    current = path
    while current != project_root and current != current.parent:
        parts_to_check.append(current)
        current = current.parent

    # Check each component for symlinks
    for component in parts_to_check:
        try:
            if component.is_symlink():
                # Resolve this specific symlink and check target
                target = component.resolve()
                try:
                    target.relative_to(project_root)
                except ValueError:
                    raise PathSecurityError(
                        f"Symlink escapes project directory: {component} -> {target}"
                    )
        except OSError:
            # Path component doesn't exist yet (e.g., for write operations)
            # This is fine - the symlink check is about existing symlinks
            pass


def case_insensitive_fnmatch(name: str, pattern: str) -> bool:
    """
    Perform fnmatch with appropriate case sensitivity for the OS.

    On Windows, performs case-insensitive matching.
    On Unix-like systems, performs case-sensitive matching.

    Args:
        name: The filename to match
        pattern: The glob pattern to match against

    Returns:
        True if the name matches the pattern
    """
    if is_windows():
        return fnmatch.fnmatch(name.lower(), pattern.lower())
    return fnmatch.fnmatch(name, pattern)
