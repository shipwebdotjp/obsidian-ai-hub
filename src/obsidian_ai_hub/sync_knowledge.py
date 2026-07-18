"""
Open Web UI Knowledge Base Sync

Synchronizes Obsidian Vault files with Open Web UI knowledge bases.
Each subdirectory under config.KNOWLEDGE_SYNC_FOLDER is treated as a knowledge_id.

Workflow:
1. Load previous sync state (last_sync timestamp, file list with mtimes)
2. Scan local files in config.KNOWLEDGE_SYNC_FOLDER/<knowledge_id>/
3. Detect changes (NEW, UPDATED, DELETED) per knowledge_id
4. Apply changes via Open Web UI API
5. Save new sync state
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.web_ui_client import (
    add_to_knowledge,
    remove_from_knowledge,
    upload_file,
    wait_for_file_processing,
)

logger = logging.getLogger(__name__)

# State file location
STATE_FILE_PATH = config.KNOWLEDGE_SYNC_STATE_PATH


def _empty_state() -> "SyncState":
    return SyncState(
        last_sync=datetime.now(timezone.utc).isoformat(),
        files=[],
    )


def _file_key(knowledge_id: str, file_path: str) -> Tuple[str, str]:
    return knowledge_id, file_path


def _format_file_key(knowledge_id: str, file_path: str) -> str:
    return f"{knowledge_id}/{file_path}"


@dataclass
class FileState:
    """Represents a file's state in sync."""

    knowledge_id: str
    name: str  # Relative path from the knowledge folder root
    mtime: float  # Modification time
    file_id_on_webui: Optional[str] = None  # File ID on Open Web UI


@dataclass
class KnowledgeChanges:
    """Change set for a single knowledge_id."""

    new_files: List[str] = field(default_factory=list)
    updated_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success_count: int = 0
    error_count: int = 0
    error_files: List[str] = None
    duration_sec: float = 0.0

    def __post_init__(self):
        if self.error_files is None:
            self.error_files = []


@dataclass
class SyncState:
    """Complete sync state."""

    last_sync: str  # ISO format timestamp
    files: List[FileState]  # List of files with their state

    @classmethod
    def from_dict(cls, data: Dict) -> "SyncState":
        """Create SyncState from dictionary."""
        files = [
            FileState(
                knowledge_id=f["knowledge_id"],
                name=f["name"],
                mtime=f["mtime"],
                file_id_on_webui=f.get("file_id_on_webui"),
            )
            for f in data.get("files", [])
        ]
        return cls(
            last_sync=data.get("last_sync", datetime.now(timezone.utc).isoformat()),
            files=files,
        )

    def to_dict(self) -> Dict:
        """Convert SyncState to dictionary."""
        return {
            "last_sync": self.last_sync,
            "files": [asdict(f) for f in self.files],
        }


def load_state_file() -> SyncState:
    """
    Load the sync state from JSON file.
    Returns empty state if file doesn't exist.

    Returns:
        SyncState object
    """
    if not STATE_FILE_PATH.exists():
        logger.info(f"State file not found, starting with empty state: {STATE_FILE_PATH}")
        return _empty_state()

    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = SyncState.from_dict(data)
        logger.info(f"Loaded state file with {len(state.files)} tracked files")
        return state
    except Exception as e:
        logger.error(f"Failed to load state file: {e}. Starting with empty state.")
        return _empty_state()


def save_state_file(state: SyncState) -> bool:
    """
    Save the sync state to JSON file.

    Args:
        state: SyncState object to save

    Returns:
        True if successful, False otherwise
    """
    try:
        STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"State file saved with {len(state.files)} files")
        return True
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")
        return False


def scan_local_files() -> Dict[str, Dict[str, float]]:
    """
    Scan local knowledge folder for markdown files.
    Each immediate subdirectory of config.KNOWLEDGE_SYNC_FOLDER is treated as a knowledge_id.

    Returns:
        Dict mapping knowledge_id -> Dict(relative file path -> mtime)
    """
    files: Dict[str, Dict[str, float]] = {}

    if not config.KNOWLEDGE_SYNC_FOLDER.exists():
        logger.warning(f"Knowledge sync folder does not exist: {config.KNOWLEDGE_SYNC_FOLDER}")
        return files

    try:
        knowledge_dirs = sorted(
            [path for path in config.KNOWLEDGE_SYNC_FOLDER.iterdir() if path.is_dir()],
            key=lambda path: path.name,
        )

        for knowledge_dir in knowledge_dirs:
            knowledge_id = knowledge_dir.name
            knowledge_files: Dict[str, float] = {}

            for md_file in sorted(knowledge_dir.rglob("*.md")):
                if md_file.is_file():
                    rel_path = md_file.relative_to(knowledge_dir).as_posix()
                    knowledge_files[rel_path] = md_file.stat().st_mtime

            files[knowledge_id] = knowledge_files

        total_files = sum(len(knowledge_files) for knowledge_files in files.values())
        logger.info(
            f"Scanned {total_files} markdown files across {len(files)} knowledge folders "
            f"in {config.KNOWLEDGE_SYNC_FOLDER}"
        )
        return files
    except Exception as e:
        logger.error(f"Error scanning local files: {e}")
        return files


class ChangeDetector:
    """Detects changes between local files and sync state."""

    @staticmethod
    def detect_changes(
        local_files: Dict[str, Dict[str, float]],
        previous_state: SyncState,
    ) -> Dict[str, KnowledgeChanges]:
        """
        Detect NEW, UPDATED, and DELETED files per knowledge_id.

        Args:
            local_files: Dict of knowledge_id -> Dict of local file paths -> mtimes
            previous_state: Previous sync state

        Returns:
            Dict mapping knowledge_id -> KnowledgeChanges
        """
        previous_files: Dict[str, Dict[str, FileState]] = {}
        for file_state in previous_state.files:
            previous_files.setdefault(file_state.knowledge_id, {})[file_state.name] = file_state

        knowledge_ids = sorted(set(local_files.keys()) | set(previous_files.keys()))
        changes_by_knowledge: Dict[str, KnowledgeChanges] = {}

        for knowledge_id in knowledge_ids:
            current_files = local_files.get(knowledge_id, {})
            previous_for_knowledge = previous_files.get(knowledge_id, {})

            new_files: List[str] = []
            updated_files: List[str] = []
            deleted_files: List[str] = []

            current_file_set = set(current_files.keys())
            previous_file_set = set(previous_for_knowledge.keys())

            for file_path, mtime in current_files.items():
                if file_path not in previous_for_knowledge:
                    new_files.append(file_path)
                    logger.debug(f"NEW file detected: {knowledge_id}/{file_path}")
                elif mtime != previous_for_knowledge[file_path].mtime:
                    updated_files.append(file_path)
                    logger.debug(f"UPDATED file detected: {knowledge_id}/{file_path}")

            for file_path in previous_file_set - current_file_set:
                deleted_files.append(file_path)
                logger.debug(f"DELETED file detected: {knowledge_id}/{file_path}")

            if new_files or updated_files or deleted_files:
                changes_by_knowledge[knowledge_id] = KnowledgeChanges(
                    new_files=new_files,
                    updated_files=updated_files,
                    deleted_files=deleted_files,
                )

        total_new = sum(len(changes.new_files) for changes in changes_by_knowledge.values())
        total_updated = sum(len(changes.updated_files) for changes in changes_by_knowledge.values())
        total_deleted = sum(len(changes.deleted_files) for changes in changes_by_knowledge.values())
        logger.info(
            f"Change detection: {total_new} new, {total_updated} updated, {total_deleted} deleted"
        )

        return changes_by_knowledge


class ChangeApplier:
    """Applies changes to Open Web UI knowledge bases."""

    def apply_changes(
        self,
        knowledge_id: str,
        new_files: List[str],
        updated_files: List[str],
        deleted_files: List[str],
        previous_state: SyncState,
    ) -> Tuple[int, int, List[str], Dict[Tuple[str, str], str], Set[Tuple[str, str]]]:
        """
        Apply file changes to Open Web UI knowledge base.

        Args:
            knowledge_id: Knowledge base ID
            new_files: List of new file paths
            updated_files: List of updated file paths
            deleted_files: List of deleted file paths
            previous_state: Previous sync state for file_id lookup

        Returns:
            Tuple of (success_count, error_count, error_files, file_id_map, successful_files)
            file_id_map: Dict mapping (knowledge_id, file_path) -> new file_id on WebUI
            successful_files: Set of (knowledge_id, file_path) that were successfully processed
        """
        success_count = 0
        error_count = 0
        error_files: List[str] = []
        file_id_map: Dict[Tuple[str, str], str] = {}
        successful_files: Set[Tuple[str, str]] = set()

        previous_files_map = {
            file_state.name: file_state
            for file_state in previous_state.files
            if file_state.knowledge_id == knowledge_id
        }

        for file_path in updated_files:
            logger.info(f"Processing UPDATED file: {knowledge_id}/{file_path}")
            previous_file = previous_files_map.get(file_path)

            if previous_file and previous_file.file_id_on_webui:
                if not remove_from_knowledge(previous_file.file_id_on_webui, knowledge_id):
                    logger.error(f"Failed to remove old file: {knowledge_id}/{file_path}")
                    error_count += 1
                    error_files.append(_format_file_key(knowledge_id, file_path))
                    continue

            success, file_id = self._upload_and_add_file(knowledge_id, file_path)
            if success and file_id:
                success_count += 1
                file_id_map[_file_key(knowledge_id, file_path)] = file_id
                successful_files.add(_file_key(knowledge_id, file_path))
            else:
                error_count += 1
                error_files.append(_format_file_key(knowledge_id, file_path))

        for file_path in new_files:
            logger.info(f"Processing NEW file: {knowledge_id}/{file_path}")
            success, file_id = self._upload_and_add_file(knowledge_id, file_path)
            if success and file_id:
                success_count += 1
                file_id_map[_file_key(knowledge_id, file_path)] = file_id
                successful_files.add(_file_key(knowledge_id, file_path))
            else:
                error_count += 1
                error_files.append(_format_file_key(knowledge_id, file_path))

        for file_path in deleted_files:
            logger.info(f"Processing DELETED file: {knowledge_id}/{file_path}")
            previous_file = previous_files_map.get(file_path)

            if previous_file and previous_file.file_id_on_webui:
                if remove_from_knowledge(previous_file.file_id_on_webui, knowledge_id):
                    success_count += 1
                    successful_files.add(_file_key(knowledge_id, file_path))
                else:
                    error_count += 1
                    error_files.append(_format_file_key(knowledge_id, file_path))
            else:
                logger.debug(
                    f"File was never uploaded, no need to delete: {knowledge_id}/{file_path}"
                )
                success_count += 1
                successful_files.add(_file_key(knowledge_id, file_path))

        logger.info(
            f"Applied changes for {knowledge_id}: {success_count} succeeded, {error_count} failed"
        )

        return success_count, error_count, error_files, file_id_map, successful_files

    def _upload_and_add_file(
        self,
        knowledge_id: str,
        file_path: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload a file and add it to knowledge base.

        Args:
            knowledge_id: Knowledge base ID
            file_path: Relative path from the knowledge folder root

        Returns:
            Tuple of (success: bool, file_id: Optional[str])
        """
        full_path = config.KNOWLEDGE_SYNC_FOLDER / knowledge_id / file_path

        if not full_path.exists():
            logger.error(f"File not found: {full_path}")
            return False, None

        file_id = upload_file(full_path)
        if not file_id:
            logger.error(f"Failed to upload file: {knowledge_id}/{file_path}")
            return False, None

        logger.info(f"File uploaded successfully: {knowledge_id}/{file_path} (ID: {file_id})")

        if not wait_for_file_processing(file_id):
            logger.error(f"File processing failed or timed out: {knowledge_id}/{file_path}")
            return False, None

        if not add_to_knowledge(file_id, knowledge_id):
            logger.error(f"Failed to add file to knowledge base: {knowledge_id}/{file_path}")
            return False, None

        return True, file_id


def create_new_state(
    local_files: Dict[str, Dict[str, float]],
    previous_state: SyncState,
    successful_files: Set[Tuple[str, str]],
    updated_file_ids: Dict[Tuple[str, str], str],
) -> SyncState:
    """
    Create new sync state based on successful uploads.

    Args:
        local_files: Dict of knowledge_id -> Dict of local file paths -> mtimes
        previous_state: Previous sync state
        successful_files: Set of (knowledge_id, file_path) that were successfully processed
        updated_file_ids: Dict mapping (knowledge_id, file_path) -> new file_id on WebUI

    Returns:
        New SyncState
    """
    new_files: List[FileState] = []
    previous_files_map = {
        _file_key(file_state.knowledge_id, file_state.name): file_state
        for file_state in previous_state.files
    }

    for knowledge_id, knowledge_files in local_files.items():
        for file_path, mtime in knowledge_files.items():
            file_key = _file_key(knowledge_id, file_path)
            previous_file = previous_files_map.get(file_key)

            if file_key in successful_files:
                file_id = updated_file_ids.get(
                    file_key,
                    previous_file.file_id_on_webui if previous_file else None,
                )
                new_files.append(
                    FileState(
                        knowledge_id=knowledge_id,
                        name=file_path,
                        mtime=mtime,
                        file_id_on_webui=file_id,
                    )
                )
            elif previous_file:
                new_files.append(previous_file)
            else:
                continue

    new_files.sort(key=lambda file_state: (file_state.knowledge_id, file_state.name))

    return SyncState(
        last_sync=datetime.now(timezone.utc).isoformat(),
        files=new_files,
    )


def main() -> SyncResult:
    """
    Main sync function orchestrating the entire synchronization process.

    Returns:
        SyncResult with statistics
    """
    config.ensure_external_allowed("Knowledge sync")
    start_time = time.time()
    result = SyncResult()

    try:
        logger.info("Starting knowledge base sync...")

        previous_state = load_state_file()
        local_files = scan_local_files()

        detector = ChangeDetector()
        changes_by_knowledge = detector.detect_changes(local_files, previous_state)

        if not changes_by_knowledge:
            logger.info("No changes detected")
            result.duration_sec = time.time() - start_time
            return result

        applier = ChangeApplier()
        successful_files: Set[Tuple[str, str]] = set()
        file_id_map: Dict[Tuple[str, str], str] = {}

        for knowledge_id in sorted(changes_by_knowledge.keys()):
            changes = changes_by_knowledge[knowledge_id]
            success_count, error_count, error_files, group_file_id_map, group_successful_files = (
                applier.apply_changes(
                    knowledge_id,
                    changes.new_files,
                    changes.updated_files,
                    changes.deleted_files,
                    previous_state,
                )
            )

            result.success_count += success_count
            result.error_count += error_count
            result.error_files.extend(error_files)
            successful_files.update(group_successful_files)
            file_id_map.update(group_file_id_map)

        new_state = create_new_state(
            local_files=local_files,
            previous_state=previous_state,
            successful_files=successful_files,
            updated_file_ids=file_id_map,
        )

        if save_state_file(new_state):
            logger.info("Sync completed successfully")
        else:
            logger.error("Failed to save state file, but sync operations completed")

        result.duration_sec = time.time() - start_time
        return result

    except Exception as e:
        logger.error(f"Fatal error during sync: {e}", exc_info=True)
        result.error_count += 1
        result.duration_sec = time.time() - start_time
        return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    result = main()
    logger.info("Sync result: %s succeeded, %s failed", result.success_count, result.error_count)
    if result.error_files:
        logger.info("Failed files count: %s", len(result.error_files))
