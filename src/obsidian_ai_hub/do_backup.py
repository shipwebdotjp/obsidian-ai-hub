"""CLI wrapper for the backup synchronization service."""

from obsidian_ai_hub.backup.service import BackupError, run_backup

__all__ = ["BackupError", "main"]


def main():
    """Synchronize configured folders using rsync.

    Mirrors each configured source into its destination. If any rsync
    invocation fails the script exits with a non-zero code raised as
    :class:`BackupError`.
    """
    run_backup()


if __name__ == "__main__":
    main()
