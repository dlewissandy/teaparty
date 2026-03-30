#!/usr/bin/env python3
"""Failing tests (TDD) for issue #84: memory_indexer.py needs importable retrieve().

Two bugs:
  Bug 1 — memory_indexer.py has no importable retrieve() function. The only
           entry point is main() which uses argparse and file I/O.
  Bug 2 — session.py._retrieve_memory() calls memory_indexer.py via subprocess
           instead of importing retrieve() directly. The subprocess call works
           but is fragile, and errors are silently swallowed by except Exception: pass.
"""
import inspect
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.memory_indexer import (
    open_db, index_file, chunk_text,
)


# ── Bug 1: memory_indexer.py needs importable retrieve() ──────────────────────

class TestRetrieveFunctionExists(unittest.TestCase):
    """Bug 1: memory_indexer.py has no importable retrieve() function.

    The issue requires: retrieve(task, db_path, source_paths, top_k, scope_base_dir) -> str
    """

    def test_retrieve_is_importable(self):
        """retrieve() must be importable from memory_indexer."""
        try:
            from scripts.memory_indexer import retrieve
        except ImportError:
            self.fail(
                "memory_indexer.py must export an importable retrieve() function. "
                "Currently only main() exists as an entry point."
            )

    def test_retrieve_signature(self):
        """retrieve() must accept task, db_path, source_paths, top_k, scope_base_dir."""
        try:
            from scripts.memory_indexer import retrieve
        except ImportError:
            self.skipTest("retrieve() not yet importable")

        sig = inspect.signature(retrieve)
        params = set(sig.parameters.keys())
        required = {'task', 'db_path', 'source_paths', 'top_k', 'scope_base_dir'}
        missing = required - params
        self.assertFalse(
            missing,
            f"retrieve() is missing parameters: {missing}. "
            f"Current params: {params}",
        )

    def test_retrieve_returns_string(self):
        """retrieve() must return a string (the formatted retrieval context)."""
        try:
            from scripts.memory_indexer import retrieve
        except ImportError:
            self.skipTest("retrieve() not yet importable")

        tmpdir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(tmpdir, '.memory.db')
            # Create a minimal indexed DB
            source = os.path.join(tmpdir, 'test.md')
            Path(source).write_text(
                "---\nid: test-1\ntype: declarative\nimportance: 0.8\n---\n"
                "## [2026-01-01] Test Learning\n"
                "**Context:** Testing retrieve function\n"
                "**Learning:** The function should return a string\n"
            )
            conn = open_db(db_path)
            index_file(conn, source)
            conn.close()

            # Mock build_retrieval_query to avoid calling claude
            with patch('scripts.memory_indexer.build_retrieval_query',
                       return_value='test learning retrieve'):
                result = retrieve(
                    task='test task about learning',
                    db_path=db_path,
                    source_paths=[source],
                    top_k=5,
                    scope_base_dir=tmpdir,
                )
            self.assertIsInstance(result, str, "retrieve() must return a string")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Bug 2: session.py should call retrieve() directly ─────────────────────────

class TestSessionUsesRetrieveDirectly(unittest.TestCase):
    """Bug 2: session.py._retrieve_memory() uses subprocess instead of import.

    The fix should replace the subprocess.run() call with a direct import
    of retrieve() from memory_indexer.
    """

    def test_retrieve_memory_does_not_use_subprocess(self):
        """_retrieve_memory() must not shell out to memory_indexer.py.

        Bug: session.py calls subprocess.run(['python3', script, ...])
        to invoke memory_indexer.py. This is fragile and couples to CLI flags.
        The fix should import and call retrieve() directly.
        """
        from orchestrator.session import Session

        source = inspect.getsource(Session._retrieve_memory)
        self.assertNotIn(
            'subprocess.run',
            source,
            "_retrieve_memory() still uses subprocess.run(). "
            "It should import and call retrieve() directly.",
        )

    def test_retrieve_memory_static_does_not_use_subprocess(self):
        """_retrieve_memory_static() must also not shell out.

        There is a second code path — _retrieve_memory_static() — that
        also calls memory_indexer.py via subprocess. Both must be fixed.
        """
        from orchestrator.session import Session

        if not hasattr(Session, '_retrieve_memory_static'):
            return  # method doesn't exist, nothing to check

        source = inspect.getsource(Session._retrieve_memory_static)
        self.assertNotIn(
            'subprocess.run',
            source,
            "_retrieve_memory_static() still uses subprocess.run(). "
            "It should import and call retrieve() directly.",
        )


if __name__ == '__main__':
    unittest.main()
