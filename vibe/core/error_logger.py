"""Persistent error logging for Vibe.

This module provides a centralized error logging system that writes errors
to a persistent log file for debugging and troubleshooting purposes.
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from vibe.core.paths.global_paths import ERROR_LOG_FILE, LOG_DIR


# Maximum log file size in bytes (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024
# Number of backup log files to keep
BACKUP_COUNT = 3


def _ensure_log_directory() -> None:
    """Ensure the log directory exists."""
    try:
        LOG_DIR.path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass  # Best effort - logging shouldn't crash the app


def _rotate_log_if_needed(log_path: Path) -> None:
    """Rotate the log file if it exceeds MAX_LOG_SIZE."""
    try:
        if not log_path.exists():
            return

        if log_path.stat().st_size < MAX_LOG_SIZE:
            return

        # Rotate existing backup files
        for i in range(BACKUP_COUNT - 1, 0, -1):
            old_backup = log_path.with_suffix(f".log.{i}")
            new_backup = log_path.with_suffix(f".log.{i + 1}")
            if old_backup.exists():
                if i == BACKUP_COUNT - 1:
                    old_backup.unlink()  # Delete oldest backup
                else:
                    old_backup.rename(new_backup)

        # Rename current log to .log.1
        log_path.rename(log_path.with_suffix(".log.1"))

    except Exception:
        pass  # Best effort rotation


class ErrorLogger:
    """A persistent error logger that writes to a file.

    Errors are written with timestamps and stack traces for debugging.
    The log file is automatically rotated when it exceeds MAX_LOG_SIZE.
    """

    _instance: ErrorLogger | None = None
    _logger: logging.Logger | None = None

    def __new__(cls) -> ErrorLogger:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._logger is not None:
            return

        _ensure_log_directory()
        log_path = ERROR_LOG_FILE.path
        _rotate_log_if_needed(log_path)

        # Create a dedicated logger for errors
        self._logger = logging.getLogger("vibe.errors")
        self._logger.setLevel(logging.ERROR)
        self._logger.propagate = False  # Don't propagate to root logger

        # Create file handler
        try:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setLevel(logging.ERROR)

            # Create formatter
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)

            self._logger.addHandler(handler)
        except Exception:
            # If file logging fails, fall back to stderr
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(logging.ERROR)
            self._logger.addHandler(handler)

    def log_error(
        self,
        message: str,
        error: Exception | None = None,
        context: dict[str, Any] | None = None,
        include_traceback: bool = True
    ) -> None:
        """Log an error to the persistent error log.

        Args:
            message: A descriptive error message
            error: The exception that was raised (optional)
            context: Additional context information (optional)
            include_traceback: Whether to include the full traceback (default: True)
        """
        if self._logger is None:
            return

        parts = [message]

        if error:
            parts.append(f"Exception: {type(error).__name__}: {error}")

        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            parts.append(f"Context: {context_str}")

        if include_traceback and error:
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            parts.append(f"Traceback:\n{tb}")

        full_message = "\n".join(parts)
        self._logger.error(full_message)

    def log_warning(
        self,
        message: str,
        context: dict[str, Any] | None = None
    ) -> None:
        """Log a warning to the persistent error log.

        Args:
            message: A descriptive warning message
            context: Additional context information (optional)
        """
        if self._logger is None:
            return

        parts = [message]

        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            parts.append(f"Context: {context_str}")

        full_message = "\n".join(parts)
        # Use error level since this is the error log
        self._logger.error(f"WARNING: {full_message}")


# Global singleton instance
_error_logger: ErrorLogger | None = None


def get_error_logger() -> ErrorLogger:
    """Get the global error logger instance."""
    global _error_logger
    if _error_logger is None:
        _error_logger = ErrorLogger()
    return _error_logger


def log_error(
    message: str,
    error: Exception | None = None,
    context: dict[str, Any] | None = None,
    include_traceback: bool = True
) -> None:
    """Convenience function to log an error.

    Args:
        message: A descriptive error message
        error: The exception that was raised (optional)
        context: Additional context information (optional)
        include_traceback: Whether to include the full traceback (default: True)
    """
    get_error_logger().log_error(message, error, context, include_traceback)


def log_warning(
    message: str,
    context: dict[str, Any] | None = None
) -> None:
    """Convenience function to log a warning.

    Args:
        message: A descriptive warning message
        context: Additional context information (optional)
    """
    get_error_logger().log_warning(message, context)
