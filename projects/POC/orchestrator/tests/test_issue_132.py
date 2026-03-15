#!/usr/bin/env python3
"""Tests for issue #132: Learning retrieval toggles for experiment control.

Covers:
 1. Session accepts learning_retrieval_mode and skip_learning_retrieval params.
 2. skip_learning_retrieval=True causes _retrieve_memory to return empty string.
 3. learning_retrieval_mode='disabled' causes _retrieve_memory to return empty string.
 4. learning_retrieval_mode='scoped' passes scope_base_dir to retrieve().
 5. learning_retrieval_mode='flat' passes empty scope_base_dir (no scope weighting).
 6. Default behavior (flat, no skip) is unchanged.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.session import Session


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(**overrides) -> Session:
    poc_root = str(Path(__file__).resolve().parent.parent.parent)
    defaults = dict(
        task='Test task for retrieval toggles',
        poc_root=poc_root,
        projects_dir='/tmp/projects',
    )
    defaults.update(overrides)
    return Session(**defaults)


def _make_project_dir_with_memory() -> tempfile.TemporaryDirectory:
    td = tempfile.TemporaryDirectory()
    Path(os.path.join(td.name, 'institutional.md')).write_text('## Institutional\nTest norm')
    Path(os.path.join(td.name, 'proxy.md')).write_text('## Proxy\nTest preference')
    return td


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSessionAcceptsRetrievalParams(unittest.TestCase):

    def test_accepts_learning_retrieval_mode(self):
        s = _make_session(learning_retrieval_mode='scoped')
        self.assertEqual(s.learning_retrieval_mode, 'scoped')

    def test_accepts_skip_learning_retrieval(self):
        s = _make_session(skip_learning_retrieval=True)
        self.assertTrue(s.skip_learning_retrieval)

    def test_default_learning_retrieval_mode_is_flat(self):
        s = _make_session()
        self.assertEqual(s.learning_retrieval_mode, 'flat')

    def test_default_skip_learning_retrieval_is_false(self):
        s = _make_session()
        self.assertFalse(s.skip_learning_retrieval)


class TestSkipLearningRetrieval(unittest.TestCase):

    def test_skip_returns_empty(self):
        td = _make_project_dir_with_memory()
        with td:
            s = _make_session(skip_learning_retrieval=True)
            result = s._retrieve_memory(td.name)
            self.assertEqual(result, '')

    def test_no_skip_returns_content(self):
        td = _make_project_dir_with_memory()
        with td:
            s = _make_session(skip_learning_retrieval=False)
            result = s._retrieve_memory(td.name)
            self.assertIn('Institutional', result)


class TestRetrievalModeDisabled(unittest.TestCase):

    def test_disabled_returns_empty(self):
        td = _make_project_dir_with_memory()
        with td:
            s = _make_session(learning_retrieval_mode='disabled')
            result = s._retrieve_memory(td.name)
            self.assertEqual(result, '')


class TestRetrievalModeScoping(unittest.TestCase):

    def test_scoped_mode_passes_scope_base_dir(self):
        td = _make_project_dir_with_memory()
        with td:
            db_path = os.path.join(td.name, '.memory.db')
            Path(db_path).touch()

            s = _make_session(learning_retrieval_mode='scoped')

            with patch('projects.POC.scripts.memory_indexer.retrieve', return_value='') as mock:
                s._retrieve_memory(td.name)
                mock.assert_called_once()
                _, kwargs = mock.call_args
                self.assertEqual(kwargs['scope_base_dir'], td.name)

    def test_flat_mode_passes_empty_scope_base_dir(self):
        td = _make_project_dir_with_memory()
        with td:
            db_path = os.path.join(td.name, '.memory.db')
            Path(db_path).touch()

            s = _make_session(learning_retrieval_mode='flat')

            with patch('projects.POC.scripts.memory_indexer.retrieve', return_value='') as mock:
                s._retrieve_memory(td.name)
                mock.assert_called_once()
                _, kwargs = mock.call_args
                self.assertEqual(kwargs['scope_base_dir'], '')


if __name__ == '__main__':
    unittest.main()
