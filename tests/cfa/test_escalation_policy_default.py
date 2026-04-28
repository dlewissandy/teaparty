"""Regression: when the project.yaml has no entry for the current CfA
state's escalation policy, the runner must return ``when_unsure`` so
the ``/escalation`` skill receives a valid argument.

Bug reproduced from joke-book: the bridge's PATCH handler treats
``when_unsure`` as the default by *deleting* the entry from the map
("default = absent").  When every state was set to ``when_unsure`` via
the UI, the project.yaml ended up with no ``escalation:`` key at all.
``_resolve_escalation_policy`` then returned ``''``, the orchestrator
seeded the proxy with a bare ``/escalation``, and the skill emitted
``UNKNOWN POLICY``.

The fix is to bridge the contract gap: absent ⇒ ``when_unsure``, the
default the bridge already documents.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.gates.escalation import (
    AskQuestionRunner,
    _DEFAULT_ESCALATION_POLICY,
)


class EscalationPolicyDefaultTest(unittest.TestCase):
    """``_resolve_escalation_policy`` must default to ``when_unsure``."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='escalation-policy-')
        # infra_dir layout: {project_root}/.teaparty/jobs/{job-dir}
        self.project_root = self._tmp
        self.jobs_dir = os.path.join(self.project_root, '.teaparty', 'jobs')
        self.infra_dir = os.path.join(self.jobs_dir, 'job-test')
        os.makedirs(self.infra_dir)
        self.project_dir = os.path.join(
            self.project_root, '.teaparty', 'project',
        )
        os.makedirs(self.project_dir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_runner(self) -> AskQuestionRunner:
        return AskQuestionRunner(
            bus_db_path='/tmp/unused.sqlite',
            infra_dir=self.infra_dir,
        )

    def _write_cfa_state(self, state: str) -> None:
        path = os.path.join(self.infra_dir, '.cfa-state.json')
        with open(path, 'w') as fh:
            json.dump({'state': state}, fh)

    def _write_project_yaml(self, payload: dict) -> None:
        path = os.path.join(self.project_dir, 'project.yaml')
        with open(path, 'w') as fh:
            yaml.safe_dump(payload, fh)

    # ── The reported bug ──────────────────────────────────────────────────

    def test_missing_escalation_map_returns_default(self) -> None:
        """The reported joke-book failure: no escalation key in project.yaml.

        Before the fix, this returned ``''`` and the skill rejected the
        empty argument.  After the fix, ``when_unsure`` is returned.
        """
        self._write_cfa_state('INTENT')
        self._write_project_yaml({
            'name': 'joke-book',
            'lead': 'joke-book-lead',
            # No escalation key — exactly what the bridge writes when
            # every state is set to when_unsure.
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    def test_escalation_map_missing_state_returns_default(self) -> None:
        """A map present but missing the current state defaults too."""
        self._write_cfa_state('PLAN')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'INTENT': 'always'},  # PLAN absent
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    def test_empty_string_value_returns_default(self) -> None:
        """A pathological empty-string value must not pass through."""
        self._write_cfa_state('INTENT')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'INTENT': ''},
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    def test_non_string_value_returns_default(self) -> None:
        """A non-string YAML value (e.g. accidental list) defaults."""
        self._write_cfa_state('INTENT')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'INTENT': ['always']},  # wrong type
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    # ── Failure modes earlier in the path ─────────────────────────────────

    def test_missing_infra_dir_returns_default(self) -> None:
        """Chat-tier callers (no infra_dir) get the default policy."""
        runner = AskQuestionRunner(
            bus_db_path='/tmp/unused.sqlite',
            infra_dir='',
        )
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    def test_missing_cfa_state_file_returns_default(self) -> None:
        """No .cfa-state.json on disk yet (race) defaults."""
        # Don't call _write_cfa_state.
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'INTENT': 'always'},
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    def test_missing_project_yaml_returns_default(self) -> None:
        """No project.yaml on disk defaults."""
        self._write_cfa_state('INTENT')
        # Don't call _write_project_yaml.
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            _DEFAULT_ESCALATION_POLICY,
        )

    # ── Happy path ────────────────────────────────────────────────────────

    def test_explicit_always_passes_through(self) -> None:
        self._write_cfa_state('INTENT')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'INTENT': 'always'},
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            'always',
        )

    def test_explicit_never_passes_through(self) -> None:
        self._write_cfa_state('EXECUTE')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'EXECUTE': 'never'},
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            'never',
        )

    def test_explicit_when_unsure_passes_through(self) -> None:
        """If the bridge ever does write when_unsure explicitly, it works."""
        self._write_cfa_state('PLAN')
        self._write_project_yaml({
            'name': 'p',
            'lead': 'l',
            'escalation': {'PLAN': 'when_unsure'},
        })
        runner = self._make_runner()
        self.assertEqual(
            runner._resolve_escalation_policy(),
            'when_unsure',
        )


if __name__ == '__main__':
    unittest.main()
