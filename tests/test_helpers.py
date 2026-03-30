"""Shared test helpers for orchestrator test isolation.

Provides real temp-directory creation with automatic cleanup, replacing
hardcoded fake paths like /tmp/fake throughout the test suite.

Issue #314.
"""
import shutil
import tempfile
import unittest


def make_tmp_dir(test_case: unittest.TestCase) -> str:
    """Create a real temp directory and register cleanup via addCleanup.

    Returns a real directory path suitable for use as infra_dir, project_workdir,
    session_worktree, proxy_model_path, poc_root, or any other path argument
    that needs a real (but ephemeral) location during testing.

    The directory is removed after the test via test_case.addCleanup, so no
    filesystem artifacts accumulate at fixed paths like /tmp/fake.

    Usage in tests:
        tmp = make_tmp_dir(self)
        orch = Orchestrator(infra_dir=tmp, project_workdir=tmp, ...)
    """
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    test_case.addCleanup(shutil.rmtree, tmp, True)
    return tmp
