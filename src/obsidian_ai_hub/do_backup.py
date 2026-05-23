import os
import subprocess
import sys
import logging

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

def main():
    """Synchronize configured folders using rsync.

    Uses rsync -a --delete to mirror source -> destination. If any
    rsync invocation fails the script will exit with a non-zero code.
    """
    sync_folders = config.BACKUP_SYNC_FOLDERS

    if not sync_folders:
        logger.error("No backup sync folders configured. Set config.backup.sync_folders in config/config.yml.")
        sys.exit(1)

    had_error = False
    for pair in sync_folders:
        src = pair.get("source")
        dest = pair.get("destination")
        if not src or not dest:
            logger.warning("Skipping invalid sync pair")
            continue

        # Ensure destination directory exists
        try:
            os.makedirs(dest, exist_ok=True)
        except OSError:
            logger.exception("Failed to create destination")
            had_error = True
            continue

        # Ensure we copy the contents of the source directory (trailing slash)
        src_path = src.rstrip('/') + '/'

        cmd = [
            'rsync',
            '-a',
            '--delete',
            '--delete-excluded',
            "--exclude=.DS_Store",
            src_path,
            dest,
        ]

        logger.info("Running rsync for backup")
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            logger.error("rsync not found on PATH. Install rsync or use a different method.")
            sys.exit(2)

        if proc.returncode != 0:
            logger.error("rsync failed (exit %s)", proc.returncode)
            had_error = True

    if had_error:
        sys.exit(1)

if __name__ == "__main__":
    main()
