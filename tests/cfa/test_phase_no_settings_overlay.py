"""Regression tests: no ``settings_overlay`` hidden magic anywhere.

Per-phase permission overlays were the source of a confusing bug where
the project-lead silently lost its Send tool at planning/execution
because the phase's ``settings_overlay.permissions.allow`` list
replaced the agent's own whitelist.  The fix was to remove the
overlay mechanism entirely: an agent's own configuration (its
``settings.yaml`` folder permissions + its ``tools:`` / ``skills:``
frontmatter) is the *single* source of truth.  No hidden per-phase
tweaks, no silent replacement.

These tests guard the invariant at two layers (the JSON schema layer
is gone — phase config is literal Python constants now, so a rogue
``settings_overlay`` would have to show up in the PhaseSpec dataclass
fields or as a source-tree reference, both covered below):

1. The ``PhaseSpec`` dataclass has no ``settings_overlay`` field.
2. Source code does not read ``phase_spec.settings_overlay`` anywhere.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from dataclasses import fields


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NoSettingsOverlayTest(unittest.TestCase):

    def test_phase_spec_dataclass_has_no_settings_overlay(self) -> None:
        """PhaseSpec must not define a ``settings_overlay`` field."""
        from teaparty.cfa.phase_config import PhaseSpec
        field_names = {f.name for f in fields(PhaseSpec)}
        self.assertNotIn(
            'settings_overlay', field_names,
            'PhaseSpec still carries a ``settings_overlay`` field. '
            'Remove it — per-phase permissions overlay is not part of '
            'the design.',
        )

    def test_source_tree_does_not_reference_settings_overlay(self) -> None:
        """No ``.py`` file under teaparty/ reads or writes settings_overlay."""
        teaparty_root = os.path.join(_REPO_ROOT, 'teaparty')
        hits: list[str] = []
        for dirpath, _, filenames in os.walk(teaparty_root):
            if '__pycache__' in dirpath:
                continue
            for filename in filenames:
                if not filename.endswith('.py'):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path) as f:
                    contents = f.read()
                if 'settings_overlay' in contents:
                    hits.append(os.path.relpath(path, _REPO_ROOT))
        self.assertEqual(
            hits, [],
            f'source files still reference ``settings_overlay``: {hits}. '
            f'The overlay mechanism was removed; these references are '
            f'dead or re-introducing hidden permissions magic.',
        )


if __name__ == '__main__':
    unittest.main()
