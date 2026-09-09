import os
import subprocess
import logging

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Raised when one or more configured backup synchronizations fail."""


def main():
    """Synchronize configured folders using rsync.

    Uses rsync -a --delete to mirror source -> destination. If any
    rsync invocation fails the script will exit with a non-zero code.
    """
    sync_folders = config.BACKUP_SYNC_FOLDERS

    if not sync_folders:
        message = (
            "No backup sync folders configured. "
            "Set config.backup.sync_folders in config/config.yml."
        )
        logger.error(message)
        raise BackupError(message)

    errors = []
    for pair in sync_folders:
        src = pair.get("source")
        dest = pair.get("destination")
        if not src or not dest:
            logger.warning("Skipping invalid sync pair")
            continue

        # Ensure destination directory exists
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError as exc:
            message = f"Failed to create backup destination {dest!r}: {exc}"
            logger.exception(message)
            errors.append(message)
            continue

        # Per-pair excludes: passed through to rsync unmodified, in listed order,
        # directly after the fixed --exclude=.DS_Store. Empty strings are invalid,
        # matching the falsy check used for source/destination above; patterns
        # are never stripped or converted.
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
            "rsync",
            "-a",
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
            message = "rsync not found on PATH. Install rsync or use a different method."
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


if __name__ == "__main__":
    main()
