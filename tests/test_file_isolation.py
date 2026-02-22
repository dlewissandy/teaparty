"""Tests for file isolation between Jobs, Engagements, and Workgroups."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Conversation,
    Engagement,
    Job,
    Membership,
    Organization,
    User,
    Workgroup,
)
from teaparty_app.services.file_helpers import (
    _files_for_conversation,
    _normalize_entity_files,
    _shared_workgroup_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id="u-1"):
    return User(id=user_id, email=f"{user_id}@test.com", name="Test User")


def _make_workgroup(wg_id="wg-1", files=None, owner_id="u-1"):
    return Workgroup(id=wg_id, name="Test WG", owner_id=owner_id, files=files or [])


def _make_conversation(conv_id="conv-1", wg_id="wg-1", kind="job"):
    return Conversation(
        id=conv_id, workgroup_id=wg_id,
        created_by_user_id="u-1", kind=kind,
    )


def _make_job(job_id="job-1", wg_id="wg-1", conv_id="conv-1", files=None, engagement_id=None):
    return Job(
        id=job_id, title="Test Job", workgroup_id=wg_id,
        conversation_id=conv_id, files=files or [],
        engagement_id=engagement_id,
    )


def _make_engagement(eng_id="eng-1", source_wg="wg-1", target_wg="wg-2", files=None):
    return Engagement(
        id=eng_id, title="Test Engagement",
        source_workgroup_id=source_wg, target_workgroup_id=target_wg,
        proposed_by_user_id="u-1", files=files or [],
    )


# ---------------------------------------------------------------------------
# File Isolation Tests
# ---------------------------------------------------------------------------

class FileIsolationTests(unittest.TestCase):
    """Test that files don't leak between entities."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(cls.engine)

    def setUp(self):
        with Session(self.engine) as session:
            # Clean tables between tests
            for model in [Job, Engagement, Conversation, Membership, Workgroup, User]:
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.commit()

    def test_job_files_not_visible_in_workgroup(self):
        """Job.files should be separate from workgroup.files."""
        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[
                {"id": "wg-f1", "path": "shared.txt", "content": "shared", "topic_id": ""},
            ])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-j1", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-1", wg_id=wg.id, conv_id=conv.id,
                files=[{"id": "job-f1", "path": "job_only.txt", "content": "job data"}],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            wg_paths = [f["path"] for f in wg.files if isinstance(f, dict)]
            self.assertNotIn("job_only.txt", wg_paths)
            self.assertIn("shared.txt", wg_paths)

    def test_engagement_files_not_visible_in_workgroup(self):
        """Engagement.files should be separate from workgroup.files."""
        with Session(self.engine) as session:
            user = _make_user()
            wg_src = _make_workgroup(wg_id="wg-src", files=[
                {"id": "wg-f1", "path": "team.md", "content": "team file", "topic_id": ""},
            ])
            wg_tgt = _make_workgroup(wg_id="wg-tgt", files=[])
            session.add_all([user, wg_src, wg_tgt])
            session.flush()

            eng = _make_engagement(
                eng_id="eng-1", source_wg="wg-src", target_wg="wg-tgt",
                files=[{"id": "eng-f1", "path": "agreement.md", "content": "terms"}],
            )
            session.add(eng)
            session.commit()

            session.refresh(wg_src)
            wg_paths = [f["path"] for f in wg_src.files if isinstance(f, dict)]
            self.assertNotIn("agreement.md", wg_paths)
            self.assertIn("team.md", wg_paths)

    def test_job_files_visible_in_job_conversation(self):
        """Job files should appear when calling _files_for_conversation for a job conversation."""
        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-j1", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-1", wg_id=wg.id, conv_id=conv.id,
                files=[
                    {"id": "jf1", "path": "main.py", "content": "print('hi')"},
                    {"id": "jf2", "path": "readme.md", "content": "# Read me"},
                ],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            result = _files_for_conversation(wg, conv, session=session)
            paths = [f["path"] for f in result]
            self.assertIn("main.py", paths)
            self.assertIn("readme.md", paths)

    def test_shared_workgroup_files_visible_in_job_conversation(self):
        """Shared workgroup files (no topic_id) appear alongside job files."""
        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[
                {"id": "wf1", "path": "CLAUDE.md", "content": "# Rules", "topic_id": ""},
                {"id": "wf2", "path": "workflows.yaml", "content": "steps:", "topic_id": ""},
            ])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-j2", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-2", wg_id=wg.id, conv_id=conv.id,
                files=[{"id": "jf1", "path": "app.py", "content": "import os"}],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            result = _files_for_conversation(wg, conv, session=session)
            paths = [f["path"] for f in result]
            self.assertIn("app.py", paths)
            self.assertIn("CLAUDE.md", paths)
            self.assertIn("workflows.yaml", paths)

    def test_other_job_files_not_visible(self):
        """One job's conversation must not see another job's files."""
        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[])
            session.add_all([user, wg])
            session.flush()

            conv_a = _make_conversation(conv_id="conv-a", wg_id=wg.id, kind="job")
            conv_b = _make_conversation(conv_id="conv-b", wg_id=wg.id, kind="job")
            session.add_all([conv_a, conv_b])
            session.flush()

            job_a = _make_job(
                job_id="job-a", wg_id=wg.id, conv_id=conv_a.id,
                files=[{"id": "af1", "path": "a_file.py", "content": "a"}],
            )
            job_b = _make_job(
                job_id="job-b", wg_id=wg.id, conv_id=conv_b.id,
                files=[{"id": "bf1", "path": "b_file.py", "content": "b"}],
            )
            session.add_all([job_a, job_b])
            session.commit()

            session.refresh(wg)
            result_a = _files_for_conversation(wg, conv_a, session=session)
            paths_a = [f["path"] for f in result_a]
            self.assertIn("a_file.py", paths_a)
            self.assertNotIn("b_file.py", paths_a)

            result_b = _files_for_conversation(wg, conv_b, session=session)
            paths_b = [f["path"] for f in result_b]
            self.assertIn("b_file.py", paths_b)
            self.assertNotIn("a_file.py", paths_b)


# ---------------------------------------------------------------------------
# Engagement File Lifecycle Tests
# ---------------------------------------------------------------------------

class EngagementFileLifecycleTests(unittest.TestCase):
    """Test engagement file creation, update, and fork to job."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(cls.engine)

    def setUp(self):
        with Session(self.engine) as session:
            for model in [AgentWorkgroup, Agent, Job, Engagement, Conversation, Membership, Organization, Workgroup, User]:
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.commit()

    def _seed(self, session):
        user = _make_user()
        wg_src = _make_workgroup(wg_id="wg-src", owner_id=user.id)
        wg_tgt = _make_workgroup(wg_id="wg-tgt", owner_id=user.id)
        session.add_all([user, wg_src, wg_tgt])
        session.flush()

        eng = _make_engagement(eng_id="eng-1", source_wg="wg-src", target_wg="wg-tgt")
        eng.status = "in_progress"
        session.add(eng)
        session.flush()
        return user, wg_src, wg_tgt, eng

    def test_create_engagement_files_writes_to_entity(self):
        """create_engagement_files writes to Engagement.files, not workgroup.files."""
        from teaparty_app.services.engagement_files import create_engagement_files

        with Session(self.engine) as session:
            user, wg_src, wg_tgt, eng = self._seed(session)
            session.commit()

            session.refresh(wg_src)
            session.refresh(wg_tgt)
            session.refresh(eng)
            create_engagement_files(session, eng, wg_src, wg_tgt)
            session.commit()

            session.refresh(eng)
            session.refresh(wg_src)
            session.refresh(wg_tgt)

            eng_paths = [f["path"] for f in eng.files if isinstance(f, dict)]
            self.assertIn("agreement.md", eng_paths)
            self.assertIn("deliverables.md", eng_paths)

            # Workgroup files must be unaffected
            self.assertEqual(wg_src.files, [])
            self.assertEqual(wg_tgt.files, [])

    def test_update_engagement_files_updates_entity(self):
        """update_engagement_files modifies Engagement.files."""
        from teaparty_app.services.engagement_files import (
            create_engagement_files,
            update_engagement_files,
        )

        with Session(self.engine) as session:
            user, wg_src, wg_tgt, eng = self._seed(session)
            session.commit()

            session.refresh(wg_src)
            session.refresh(wg_tgt)
            session.refresh(eng)
            create_engagement_files(session, eng, wg_src, wg_tgt)
            session.commit()

            eng.status = "completed"
            session.add(eng)
            session.commit()

            session.refresh(eng)
            session.refresh(wg_src)
            session.refresh(wg_tgt)
            update_engagement_files(session, eng, wg_src, wg_tgt, "Completed", "All done")
            session.commit()

            session.refresh(eng)
            agreement = next(
                (f for f in eng.files if isinstance(f, dict) and f["path"] == "agreement.md"),
                None,
            )
            self.assertIsNotNone(agreement)
            self.assertIn("completed", agreement["content"])

            deliverables = next(
                (f for f in eng.files if isinstance(f, dict) and f["path"] == "deliverables.md"),
                None,
            )
            self.assertIsNotNone(deliverables)
            self.assertIn("Completed", deliverables["content"])
            self.assertIn("All done", deliverables["content"])

            # Workgroups still clean
            session.refresh(wg_src)
            session.refresh(wg_tgt)
            self.assertEqual(wg_src.files, [])
            self.assertEqual(wg_tgt.files, [])

    def test_engagement_files_forked_to_job(self):
        """create_engagement_job copies engagement files into Job.files under engagement/ prefix."""
        with Session(self.engine) as session:
            user = _make_user()
            org = Organization(
                id="org-1", name="Test Org", owner_id=user.id,
            )
            wg_ops = _make_workgroup(wg_id="wg-ops", owner_id=user.id)
            wg_ops.organization_id = "org-1"
            wg_dev = Workgroup(
                id="wg-dev", name="Dev Team", owner_id=user.id,
                organization_id="org-1", files=[],
            )
            session.add_all([user, org, wg_ops, wg_dev])
            session.flush()

            # Create an agent in the ops workgroup (the coordinator)
            from teaparty_app.services.agent_workgroups import link_agent
            agent = Agent(
                id="agent-coord", organization_id="org-1",
                created_by_user_id=user.id, name="Coordinator",
            )
            session.add(agent)
            session.flush()
            link_agent(session, agent.id, "wg-ops")

            eng = _make_engagement(
                eng_id="eng-fork", source_wg="wg-ops", target_wg="wg-dev",
                files=[
                    {"id": "ef1", "path": "agreement.md", "content": "# Agreement"},
                    {"id": "ef2", "path": "deliverables.md", "content": "# Deliverables"},
                ],
            )
            eng.status = "in_progress"
            session.add(eng)
            session.commit()

            # Use orchestration to create the job
            from teaparty_app.services.orchestration import create_engagement_job
            with patch("teaparty_app.services.agent_runtime._process_auto_responses_in_background"):
                result = create_engagement_job(
                    session,
                    agent_id="agent-coord",
                    team_name="Dev Team",
                    title="Build widget",
                    scope="Frontend work",
                    engagement_id="eng-fork",
                )

            self.assertNotIn("error", result)
            job_id = result["job_id"]
            job = session.get(Job, job_id)
            self.assertIsNotNone(job)

            job_paths = [f["path"] for f in job.files if isinstance(f, dict)]
            self.assertIn("engagement/agreement.md", job_paths)
            self.assertIn("engagement/deliverables.md", job_paths)

            # Verify content was copied
            agreement = next(f for f in job.files if f["path"] == "engagement/agreement.md")
            self.assertEqual(agreement["content"], "# Agreement")


# ---------------------------------------------------------------------------
# Entity Materialization Tests
# ---------------------------------------------------------------------------

class EntityMaterializationTests(unittest.TestCase):
    """Test that materialization routes sync-back correctly."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(cls.engine)

    def setUp(self):
        with Session(self.engine) as session:
            for model in [Job, Engagement, Conversation, Workgroup, User]:
                for row in session.exec(select(model)).all():
                    session.delete(row)
            session.commit()

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_job_materialization_sets_sync_target(self, mock_activity):
        """materialized_files sets ctx.sync_target == 'job' for job conversations."""
        from teaparty_app.services.file_materializer import materialized_files

        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[
                {"id": "wf1", "path": "shared.md", "content": "shared", "topic_id": ""},
            ])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-m1", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-m1", wg_id=wg.id, conv_id=conv.id,
                files=[{"id": "jf1", "path": "app.py", "content": "code"}],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            with materialized_files(session, wg, conv) as ctx:
                self.assertEqual(ctx.sync_target, "job")
                self.assertEqual(ctx.sync_entity_id, "job-m1")

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_shared_files_are_readonly_in_job_context(self, mock_activity):
        """Shared workgroup files should be in ctx.readonly_file_ids for job conversations."""
        from teaparty_app.services.file_materializer import materialized_files

        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[
                {"id": "wf1", "path": "CLAUDE.md", "content": "# Rules", "topic_id": ""},
                {"id": "wf2", "path": "workflows.yaml", "content": "steps:", "topic_id": ""},
            ])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-m2", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-m2", wg_id=wg.id, conv_id=conv.id,
                files=[{"id": "jf1", "path": "main.py", "content": "code"}],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            with materialized_files(session, wg, conv) as ctx:
                self.assertIn("CLAUDE.md", ctx.readonly_file_ids)
                self.assertIn("workflows.yaml", ctx.readonly_file_ids)
                # Job files should NOT be read-only
                self.assertNotIn("main.py", ctx.readonly_file_ids)

    @patch("teaparty_app.services.file_materializer.post_file_change_activity")
    def test_new_files_sync_to_job_not_workgroup(self, mock_activity):
        """New files written during a job materialization sync to Job.files, not workgroup.files."""
        from teaparty_app.services.file_materializer import materialized_files

        with Session(self.engine) as session:
            user = _make_user()
            wg = _make_workgroup(files=[
                {"id": "wf1", "path": "shared.md", "content": "shared", "topic_id": ""},
            ])
            session.add_all([user, wg])
            session.flush()

            conv = _make_conversation(conv_id="conv-m3", wg_id=wg.id, kind="job")
            session.add(conv)
            session.flush()

            job = _make_job(
                job_id="job-m3", wg_id=wg.id, conv_id=conv.id,
                files=[{"id": "jf1", "path": "existing.py", "content": "old"}],
            )
            session.add(job)
            session.commit()

            session.refresh(wg)
            with materialized_files(session, wg, conv) as ctx:
                # Write a new file on disk during materialization
                new_path = Path(ctx.dir_path) / "new_output.txt"
                new_path.write_text("generated result")

            # Flush so the sync-back changes are persisted before refresh
            session.flush()

            # After context manager exits, sync-back should have written to job
            session.refresh(job)
            job_paths = [f["path"] for f in job.files if isinstance(f, dict)]
            self.assertIn("new_output.txt", job_paths)

            # Workgroup should NOT have the new file
            session.refresh(wg)
            wg_paths = [f["path"] for f in wg.files if isinstance(f, dict)]
            self.assertNotIn("new_output.txt", wg_paths)


if __name__ == "__main__":
    unittest.main()
