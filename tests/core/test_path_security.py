"""Tests for path security validation utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from vibe.core.path_security import (
    PathSecurityError,
    _reject_unc_paths,
    _reject_windows_device_paths,
    case_insensitive_fnmatch,
    validate_safe_path,
)


class TestWindowsDevicePaths:
    """Test rejection of Windows device paths."""

    @pytest.mark.parametrize(
        "path_str",
        [
            "\\\\.\\COM1",  # \\.\COM1
            "\\\\.\\C:",  # \\.\C:
            "\\\\.\\GLOBALROOT\\Device\\HarddiskVolume1",
            "\\\\?\\C:\\Windows",
            "//./COM1",  # Forward-slash variant
            "//?/C:/Windows",
        ],
    )
    def test_rejects_device_paths(self, path_str: str) -> None:
        with pytest.raises(PathSecurityError, match="Device paths are not allowed"):
            _reject_windows_device_paths(path_str)

    def test_allows_normal_paths(self) -> None:
        # Should not raise
        _reject_windows_device_paths("C:\\Users\\test\\project\\file.txt")
        _reject_windows_device_paths("/home/user/project/file.txt")


class TestUNCPaths:
    """Test rejection of UNC network paths."""

    @pytest.mark.parametrize(
        "path_str",
        [
            "\\\\server\\share\\file.txt",  # \\server\share\file.txt
            "\\\\192.168.1.1\\share",  # \\192.168.1.1\share
            "//server/share",  # Forward-slash variant
        ],
    )
    def test_rejects_unc_paths(self, path_str: str) -> None:
        with pytest.raises(PathSecurityError, match="Network.*paths are not allowed"):
            _reject_unc_paths(path_str)

    def test_allows_device_path_prefixes(self) -> None:
        # Device paths like \\.\ or \\?\ should not trigger UNC rejection
        # (they're handled by _reject_windows_device_paths)
        _reject_unc_paths("\\\\.\\COM1")  # Not a UNC path
        _reject_unc_paths("\\\\?\\C:\\Windows")  # Not a UNC path


class TestValidateSafePath:
    """Test the main validation function."""

    def test_path_within_root_allowed(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        file_path = project_root / "subdir" / "file.txt"

        # Should not raise
        validate_safe_path(file_path, project_root)

    def test_path_outside_root_rejected(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        outside_file = tmp_path / "outside.txt"

        with pytest.raises(PathSecurityError, match="outside project directory"):
            validate_safe_path(outside_file, project_root)

    @pytest.mark.skipif(
        not hasattr(Path, "symlink_to"), reason="Symlinks not supported"
    )
    def test_symlink_inside_root_allowed(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        target = project_root / "target.txt"
        target.write_text("content")
        link = project_root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Unable to create symlinks (requires admin on Windows)")

        # Should not raise - symlink target is within root
        validate_safe_path(link, project_root)

    @pytest.mark.skipif(
        not hasattr(Path, "symlink_to"), reason="Symlinks not supported"
    )
    def test_symlink_outside_root_rejected(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        outside_target = tmp_path / "outside.txt"
        outside_target.write_text("secret")
        link = project_root / "link.txt"
        try:
            link.symlink_to(outside_target)
        except OSError:
            pytest.skip("Unable to create symlinks (requires admin on Windows)")

        with pytest.raises(PathSecurityError, match="Symlink escapes project"):
            validate_safe_path(link, project_root)

    @patch("vibe.core.path_security.is_windows", return_value=True)
    def test_windows_device_path_rejected(self, mock_windows: Any) -> None:
        project_root = Path("C:\\project")
        device_path = Path("\\\\.\\COM1")

        with pytest.raises(PathSecurityError, match="Device paths"):
            validate_safe_path(device_path, project_root)

    @patch("vibe.core.path_security.is_windows", return_value=True)
    def test_windows_unc_path_rejected(self, mock_windows: Any) -> None:
        project_root = Path("C:\\project")
        unc_path = Path("\\\\server\\share\\file.txt")

        with pytest.raises(PathSecurityError, match="Network"):
            validate_safe_path(unc_path, project_root)


class TestCaseInsensitiveFnmatch:
    """Test case-insensitive pattern matching."""

    @patch("vibe.core.path_security.is_windows", return_value=True)
    def test_windows_case_insensitive(self, mock_windows: Any) -> None:
        assert case_insensitive_fnmatch("File.TXT", "*.txt")
        assert case_insensitive_fnmatch("FILE.TXT", "*.txt")
        assert case_insensitive_fnmatch("file.txt", "*.TXT")

    @patch("vibe.core.path_security.is_windows", return_value=False)
    def test_unix_case_sensitive(self, mock_windows: Any) -> None:
        assert case_insensitive_fnmatch("file.txt", "*.txt")
        assert not case_insensitive_fnmatch("File.TXT", "*.txt")
        assert not case_insensitive_fnmatch("FILE.TXT", "*.txt")
