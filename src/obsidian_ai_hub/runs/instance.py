"""Process instance identity and exclusive run-worker lock."""

from __future__ import annotations

import fcntl
import logging
import uuid
from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

_INSTANCE_ID: Optional[str] = None


def get_instance_id() -> str:
    """Return the stable UUID for this application process."""
    global _INSTANCE_ID
    if _INSTANCE_ID is None:
        _INSTANCE_ID = f"inst_{uuid.uuid4().hex[:12]}"
    return _INSTANCE_ID


def lock_file_path() -> Path:
    db_path = Path(str(config.MEMORY_SQLITE_PATH)).expanduser()
    return db_path.parent / (db_path.name + ".run-worker.lock")


class RunWorkerLock:
    """Single-process exclusive lock shared by Agent/Coding workers.

    The lock is held for the whole process lifetime via an open FD with
    flock(LOCK_EX|LOCK_NB). A second app process fails to acquire and must
    not start workers nor mutate runs.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or lock_file_path()
        self._fd: Optional[int] = None

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Open (create) the lock file and hold the FD for process lifetime.
            import os

            fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            logger.warning("Failed to open run-worker lock %s: %s", self._path, exc)
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                import os as _os

                _os.close(fd)
            except OSError:
                pass
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            import os

            os.close(self._fd)
        except OSError:
            pass
        self._fd = None

    def is_held(self) -> bool:
        return self._fd is not None
