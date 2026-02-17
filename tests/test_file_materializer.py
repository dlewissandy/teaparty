import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from teaparty_app.models import Conversation, Workgroup
from teaparty_app.services.file_materializer import (
    MaterializedContext,
    materialized_files,
    read_files_from_directory,
    sync_directory_to_files,
)


def _make_workgroup(*, workgroup_id="wg-1", files=None, workspace_enabled=False):
    return Workgroup(
        id=workgroup_id, name="Test", owner_id="user-1",
        files=files or [], workspace_enabled=workspace_enabled,
    )


def _make_conversation(*, conversation_id="conv-1", kind="job"):
    return Conversation(
        id=conversation_id, workgroup_id="wg-1",
        created_by_user_id="user-1", kind=kind,
    )


class ReadFilesFromDirectoryTests(unittest.TestCase):
    """Tests for read_files_from_directory."""

    def test_read_files_from_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "hello.txt").write_text("hello world")
            Path(td, "sub").mkdir()
            Path(td, "sub", "main.py").write_text("print('hi')")

            result = read_files_from_directory(Path(td))

        paths = {f["path"] for f in result}
        self.assertIn("hello.txt", paths)
        self.assertIn(os.path.join("sub", "main.py"), paths)
        contents = {f["path"]: f["content"] for f in result}
        self.assertEqual(contents["hello.txt"], "hello world")
        self.assertEqual(contents[os.path.join("sub", "main.py")], "print('hi')")

    def test_read_files_skips_hidden_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "visible.txt").write_text("ok")
            Path(td, ".git").mkdir()
            Path(td, ".git", "config").write_text("hidden")
            Path(td, "__pycache__").mkdir()
            Path(td, "__pycache__", "cache.pyc").write_text("bytecode")

            result = read_files_from_directory(Path(td))

        paths = {f["path"] for f in result}
        self.assertEqual(paths, {"visible.txt"})


class MaterializedFilesLifecycleTests(unittest.TestCase):
    """Tests for the materialized_files context manager."""

    def _mock_session(self, workgroup):
        session = MagicMock()
        session.get.return_value = workgroup
        # No active worktree
        mock_exec_result = MagicMock()
        mock_exec_result.first.return_value = None
        session.exec.return_value = mock_exec_result
        return session

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_materialized_files_lifecycle(self, mock_activity) -> None:
        files = [
            {"id": "f1", "path": "readme.txt", "content": "Hello", "topic_id": ""},
        ]
        wg = _make_workgroup(files=files)
        conv = _make_conversation()
        session = self._mock_session(wg)

        dir_path = None
        with materialized_files(session, wg, conv) as mat_ctx:
            dir_path = mat_ctx.dir_path
            self.assertTrue(Path(dir_path).is_dir())
            self.assertTrue(Path(dir_path, "readme.txt").exists())
            self.assertEqual(Path(dir_path, "readme.txt").read_text(), "Hello")
            self.assertIsInstance(mat_ctx.settings_json, str)
            self.assertIn("f1", mat_ctx.original_file_ids.values())

        # Temp dir cleaned up
        self.assertFalse(Path(dir_path).exists())

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_materialized_files_cleanup_on_error(self, mock_activity) -> None:
        files = [
            {"id": "f1", "path": "readme.txt", "content": "Hello", "topic_id": ""},
        ]
        wg = _make_workgroup(files=files)
        conv = _make_conversation()
        session = self._mock_session(wg)

        dir_path = None
        with self.assertRaises(ValueError):
            with materialized_files(session, wg, conv) as mat_ctx:
                dir_path = mat_ctx.dir_path
                self.assertTrue(Path(dir_path).is_dir())
                raise ValueError("boom")

        self.assertFalse(Path(dir_path).exists())

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_settings_json_has_constrain_hook(self, mock_activity) -> None:
        wg = _make_workgroup(files=[
            {"id": "f1", "path": "a.txt", "content": "x", "topic_id": ""},
        ])
        conv = _make_conversation()
        session = self._mock_session(wg)

        with materialized_files(session, wg, conv) as mat_ctx:
            parsed = json.loads(mat_ctx.settings_json)
            self.assertIn("hooks", parsed)
            self.assertIn("PreToolUse", parsed["hooks"])
            matcher = parsed["hooks"]["PreToolUse"][0]["matcher"]
            self.assertIn("Edit", matcher)
            self.assertIn("Write", matcher)
            self.assertIn("Glob", matcher)
            self.assertIn("Grep", matcher)

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_conversation_scoping(self, mock_activity) -> None:
        """Job conversations see shared files + own-topic files, not other jobs' files."""
        files = [
            {"id": "f1", "path": "shared.txt", "content": "shared", "topic_id": ""},
            {"id": "f2", "path": "mine.txt", "content": "mine", "topic_id": "conv-1"},
            {"id": "f3", "path": "other.txt", "content": "other", "topic_id": "conv-other"},
        ]
        wg = _make_workgroup(files=files)
        conv = _make_conversation(conversation_id="conv-1", kind="job")
        session = self._mock_session(wg)

        with materialized_files(session, wg, conv) as mat_ctx:
            disk_files = {p.name for p in Path(mat_ctx.dir_path).rglob("*") if p.is_file()}
            self.assertIn("shared.txt", disk_files)
            self.assertIn("mine.txt", disk_files)
            self.assertNotIn("other.txt", disk_files)


class SyncDirectoryToFilesTests(unittest.TestCase):
    """Tests for sync_directory_to_files."""

    def _mock_session(self, workgroup):
        session = MagicMock()
        session.refresh = MagicMock()
        session.add = MagicMock()
        return session

    def test_sync_detects_modified_file(self) -> None:
        wg = _make_workgroup(files=[
            {"id": "f1", "path": "readme.txt", "content": "old content", "topic_id": ""},
        ])
        original_file_ids = {"readme.txt": "f1"}
        session = self._mock_session(wg)
        conv = _make_conversation()

        with tempfile.TemporaryDirectory() as td:
            Path(td, "readme.txt").write_text("new content")
            changes = sync_directory_to_files(session, wg, conv, td, original_file_ids)

        self.assertEqual(changes, [("modified", "readme.txt")])
        # Verify the file content was updated
        updated = [f for f in wg.files if f["id"] == "f1"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["content"], "new content")

    def test_sync_detects_new_file(self) -> None:
        wg = _make_workgroup(files=[
            {"id": "f1", "path": "readme.txt", "content": "hello", "topic_id": ""},
        ])
        original_file_ids = {"readme.txt": "f1"}
        session = self._mock_session(wg)
        conv = _make_conversation(kind="job")

        with tempfile.TemporaryDirectory() as td:
            Path(td, "readme.txt").write_text("hello")
            Path(td, "new_file.py").write_text("print(1)")
            changes = sync_directory_to_files(session, wg, conv, td, original_file_ids)

        self.assertEqual(changes, [("created", "new_file.py")])
        new_files = [f for f in wg.files if f["path"] == "new_file.py"]
        self.assertEqual(len(new_files), 1)
        self.assertEqual(new_files[0]["content"], "print(1)")
        # New file should have a UUID id
        self.assertTrue(len(new_files[0]["id"]) > 0)

    def test_sync_detects_deleted_file(self) -> None:
        wg = _make_workgroup(files=[
            {"id": "f1", "path": "readme.txt", "content": "hello", "topic_id": ""},
            {"id": "f2", "path": "delete_me.txt", "content": "bye", "topic_id": ""},
        ])
        original_file_ids = {"readme.txt": "f1", "delete_me.txt": "f2"}
        session = self._mock_session(wg)
        conv = _make_conversation()

        with tempfile.TemporaryDirectory() as td:
            # Only write readme, delete_me is gone
            Path(td, "readme.txt").write_text("hello")
            changes = sync_directory_to_files(session, wg, conv, td, original_file_ids)

        self.assertEqual(changes, [("deleted", "delete_me.txt")])
        remaining_paths = [f["path"] for f in wg.files]
        self.assertIn("readme.txt", remaining_paths)
        self.assertNotIn("delete_me.txt", remaining_paths)

    def test_new_file_topic_id_for_job(self) -> None:
        wg = _make_workgroup(files=[])
        original_file_ids = {}
        session = self._mock_session(wg)
        conv = _make_conversation(conversation_id="job-42", kind="job")

        with tempfile.TemporaryDirectory() as td:
            Path(td, "new.txt").write_text("data")
            sync_directory_to_files(session, wg, conv, td, original_file_ids)

        new_files = [f for f in wg.files if f["path"] == "new.txt"]
        self.assertEqual(len(new_files), 1)
        self.assertEqual(new_files[0]["topic_id"], "job-42")

    def test_new_file_topic_id_for_direct(self) -> None:
        wg = _make_workgroup(files=[])
        original_file_ids = {}
        session = self._mock_session(wg)
        conv = _make_conversation(conversation_id="dm-1", kind="direct")

        with tempfile.TemporaryDirectory() as td:
            Path(td, "new.txt").write_text("data")
            sync_directory_to_files(session, wg, conv, td, original_file_ids)

        new_files = [f for f in wg.files if f["path"] == "new.txt"]
        self.assertEqual(len(new_files), 1)
        self.assertEqual(new_files[0]["topic_id"], "")

    def test_existing_topic_id_preserved(self) -> None:
        wg = _make_workgroup(files=[
            {"id": "f1", "path": "readme.txt", "content": "old", "topic_id": "original-topic"},
        ])
        original_file_ids = {"readme.txt": "f1"}
        session = self._mock_session(wg)
        conv = _make_conversation(kind="job")

        with tempfile.TemporaryDirectory() as td:
            Path(td, "readme.txt").write_text("updated")
            sync_directory_to_files(session, wg, conv, td, original_file_ids)

        updated = [f for f in wg.files if f["id"] == "f1"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["topic_id"], "original-topic")


if __name__ == "__main__":
    unittest.main()
