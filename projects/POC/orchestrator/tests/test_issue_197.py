#!/usr/bin/env python3
"""Failing tests (TDD) for issue #197: Type-aware retrieval budget allocation.

The learning system stores three categories with different retrieval semantics:
  - Institutional — always loaded at matching scope (like CLAUDE.md)
  - Task-based — fuzzy-retrieved against current task context
  - Proxy — preferential always loaded, task-based fuzzy-retrieved

But retrieve() treats all memories identically: no type filtering, no budget
allocation per type.  These tests verify the fix.

Test strategy:
  1. retrieve() accepts a learning_type parameter for type filtering
  2. retrieve() accepts a max_chars parameter for budget caps
  3. Source path classification determines learning type
  4. Session callers no longer pass institutional.md to retrieve()
     (it is already loaded as a raw file read)
"""
import inspect
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.memory_indexer import (
    open_db, index_file,
)


def _make_entry(entry_id, content, importance=0.7):
    """Build a YAML-frontmattered memory entry string."""
    return (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: declarative\n"
        f"domain: task\n"
        f"importance: {importance}\n"
        f"phase: implementation\n"
        f"status: active\n"
        f"reinforcement_count: 2\n"
        f"last_reinforced: '2026-03-20'\n"
        f"created_at: '2026-03-01'\n"
        f"---\n"
        f"{content}\n"
    )


def _make_indexed_db(tmpdir, files):
    """Create a SQLite DB and index a dict of {relative_path: content}.

    Returns (db_path, {relative_path: absolute_path}).
    """
    db_path = os.path.join(tmpdir, '.memory.db')
    conn = open_db(db_path)
    abs_paths = {}
    for rel_path, content in files.items():
        abs_path = os.path.join(tmpdir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        Path(abs_path).write_text(content)
        index_file(conn, abs_path)
        abs_paths[rel_path] = abs_path
    conn.close()
    return db_path, abs_paths


# ── 1. retrieve() accepts learning_type parameter ────────────────────────────

class TestRetrieveLearningTypeParameter(unittest.TestCase):
    """retrieve() must accept an optional learning_type parameter."""

    def test_learning_type_in_signature(self):
        """retrieve() must accept a learning_type parameter."""
        from projects.POC.scripts.memory_indexer import retrieve
        sig = inspect.signature(retrieve)
        self.assertIn(
            'learning_type', sig.parameters,
            "retrieve() must accept a 'learning_type' parameter for type-aware "
            "filtering (institutional, task, proxy)."
        )

    def test_learning_type_default_is_none(self):
        """learning_type defaults to None (backward compatible — no filtering)."""
        from projects.POC.scripts.memory_indexer import retrieve
        sig = inspect.signature(retrieve)
        param = sig.parameters['learning_type']
        self.assertIs(
            param.default, None,
            "learning_type must default to None for backward compatibility."
        )


# ── 2. retrieve() accepts max_chars budget parameter ─────────────────────────

class TestRetrieveMaxCharsParameter(unittest.TestCase):
    """retrieve() must accept an optional max_chars parameter for budget caps."""

    def test_max_chars_in_signature(self):
        """retrieve() must accept a max_chars parameter."""
        from projects.POC.scripts.memory_indexer import retrieve
        sig = inspect.signature(retrieve)
        self.assertIn(
            'max_chars', sig.parameters,
            "retrieve() must accept a 'max_chars' parameter for per-type "
            "budget allocation."
        )

    def test_max_chars_default_is_zero(self):
        """max_chars defaults to 0 (no limit — backward compatible)."""
        from projects.POC.scripts.memory_indexer import retrieve
        sig = inspect.signature(retrieve)
        param = sig.parameters['max_chars']
        self.assertEqual(
            param.default, 0,
            "max_chars must default to 0 (no limit) for backward compatibility."
        )

    def test_max_chars_truncates_output(self):
        """When max_chars is set, retrieve() output does not exceed it."""
        tmpdir = tempfile.mkdtemp()
        try:
            # Create several long task learnings
            entries = {}
            for i in range(5):
                entries[f'tasks/learning-{i}.md'] = _make_entry(
                    f'task-{i}',
                    f'## Task Learning {i}\n' + ('x ' * 200),
                    importance=0.9,
                )
            db_path, abs_paths = _make_indexed_db(tmpdir, entries)

            from projects.POC.scripts.memory_indexer import retrieve
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='task learning'):
                result = retrieve(
                    task='test task',
                    db_path=db_path,
                    source_paths=[os.path.join(tmpdir, 'tasks')],
                    top_k=10,
                    max_chars=500,
                )
            self.assertLessEqual(
                len(result), 500,
                f"retrieve() output is {len(result)} chars but max_chars=500. "
                "Budget cap must be enforced."
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 3. classify_learning_type maps source paths to learning categories ───────

class TestClassifyLearningType(unittest.TestCase):
    """Source path determines learning type: institutional, task, proxy."""

    def test_function_exists(self):
        """classify_learning_type() must be importable."""
        try:
            from projects.POC.scripts.memory_indexer import classify_learning_type
        except ImportError:
            self.fail(
                "memory_indexer.py must export classify_learning_type(source_path) "
                "to map source paths to learning categories."
            )

    def test_institutional_md(self):
        """institutional.md maps to 'institutional'."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        self.assertEqual(
            classify_learning_type('/project/institutional.md'),
            'institutional',
        )

    def test_tasks_dir(self):
        """Files in tasks/ map to 'task'."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        self.assertEqual(
            classify_learning_type('/project/tasks/learning-1.md'),
            'task',
        )

    def test_proxy_md(self):
        """proxy.md maps to 'proxy'."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        self.assertEqual(
            classify_learning_type('/project/proxy.md'),
            'proxy',
        )

    def test_proxy_tasks_dir(self):
        """Files in proxy-tasks/ map to 'proxy'."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        self.assertEqual(
            classify_learning_type('/project/proxy-tasks/pattern-1.md'),
            'proxy',
        )

    def test_unknown_defaults_to_task(self):
        """Unrecognized paths default to 'task'."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        self.assertEqual(
            classify_learning_type('/project/MEMORY.md'),
            'task',
        )


# ── 4. Type filtering in retrieve() ──────────────────────────────────────────

class TestTypeFilteredRetrieval(unittest.TestCase):
    """retrieve() with learning_type returns only entries from matching sources."""

    def _make_mixed_db(self):
        """Create a DB with both institutional and task entries."""
        tmpdir = tempfile.mkdtemp()
        files = {
            'institutional.md': _make_entry(
                'inst-1',
                '## Code Review Convention\nReviewer runs tests before reading diff.',
                importance=0.9,
            ),
            'tasks/deploy-learning.md': _make_entry(
                'task-1',
                '## Deployment Pattern\nAlways run migrations before deploying.',
                importance=0.8,
            ),
        }
        db_path, abs_paths = _make_indexed_db(tmpdir, files)
        return tmpdir, db_path, abs_paths

    def test_learning_type_task_excludes_institutional(self):
        """learning_type='task' must not return institutional entries."""
        tmpdir, db_path, abs_paths = self._make_mixed_db()
        try:
            from projects.POC.scripts.memory_indexer import retrieve
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='code review convention deploy migration'):
                result = retrieve(
                    task='deployment task',
                    db_path=db_path,
                    source_paths=list(abs_paths.values()),
                    top_k=10,
                    learning_type='task',
                )
            # Should contain task learning, not institutional
            self.assertNotIn('Code Review Convention', result,
                             "learning_type='task' must filter out institutional entries.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_learning_type_institutional_excludes_tasks(self):
        """learning_type='institutional' must not return task entries."""
        tmpdir, db_path, abs_paths = self._make_mixed_db()
        try:
            from projects.POC.scripts.memory_indexer import retrieve
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='code review convention deploy migration'):
                result = retrieve(
                    task='code review',
                    db_path=db_path,
                    source_paths=list(abs_paths.values()),
                    top_k=10,
                    learning_type='institutional',
                )
            self.assertNotIn('Deployment Pattern', result,
                             "learning_type='institutional' must filter out task entries.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_learning_type_none_returns_all(self):
        """learning_type=None (default) returns entries from all types."""
        tmpdir, db_path, abs_paths = self._make_mixed_db()
        try:
            from projects.POC.scripts.memory_indexer import retrieve
            with patch('projects.POC.scripts.memory_indexer.build_retrieval_query',
                       return_value='code review convention deploy migration'):
                result = retrieve(
                    task='everything',
                    db_path=db_path,
                    source_paths=list(abs_paths.values()),
                    top_k=10,
                    learning_type=None,
                )
            # With no type filter, both should potentially appear
            # (at least the result should be non-empty)
            self.assertTrue(len(result) > 0,
                            "learning_type=None should return results from all types.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 5. Session callers: institutional.md not passed to fuzzy retrieve ────────

class TestSessionDoesNotFuzzyRetrieveInstitutional(unittest.TestCase):
    """session.py must not pass institutional.md to retrieve() source_paths.

    institutional.md is already loaded unconditionally as a raw file read.
    Passing it to retrieve() causes double-loading and wastes the fuzzy
    retrieval budget on content that should be injected in full.
    """

    def test_retrieve_memory_source_paths_exclude_institutional(self):
        """_retrieve_memory() must not include institutional.md in source_paths."""
        from projects.POC.orchestrator.session import Session
        source = inspect.getsource(Session._retrieve_memory)
        # The source_paths list should not contain 'institutional.md'
        # It should only contain fuzzy-retrieved sources like 'tasks'
        lines = [l.strip() for l in source.splitlines()
                 if 'source_paths' in l or 'institutional.md' in l]
        # Check that institutional.md is not passed as a source to retrieve()
        # It should only appear in the raw file read section
        retrieve_section = source.split('retrieve(')[1] if 'retrieve(' in source else ''
        self.assertNotIn(
            'institutional.md', retrieve_section,
            "_retrieve_memory() passes institutional.md to retrieve() source_paths. "
            "institutional.md is already loaded as a raw file read — it should not "
            "also be fuzzy-retrieved. Remove it from retrieve() source_paths."
        )


if __name__ == '__main__':
    unittest.main()
