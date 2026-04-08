"""Issue #384 (cutover): worktree.py must not reference worktrees.json.

The job_store.py module replaces the flat worktrees.json manifest.
These tests verify that the legacy worktrees.json code paths have been
removed from worktree.py, state_reader.py, and the codebase.
"""
from __future__ import annotations

import ast
import os
import unittest


def _module_function_names(filepath: str) -> set[str]:
    """Return the set of top-level and class-method function names in a module."""
    with open(filepath) as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestWorktreeModuleCutover(unittest.TestCase):
    """worktree.py no longer contains worktrees.json-dependent code."""

    def test_no_worktrees_json_reference_in_worktree_module(self):
        """worktree.py must not contain any reference to worktrees.json."""
        filepath = os.path.join(_repo_root(), 'teaparty', 'workspace', 'worktree.py')
        with open(filepath) as f:
            source = f.read()
        self.assertNotIn('worktrees.json', source,
                         'worktree.py still references worktrees.json')

    def test_dead_functions_removed_from_worktree_module(self):
        """The legacy worktrees.json functions must not exist in worktree.py."""
        filepath = os.path.join(_repo_root(), 'teaparty', 'workspace', 'worktree.py')
        names = _module_function_names(filepath)
        dead = {
            'create_session_worktree',
            'create_dispatch_worktree',
            'cleanup_worktree',
            'find_orphaned_worktrees',
            '_register_worktree',
            '_unregister_worktree',
        }
        found = dead & names
        self.assertEqual(found, set(),
                         f'Dead functions still present: {found}')

    def test_no_load_manifest_in_state_reader(self):
        """state_reader.py must not contain the dead _load_manifest method."""
        filepath = os.path.join(_repo_root(), 'teaparty', 'bridge', 'state', 'reader.py')
        names = _module_function_names(filepath)
        self.assertNotIn('_load_manifest', names,
                         '_load_manifest still present in state_reader.py')

    def test_worktree_manifest_script_removed(self):
        """scripts/worktree_manifest.py must not exist."""
        filepath = os.path.join(_repo_root(), 'scripts', 'worktree_manifest.py')
        self.assertFalse(os.path.exists(filepath),
                         'scripts/worktree_manifest.py still exists')

    def test_merge_exclusion_list_no_worktrees_json(self):
        """merge.py must not exclude worktrees.json from merges."""
        filepath = os.path.join(_repo_root(), 'teaparty', 'workspace', 'merge.py')
        with open(filepath) as f:
            source = f.read()
        self.assertNotIn('worktrees.json', source,
                         'merge.py still references worktrees.json')

    def test_worktrees_json_file_removed(self):
        """worktrees.json must not exist at repo root (SC6)."""
        filepath = os.path.join(_repo_root(), 'worktrees.json')
        self.assertFalse(os.path.exists(filepath),
                         'worktrees.json still exists at repo root')

    def test_dead_session_scan_methods_removed_from_state_reader(self):
        """Legacy .sessions/-based scan methods must not exist in state_reader.py."""
        filepath = os.path.join(_repo_root(), 'teaparty', 'bridge', 'state', 'reader.py')
        names = _module_function_names(filepath)
        dead = {'_scan_project_sessions', '_find_dispatches_for_session'}
        found = dead & names
        self.assertEqual(found, set(),
                         f'Dead session scan methods still present: {found}')
