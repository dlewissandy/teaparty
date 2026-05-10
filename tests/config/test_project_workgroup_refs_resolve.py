"""Regression test: every project workgroup ref resolves on a
case-sensitive filesystem.

Background: ``resolve_workgroups`` in ``teaparty.config.config_reader``
treats each ``- ref: <name>`` entry as a literal filename via
``f'{entry.ref}.yaml'``.  On macOS APFS (case-insensitive by
default) ``Intake.yaml`` resolves to ``intake.yaml`` and the ref
appears to work.  On Linux (case-sensitive) the same ref raises
FileNotFoundError -- which is what broke CI when the
software-development roster test first exercised the project
workgroup-resolution path.

This test loads the TeaParty project config and verifies each ref
resolves to an on-disk file using case-sensitive matching, so the
case mismatch fails CI before the merge instead of after.
"""
from __future__ import annotations

import os
import unittest

from teaparty.config.config_reader import (
    WorkgroupRef,
    load_project_team,
    management_workgroups_dir,
    project_workgroups_dir,
)


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'),
)
TEAPARTY_HOME = os.path.join(REPO_ROOT, '.teaparty')


def _case_sensitive_exists(path: str) -> bool:
    """Like ``os.path.exists`` but rejects matches that differ only
    in case from the on-disk entry.  This emulates the Linux
    case-sensitive filesystem semantics CI runs under, so the test
    catches case mismatches even when run on macOS APFS."""
    if not os.path.exists(path):
        return False
    parent = os.path.dirname(path)
    name = os.path.basename(path)
    try:
        entries = os.listdir(parent)
    except OSError:
        return False
    return name in entries


class TestProjectWorkgroupRefsResolve(unittest.TestCase):

    def test_every_project_workgroup_ref_resolves_case_sensitive(self):
        """Every ``- ref: <name>`` entry in TeaParty's project.yaml
        must resolve to an existing YAML file using exact-case
        filename matching.  A mismatched case (``Intake`` ref with
        ``intake.yaml`` on disk) passes on macOS but fails on the
        CI Linux runner -- so the test must enforce case-sensitive
        matching regardless of host filesystem."""
        proj = load_project_team(REPO_ROOT)
        unresolved: list[str] = []

        for entry in proj.workgroups:
            if not isinstance(entry, WorkgroupRef):
                continue
            filename = f'{entry.ref}.yaml'
            project_path = os.path.join(
                project_workgroups_dir(REPO_ROOT), filename,
            )
            org_path = os.path.join(
                management_workgroups_dir(TEAPARTY_HOME), filename,
            )
            if not (_case_sensitive_exists(project_path)
                    or _case_sensitive_exists(org_path)):
                unresolved.append(entry.ref)

        self.assertEqual(
            unresolved, [],
            f'project.yaml workgroup refs do not resolve case-sensitively: '
            f'{unresolved}.  Lowercase the ref in '
            f'.teaparty/project/project.yaml so it matches the catalog '
            f'filename exactly (e.g. ``- ref: intake`` not '
            f'``- ref: Intake``).  Mismatched case passes on macOS APFS '
            f'and fails on Linux CI.',
        )


if __name__ == '__main__':
    unittest.main()
