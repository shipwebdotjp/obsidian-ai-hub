"""Backup synchronization service.

Mirrors configured folders with rsync. The rsync binary can be pinned via
``backup.rsync_executable`` so a GNU rsync can be used instead of the
openrsync shipped with macOS, which can abort during ``--delete`` scans.
"""

from __future__ import annotations

import logging
import os
import subprocess

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

_DEFAULT_RSYNC_EXECUTABLE = "rsync"
_OPENRSYNC_MARKER = "openrsync"


class BackupError(RuntimeError):
    """Raised when configuration or one or more backup synchronizations fail."""


def _resolve_executable() -> str:
    """Return the rsync executable, validating an explicit configuration value."""
    value = config.BACKUP_RSYNC_EXECUTABLE
    if value is None:
        return _DEFAULT_RSYNC_EXECUTABLE
    if not isinstance(value, str):
        raise BackupError(
            "Invalid backup.rsync_executable: expected a single executable path, "
            f"got {type(value).__name__}."
        )
    executable = value.strip()
    if not executable:
        raise BackupError("Invalid backup.rsync_executable: value must not be empty.")
    return executable


def _preflight(executable: str) -> None:
    """Run ``<executable> --version`` once before touching any destination."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
        )
    except FileNotFoundError:
        raise BackupError(
            f"rsync executable not found: {executable!r}. "
            "Install rsync or set backup.rsync_executable to an existing path."
        ) from None
    except OSError as exc:
        raise BackupError(
            f"Failed to run rsync executable {executable!r}: {exc}"
        ) from exc

    output = proc.stdout or ""
    if proc.returncode != 0:
        raise BackupError(
            f"rsync executable {executable!r} failed --version "
            f"(exit {proc.returncode}): {output.strip()}"
        )

    if _OPENRSYNC_MARKER in output.lower():
        logger.warning(
            "Configured rsync executable appears to be openrsync, which can "
            "abort with an assertion during --delete scanning. Install GNU rsync "
            "(e.g. `brew install rsync`) and set backup.rsync_executable to an "
            "absolute path such as /opt/homebrew/opt/rsync/bin/rsync. "
            "Continuing with the configured executable.",
        )


def run_backup() -> None:
    """Mirror configured folders with rsync.

    Uses ``-a --inplace --delete --delete-excluded`` to mirror each source into
    its destination. Configuration and the rsync executable are validated
    before any destination directory is created. If any rsync invocation fails,
    every pair is still attempted and a single :class:`BackupError` aggregates
    the failures at the end.
    """
    sync_folders = config.BACKUP_SYNC_FOLDERS

    if not sync_folders:
        message = (
            "No backup sync folders configured. "
            "Set config.backup.sync_folders in config/config.yml."
        )
        logger.error(message)
        raise BackupError(message)

    executable = _resolve_executable()
    _preflight(executable)

    errors = []
    for pair in sync_folders:
        if not isinstance(pair, dict):
            logger.warning("Skipping invalid sync pair: %r", pair)
            continue
        src = pair.get("source")
        dest = pair.get("destination")
        if not isinstance(src, str) or not isinstance(dest, str) or not src or not dest:
            logger.warning("Skipping invalid sync pair")
            continue

        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as exc:
            message = f"Failed to create backup destination {dest!r}: {exc}"
            logger.exception(message)
            errors.append(message)
            continue

        # Per-pair excludes are passed through to rsync unmodified, in listed
        # order, directly after the fixed --exclude=.DS_Store. Empty strings are
        # invalid, matching the falsy check used for source/destination above;
        # patterns are never stripped or converted.
        extra_excludes: list[str] = []
        if "excludes" in pair:
            excludes = pair.get("excludes")
            if not isinstance(excludes, list):
                logger.warning(
                    "Invalid excludes for %r -> %r: expected a list, ignoring excludes",
                    src,
                    dest,
                )
            else:
                for pattern in excludes:
                    if not isinstance(pattern, str) or pattern == "":
                        logger.warning(
                            "Invalid exclude pattern for %r -> %r: %r, ignoring",
                            src,
                            dest,
                            pattern,
                        )
                        continue
                    extra_excludes.append(pattern)

        # Ensure we copy the contents of the source directory (trailing slash)
        src_path = src.rstrip("/") + "/"

        cmd = [
            executable,
            "-a",
            "--inplace",
            "--delete",
            "--delete-excluded",
            "--exclude=.DS_Store",
            *(f"--exclude={pattern}" for pattern in extra_excludes),
            src_path,
            dest,
        ]

        logger.info("Running rsync for backup")
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="backslashreplace",
            )
        except FileNotFoundError:
            message = (
                f"rsync executable not found: {executable!r}. "
                "Install rsync or use a different method."
            )
            logger.error(message)
            errors.append(message)
            continue
        except OSError as exc:
            message = f"Failed to run rsync executable {executable!r}: {exc}"
            logger.error(message)
            errors.append(message)
            continue

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            message = (
                f"rsync failed for {src!r} -> {dest!r} "
                f"(exit {proc.returncode})"
            )
            if stderr:
                message = f"{message}: {stderr}"
            logger.error(message)
            errors.append(message)

    if errors:
        raise BackupError("Backup failed:\n" + "\n".join(errors))
