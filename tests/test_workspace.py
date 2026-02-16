"""Tests for workspace manager: init, worktree, merge, sync, path traversal."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import Conversation, Workspace, WorkspaceWorktree, Workgroup, new_id, utc_now


def _make_engine(tmp_path: str):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, echo=False)
    SQLModel.metadata.create_all(engine)
    return engine


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@unittest.skipUnless(_git_available(), "git not available")
class TestWorkspaceManager(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp()
        self.workspace_root = os.path.join(self.tmpdir, "workspaces")
        self.db_path = os.path.join(self.tmpdir, "db")
        os.makedirs(self.db_path, exist_ok=True)
        self.engine = _make_engine(self.db_path)

        # Patch settings.workspace_root
        self.settings_patcher = patch(
            "teaparty_app.services.workspace_manager.settings"
        )
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.workspace_root = self.workspace_root

        # Set up git user config for commits
        os.environ["GIT_AUTHOR_NAME"] = "Test User"
        os.environ["GIT_AUTHOR_EMAIL"] = "test@test.com"
        os.environ["GIT_COMMITTER_NAME"] = "Test User"
        os.environ["GIT_COMMITTER_EMAIL"] = "test@test.com"

    def tearDown(self):
        self.settings_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _session(self) -> Session:
        return Session(self.engine)

    def _create_workgroup(self, session: Session, files: list | None = None) -> Workgroup:
        wg = Workgroup(
            id=new_id(),
            name="Test Workgroup",
            files=files or [],
            owner_id="user-1",
        )
        session.add(wg)
        session.flush()
        return wg

    def _create_conversation(self, session: Session, workgroup_id: str, topic: str = "feature-x") -> Conversation:
        conv = Conversation(
            id=new_id(),
            workgroup_id=workgroup_id,
            created_by_user_id="user-1",
            kind="job",
            topic=topic,
            name=topic,
        )
        session.add(conv)
        session.flush()
        return conv

    def test_init_workspace_creates_repo_and_worktree(self):
        from teaparty_app.services.workspace_manager import init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session, files=[{"path": "hello.txt", "content": "hello world"}])
            ws = init_workspace(session, wg.id)
            session.commit()

            self.assertEqual(ws.status, "active")
            self.assertTrue(Path(ws.repo_path).exists())
            self.assertTrue(Path(ws.main_worktree_path).exists())
            # File should be written to disk
            hello_path = Path(ws.main_worktree_path) / "hello.txt"
            self.assertTrue(hello_path.exists())
            self.assertEqual(hello_path.read_text(), "hello world")

    def test_init_workspace_idempotent(self):
        from teaparty_app.services.workspace_manager import init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws1 = init_workspace(session, wg.id)
            session.commit()

            ws2 = init_workspace(session, wg.id)
            self.assertEqual(ws1.id, ws2.id)

    def test_create_worktree_for_job(self):
        from teaparty_app.services.workspace_manager import create_worktree_for_job, init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws = init_workspace(session, wg.id)
            conv = self._create_conversation(session, wg.id)
            wt = create_worktree_for_job(session, ws, conv)
            session.commit()

            self.assertEqual(wt.status, "active")
            self.assertTrue(Path(wt.worktree_path).exists())
            self.assertIn("job/", wt.branch_name)

    def test_create_worktree_idempotent(self):
        from teaparty_app.services.workspace_manager import create_worktree_for_job, init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws = init_workspace(session, wg.id)
            conv = self._create_conversation(session, wg.id)
            wt1 = create_worktree_for_job(session, ws, conv)
            session.commit()

            wt2 = create_worktree_for_job(session, ws, conv)
            self.assertEqual(wt1.id, wt2.id)

    def test_remove_worktree(self):
        from teaparty_app.services.workspace_manager import (
            create_worktree_for_job,
            init_workspace,
            remove_worktree,
        )

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws = init_workspace(session, wg.id)
            conv = self._create_conversation(session, wg.id)
            wt = create_worktree_for_job(session, ws, conv)
            session.commit()

            wt_path = wt.worktree_path
            remove_worktree(session, wt, delete_branch=False)
            session.commit()

            session.refresh(wt)
            self.assertEqual(wt.status, "removed")
            self.assertFalse(Path(wt_path).exists())

    def test_merge_success(self):
        from teaparty_app.services.workspace_manager import (
            create_worktree_for_job,
            init_workspace,
            merge_job_to_main,
        )

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws = init_workspace(session, wg.id)
            conv = self._create_conversation(session, wg.id)
            wt = create_worktree_for_job(session, ws, conv)
            session.commit()

            # Make a change on the job branch
            job_file = Path(wt.worktree_path) / "feature.txt"
            job_file.write_text("new feature")
            subprocess.run(["git", "add", "-A"], cwd=wt.worktree_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Add feature"],
                cwd=wt.worktree_path,
                check=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@test.com",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@test.com",
                },
            )

            result = merge_job_to_main(session, ws, wt)
            session.commit()

            self.assertTrue(result["merged"])
            self.assertEqual(result["conflicts"], [])

            # File should exist on main now
            main_file = Path(ws.main_worktree_path) / "feature.txt"
            self.assertTrue(main_file.exists())
            self.assertEqual(main_file.read_text(), "new feature")

    def test_merge_conflict_aborts(self):
        from teaparty_app.services.workspace_manager import (
            create_worktree_for_job,
            init_workspace,
            merge_job_to_main,
        )

        with self._session() as session:
            wg = self._create_workgroup(session, files=[{"path": "conflict.txt", "content": "original"}])
            ws = init_workspace(session, wg.id)
            conv = self._create_conversation(session, wg.id)
            wt = create_worktree_for_job(session, ws, conv)
            session.commit()

            git_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
            }

            # Change on job branch
            (Path(wt.worktree_path) / "conflict.txt").write_text("job change")
            subprocess.run(["git", "add", "-A"], cwd=wt.worktree_path, check=True)
            subprocess.run(["git", "commit", "-m", "Job change"], cwd=wt.worktree_path, check=True, env=git_env)

            # Conflicting change on main
            (Path(ws.main_worktree_path) / "conflict.txt").write_text("main change")
            subprocess.run(["git", "add", "-A"], cwd=ws.main_worktree_path, check=True)
            subprocess.run(["git", "commit", "-m", "Main change"], cwd=ws.main_worktree_path, check=True, env=git_env)

            result = merge_job_to_main(session, ws, wt)

            self.assertFalse(result["merged"])
            self.assertIn("conflict.txt", result["conflicts"])

    def test_destroy_workspace(self):
        from teaparty_app.services.workspace_manager import destroy_workspace, init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session)
            ws = init_workspace(session, wg.id)
            session.commit()

            repo_path = ws.repo_path
            destroy_workspace(session, ws)
            session.commit()

            self.assertFalse(Path(repo_path).parent.exists())
            remaining = session.exec(select(Workspace).where(Workspace.workgroup_id == wg.id)).first()
            self.assertIsNone(remaining)

    def test_path_traversal_blocked(self):
        from teaparty_app.services.workspace_manager import _write_files_to_worktree

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            count = _write_files_to_worktree(tmpdir, [{"path": "../../../etc/evil.txt", "content": "pwned"}])
            self.assertEqual(count, 0)
            # Make sure it didn't write outside
            self.assertFalse(Path(tmpdir).parent.joinpath("etc/evil.txt").exists())

    def test_file_sync_round_trip(self):
        from teaparty_app.services.workspace_manager import init_workspace
        from teaparty_app.services.workspace_sync import sync_db_to_filesystem, sync_filesystem_to_db

        with self._session() as session:
            wg = self._create_workgroup(session, files=[
                {"id": "f1", "path": "readme.md", "content": "# Hello"},
                {"id": "f2", "path": "src/main.py", "content": "print('hi')"},
            ])
            ws = init_workspace(session, wg.id)
            session.commit()

            # Sync DB -> filesystem
            result = sync_db_to_filesystem(session, ws)
            session.commit()
            self.assertGreater(result["files_written"], 0)

            # Modify a file on disk
            readme = Path(ws.main_worktree_path) / "readme.md"
            readme.write_text("# Updated")
            subprocess.run(["git", "add", "-A"], cwd=ws.main_worktree_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Update readme"],
                cwd=ws.main_worktree_path,
                check=True,
                env={
                    **os.environ,
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@test.com",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@test.com",
                },
            )

            # Sync filesystem -> DB
            result = sync_filesystem_to_db(session, ws)
            session.commit()
            self.assertGreater(result["files_read"], 0)

            # Check the DB was updated
            session.refresh(wg)
            paths = {f["path"] for f in wg.files}
            self.assertIn("readme.md", paths)
            for f in wg.files:
                if f["path"] == "readme.md":
                    self.assertEqual(f["content"], "# Updated")
                    self.assertEqual(f["id"], "f1")  # ID preserved

    def test_workspace_root_not_configured(self):
        from teaparty_app.services.workspace_manager import workspace_root_configured

        self.mock_settings.workspace_root = ""
        self.assertFalse(workspace_root_configured())

    def test_git_log(self):
        from teaparty_app.services.workspace_manager import get_git_log, init_workspace

        with self._session() as session:
            wg = self._create_workgroup(session, files=[{"path": "test.txt", "content": "test"}])
            ws = init_workspace(session, wg.id)
            session.commit()

            entries = get_git_log(ws, limit=5)
            self.assertGreater(len(entries), 0)
            self.assertIn("commit_hash", entries[0])
            self.assertIn("message", entries[0])


if __name__ == "__main__":
    unittest.main()
