#!/usr/bin/env python3
"""Tests for issue #91: Wire track_reinforcement.py into extract_learnings().

Covers:
 1. retrieve() in memory_indexer.py writes retrieved entry IDs to a sidecar
    file when ids_output_path is provided.
 2. extract_learnings() calls reinforcement tracking as part of its pipeline.
 3. After a full session, entries that were retrieved at session start have
    their reinforcement_count incremented.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_memory_entry_text(
    entry_id: str = 'test-id-001',
    content: str = 'Test learning about distributed systems',
    importance: float = 0.7,
    reinforcement_count: int = 0,
) -> str:
    """Create a YAML-frontmatter memory entry string."""
    today = date.today().isoformat()
    return (
        f'---\n'
        f'id: {entry_id}\n'
        f'type: procedural\n'
        f'domain: team\n'
        f'importance: {importance}\n'
        f'phase: unknown\n'
        f'status: active\n'
        f'reinforcement_count: {reinforcement_count}\n'
        f"last_reinforced: '{today}'\n"
        f"created_at: '{today}'\n"
        f'---\n'
        f'{content}'
    )


def _make_indexed_db(db_path: str, source_path: str) -> None:
    """Create a SQLite FTS5 database with one indexed source file."""
    from projects.POC.scripts.memory_indexer import open_db, index_file
    conn = open_db(db_path)
    index_file(conn, source_path)
    conn.close()


def _write(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)


# ── Tests: retrieve() writes IDs ─────────────────────────────────────────────

class TestRetrieveWritesEntryIds(unittest.TestCase):
    """memory_indexer.retrieve() saves retrieved entry IDs to a sidecar file."""

    def test_retrieve_writes_ids_to_output_path(self):
        """When ids_output_path is provided, retrieve() writes matched entry IDs."""
        with tempfile.TemporaryDirectory() as td:
            # Create a memory file with a known entry ID
            tasks_dir = os.path.join(td, 'tasks')
            os.makedirs(tasks_dir)
            entry_text = _make_memory_entry_text(
                entry_id='abc-123',
                content='Distributed consensus algorithms require leader election',
            )
            task_file = os.path.join(tasks_dir, 'learning.md')
            _write(task_file, entry_text)

            db_path = os.path.join(td, '.memory.db')
            _make_indexed_db(db_path, task_file)

            ids_path = os.path.join(td, '.retrieved-ids.txt')

            from projects.POC.scripts.memory_indexer import retrieve

            # Mock build_retrieval_query to avoid calling claude
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='distributed consensus leader election'):
                result = retrieve(
                    task='Research distributed consensus',
                    db_path=db_path,
                    source_paths=[tasks_dir],
                    top_k=5,
                    ids_output_path=ids_path,
                )

            # IDs file should exist with our entry ID
            self.assertTrue(os.path.exists(ids_path), 'ids_output_path file was not created')
            ids_content = Path(ids_path).read_text()
            self.assertIn('abc-123', ids_content)

    def test_retrieve_no_ids_file_when_param_omitted(self):
        """When ids_output_path is not provided, no sidecar file is created."""
        with tempfile.TemporaryDirectory() as td:
            tasks_dir = os.path.join(td, 'tasks')
            os.makedirs(tasks_dir)
            entry_text = _make_memory_entry_text(entry_id='xyz-789')
            _write(os.path.join(tasks_dir, 'learning.md'), entry_text)

            db_path = os.path.join(td, '.memory.db')
            _make_indexed_db(db_path, os.path.join(tasks_dir, 'learning.md'))

            ids_path = os.path.join(td, '.retrieved-ids.txt')

            from projects.POC.scripts.memory_indexer import retrieve
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='test query'):
                retrieve(
                    task='Some task',
                    db_path=db_path,
                    source_paths=[tasks_dir],
                    top_k=5,
                )

            self.assertFalse(os.path.exists(ids_path))


# ── Tests: extract_learnings runs reinforcement ──────────────────────────────

class TestExtractLearningsRunsReinforcement(unittest.TestCase):
    """extract_learnings() calls reinforcement tracking at session end."""

    def test_reinforcement_scope_in_extract_learnings(self):
        """extract_learnings() includes a 'reinforcement' scope that runs."""
        with tempfile.TemporaryDirectory() as td:
            infra_dir = os.path.join(td, 'infra')
            project_dir = os.path.join(td, 'project')
            os.makedirs(infra_dir)
            os.makedirs(project_dir)

            # Create stream files so other scopes don't error on missing files
            _write(os.path.join(infra_dir, '.intent-stream.jsonl'), '')
            _write(os.path.join(infra_dir, '.exec-stream.jsonl'), '')

            # Create a retrieved IDs file (as session._retrieve_memory would)
            ids_path = os.path.join(infra_dir, '.retrieved-ids.txt')
            _write(ids_path, 'entry-001\nentry-002\n')

            # Create a memory file with matching entries
            tasks_dir = os.path.join(project_dir, 'tasks')
            os.makedirs(tasks_dir)
            entry1 = _make_memory_entry_text(
                entry_id='entry-001',
                content='Learning one',
                reinforcement_count=0,
            )
            entry2 = _make_memory_entry_text(
                entry_id='entry-002',
                content='Learning two',
                reinforcement_count=3,
            )
            _write(os.path.join(tasks_dir, 'a.md'), entry1)
            _write(os.path.join(tasks_dir, 'b.md'), entry2)

            from projects.POC.orchestrator.learnings import extract_learnings

            # Mock all the other learning scopes to avoid subprocess calls
            with patch('projects.POC.orchestrator.learnings._run_summarize'), \
                 patch('projects.POC.orchestrator.learnings._call_promote'):
                _run(extract_learnings(
                    infra_dir=infra_dir,
                    project_dir=project_dir,
                    session_worktree=td,
                    task='test task',
                    poc_root=td,
                ))

            # Verify reinforcement_count was incremented
            from projects.POC.scripts.memory_entry import parse_memory_file
            text1 = Path(os.path.join(tasks_dir, 'a.md')).read_text()
            entries1 = parse_memory_file(text1)
            self.assertEqual(len(entries1), 1)
            self.assertEqual(entries1[0].reinforcement_count, 1,
                             'entry-001 should have reinforcement_count=1')

            text2 = Path(os.path.join(tasks_dir, 'b.md')).read_text()
            entries2 = parse_memory_file(text2)
            self.assertEqual(len(entries2), 1)
            self.assertEqual(entries2[0].reinforcement_count, 4,
                             'entry-002 should have reinforcement_count=4 (was 3)')

    def test_no_ids_file_reinforcement_is_noop(self):
        """When no .retrieved-ids.txt exists, reinforcement silently skips."""
        with tempfile.TemporaryDirectory() as td:
            infra_dir = os.path.join(td, 'infra')
            project_dir = os.path.join(td, 'project')
            os.makedirs(infra_dir)
            os.makedirs(project_dir)

            _write(os.path.join(infra_dir, '.intent-stream.jsonl'), '')
            _write(os.path.join(infra_dir, '.exec-stream.jsonl'), '')

            # Create a memory file — should NOT be modified
            tasks_dir = os.path.join(project_dir, 'tasks')
            os.makedirs(tasks_dir)
            original = _make_memory_entry_text(
                entry_id='entry-999',
                content='Should not change',
                reinforcement_count=5,
            )
            task_file = os.path.join(tasks_dir, 'c.md')
            _write(task_file, original)

            from projects.POC.orchestrator.learnings import extract_learnings

            with patch('projects.POC.orchestrator.learnings._run_summarize'), \
                 patch('projects.POC.orchestrator.learnings._call_promote'):
                _run(extract_learnings(
                    infra_dir=infra_dir,
                    project_dir=project_dir,
                    session_worktree=td,
                    task='test task',
                    poc_root=td,
                ))

            # reinforcement_count should be unchanged
            from projects.POC.scripts.memory_entry import parse_memory_file
            text = Path(task_file).read_text()
            entries = parse_memory_file(text)
            self.assertEqual(entries[0].reinforcement_count, 5)


if __name__ == '__main__':
    unittest.main()
