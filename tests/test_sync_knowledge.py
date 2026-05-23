"""
Tests for sync_knowledge module

Tests for:
- State file loading/saving
- Local file scanning
- Change detection (NEW, UPDATED, DELETED)
- Sync result tracking
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from obsidian_ai_hub.sync_knowledge import (
    FileState,
    KnowledgeChanges,
    SyncState,
    SyncResult,
    ChangeDetector,
    create_new_state,
    load_state_file,
    save_state_file,
    scan_local_files,
)


class TestFileState:
    """Test FileState data class"""
    
    def test_create_file_state(self):
        fs = FileState(knowledge_id="kb1", name="note.md", mtime=123456.0)
        assert fs.knowledge_id == "kb1"
        assert fs.name == "note.md"
        assert fs.mtime == 123456.0
        assert fs.file_id_on_webui is None
    
    def test_file_state_with_id(self):
        fs = FileState(
            knowledge_id="kb1",
            name="note.md",
            mtime=123456.0,
            file_id_on_webui="file_123",
        )
        assert fs.file_id_on_webui == "file_123"


class TestSyncState:
    """Test SyncState data class"""
    
    def test_sync_state_creation(self):
        now = datetime.now(timezone.utc).isoformat()
        files = [
            FileState(knowledge_id="kb1", name="note1.md", mtime=100.0),
            FileState(
                knowledge_id="kb2",
                name="note2.md",
                mtime=200.0,
                file_id_on_webui="file_1",
            ),
        ]
        state = SyncState(last_sync=now, files=files)
        
        assert state.last_sync == now
        assert len(state.files) == 2
        assert state.files[0].name == "note1.md"
    
    def test_sync_state_to_dict(self):
        now = datetime.now(timezone.utc).isoformat()
        files = [FileState(knowledge_id="kb1", name="note1.md", mtime=100.0)]
        state = SyncState(last_sync=now, files=files)
        
        data = state.to_dict()
        assert data['last_sync'] == now
        assert len(data['files']) == 1
        assert data['files'][0]['knowledge_id'] == "kb1"
        assert data['files'][0]['name'] == "note1.md"
    
    def test_sync_state_from_dict(self):
        now = datetime.now(timezone.utc).isoformat()
        data = {
            'last_sync': now,
            'files': [
                {
                    'knowledge_id': 'kb1',
                    'name': 'note1.md',
                    'mtime': 100.0,
                    'file_id_on_webui': 'file_1',
                }
            ]
        }
        
        state = SyncState.from_dict(data)
        assert state.last_sync == now
        assert len(state.files) == 1
        assert state.files[0].knowledge_id == 'kb1'
        assert state.files[0].name == 'note1.md'
        assert state.files[0].file_id_on_webui == 'file_1'


class TestSyncResult:
    """Test SyncResult data class"""
    
    def test_sync_result_default(self):
        result = SyncResult()
        assert result.success_count == 0
        assert result.error_count == 0
        assert result.error_files == []
        assert result.duration_sec == 0.0
    
    def test_sync_result_with_values(self):
        result = SyncResult(
            success_count=5,
            error_count=2,
            error_files=['file1.md', 'file2.md'],
            duration_sec=10.5
        )
        assert result.success_count == 5
        assert result.error_count == 2
        assert len(result.error_files) == 2


class TestStateFilePersistence:
    """Test state file loading and saving"""
    
    def test_load_state_file_not_found(self):
        with patch('obsidian_ai_hub.sync_knowledge.STATE_FILE_PATH', Path('/nonexistent/path.json')):
            state = load_state_file()
            assert state.files == []
            assert state.last_sync is not None
    
    def test_save_and_load_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / 'state.json'
            
            with patch('obsidian_ai_hub.sync_knowledge.STATE_FILE_PATH', state_path):
                # Save state
                now = datetime.now(timezone.utc).isoformat()
                files = [
                    FileState(
                        knowledge_id="kb1",
                        name="note1.md",
                        mtime=100.0,
                        file_id_on_webui="file_1",
                    ),
                    FileState(
                        knowledge_id="kb2",
                        name="note2.md",
                        mtime=200.0,
                    ),
                ]
                original_state = SyncState(last_sync=now, files=files)
                
                assert save_state_file(original_state) is True
                assert state_path.exists()
                
                # Load state
                loaded_state = load_state_file()
                assert loaded_state.last_sync == now
                assert len(loaded_state.files) == 2
                assert loaded_state.files[0].knowledge_id == "kb1"
                assert loaded_state.files[0].name == "note1.md"
                assert loaded_state.files[0].file_id_on_webui == "file_1"


class TestChangeDetector:
    """Test change detection logic"""
    
    def test_detect_new_files(self):
        """Test detection of new files"""
        local_files = {
            "kb1": {
                "old_note.md": 100.0,
                "new_note.md": 200.0,
            }
        }
        
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[FileState(knowledge_id="kb1", name="old_note.md", mtime=100.0)]
        )
        
        detector = ChangeDetector()
        changes = detector.detect_changes(
            local_files, previous_state
        )
        
        assert "kb1" in changes
        assert "new_note.md" in changes["kb1"].new_files
        assert len(changes["kb1"].updated_files) == 0
        assert len(changes["kb1"].deleted_files) == 0
    
    def test_detect_updated_files(self):
        """Test detection of updated files"""
        old_mtime = 100.0
        new_mtime = 200.0
        
        local_files = {
            "kb1": {
                "note.md": new_mtime,
            }
        }
        
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[FileState(knowledge_id="kb1", name="note.md", mtime=old_mtime)]
        )
        
        detector = ChangeDetector()
        changes = detector.detect_changes(
            local_files, previous_state
        )
        
        assert len(changes["kb1"].new_files) == 0
        assert "note.md" in changes["kb1"].updated_files
        assert len(changes["kb1"].deleted_files) == 0
    
    def test_detect_deleted_files(self):
        """Test detection of deleted files"""
        local_files = {
            "kb1": {
                "existing.md": 100.0,
            }
        }
        
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[
                FileState(knowledge_id="kb1", name="existing.md", mtime=100.0),
                FileState(knowledge_id="kb1", name="deleted.md", mtime=100.0),
            ]
        )
        
        detector = ChangeDetector()
        changes = detector.detect_changes(
            local_files, previous_state
        )
        
        assert len(changes["kb1"].new_files) == 0
        assert len(changes["kb1"].updated_files) == 0
        assert "deleted.md" in changes["kb1"].deleted_files
    
    def test_detect_no_changes(self):
        """Test when there are no changes"""
        local_files = {
            "kb1": {
                "note.md": 50.0,
            }
        }
        
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[FileState(knowledge_id="kb1", name="note.md", mtime=50.0)]
        )
        
        detector = ChangeDetector()
        changes = detector.detect_changes(local_files, previous_state)

        assert changes == {}
    
    def test_detect_complex_changes(self):
        """Test detection with mixed changes"""
        local_files = {
            "kb1": {
                "existing_unchanged.md": 50.0,
                "existing_updated.md": 150.0,
                "new_file.md": 120.0,
            },
            "kb2": {
                "other.md": 10.0,
            }
        }
        
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[
                FileState(knowledge_id="kb1", name="existing_unchanged.md", mtime=50.0),
                FileState(knowledge_id="kb1", name="existing_updated.md", mtime=80.0),
                FileState(knowledge_id="kb1", name="deleted_file.md", mtime=80.0),
                FileState(knowledge_id="kb2", name="removed.md", mtime=10.0),
            ]
        )
        
        detector = ChangeDetector()
        changes = detector.detect_changes(local_files, previous_state)

        assert "new_file.md" in changes["kb1"].new_files
        assert "existing_updated.md" in changes["kb1"].updated_files
        assert "deleted_file.md" in changes["kb1"].deleted_files
        assert "removed.md" in changes["kb2"].deleted_files
        assert "existing_unchanged.md" not in changes["kb1"].new_files
        assert "existing_unchanged.md" not in changes["kb1"].updated_files
        assert "existing_unchanged.md" not in changes["kb1"].deleted_files


class TestLocalFileScanning:
    """Test local file scanning functionality"""
    
    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('obsidian_ai_hub.sync_knowledge.KNOWLEDGE_SYNC_FOLDER', Path(tmpdir)):
                files = scan_local_files()
                assert files == {}
    
    def test_scan_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            kb1 = tmppath / "kb1"
            kb1.mkdir()
            (kb1 / "note1.md").write_text("content1")
            (kb1 / "note2.md").write_text("content2")
            (kb1 / "ignore.txt").write_text("should not be scanned")

            nested = kb1 / "subfolder"
            nested.mkdir()
            (nested / "note3.md").write_text("content3")

            kb2 = tmppath / "kb2"
            kb2.mkdir()
            (kb2 / "other.md").write_text("content4")

            (tmppath / "root.md").write_text("should be ignored")
            
            with patch('obsidian_ai_hub.sync_knowledge.KNOWLEDGE_SYNC_FOLDER', tmppath):
                files = scan_local_files()
                
                assert set(files.keys()) == {"kb1", "kb2"}
                assert len(files["kb1"]) == 3
                assert "note1.md" in files["kb1"]
                assert "note2.md" in files["kb1"]
                assert "subfolder/note3.md" in files["kb1"]
                assert "ignore.txt" not in files["kb1"]
                assert len(files["kb2"]) == 1
                assert "other.md" in files["kb2"]
                assert "root.md" not in files.get("root", {})


class TestStateCreation:
    """Test state creation after applying changes"""

    def test_failed_new_file_is_not_tracked(self):
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[
                FileState(
                    knowledge_id="kb1",
                    name="existing.md",
                    mtime=100.0,
                    file_id_on_webui="file_1",
                )
            ]
        )

        new_state = create_new_state(
            local_files={
                "kb1": {
                    "existing.md": 100.0,
                    "new_failed.md": 200.0,
                }
            },
            previous_state=previous_state,
            successful_files={("kb1", "existing.md")},
            updated_file_ids={},
        )

        assert [f.name for f in new_state.files] == ["existing.md"]
        assert new_state.files[0].knowledge_id == "kb1"
        assert new_state.files[0].file_id_on_webui == "file_1"

    def test_failed_update_keeps_previous_state(self):
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[
                FileState(
                    knowledge_id="kb1",
                    name="note.md",
                    mtime=100.0,
                    file_id_on_webui="file_1",
                )
            ]
        )

        new_state = create_new_state(
            local_files={"kb1": {"note.md": 200.0}},
            previous_state=previous_state,
            successful_files=set(),
            updated_file_ids={},
        )

        assert len(new_state.files) == 1
        assert new_state.files[0].name == "note.md"
        assert new_state.files[0].knowledge_id == "kb1"
        assert new_state.files[0].mtime == 100.0
        assert new_state.files[0].file_id_on_webui == "file_1"


class TestMultipleKnowledgePartitioning:
    """Test that files are partitioned per knowledge_id."""

    def test_same_filename_in_different_knowledge_ids_isolated(self):
        local_files = {
            "kb1": {"shared.md": 100.0},
            "kb2": {"shared.md": 200.0},
        }
        previous_state = SyncState(
            last_sync=datetime.now(timezone.utc).isoformat(),
            files=[
                FileState(knowledge_id="kb1", name="shared.md", mtime=50.0),
                FileState(knowledge_id="kb2", name="shared.md", mtime=150.0),
            ],
        )

        changes = ChangeDetector().detect_changes(local_files, previous_state)

        assert "kb1" in changes
        assert "kb2" in changes
        assert changes["kb1"].updated_files == ["shared.md"]
        assert changes["kb2"].updated_files == ["shared.md"]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
