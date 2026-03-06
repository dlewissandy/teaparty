#!/usr/bin/env python3
"""Tests for Phase 2: INTENT.md archival and lifecycle isolation.

These are contract tests that verify run.sh does not load prior INTENT.md
as persistent context and correctly archives it to the infra directory.
"""
import os
import re
import sys
import unittest
from pathlib import Path

# Path to run.sh relative to this test file
REPO_ROOT = Path(__file__).parent.parent.parent
RUN_SH = REPO_ROOT / "run.sh"


def read_run_sh() -> str:
    if not RUN_SH.is_file():
        return ""
    return RUN_SH.read_text()


class TestIntentArchivalContracts(unittest.TestCase):
    """Verify run.sh implements Phase 2 INTENT.md isolation correctly."""

    def setUp(self):
        self.run_sh = read_run_sh()
        if not self.run_sh:
            self.skipTest(f"run.sh not found at {RUN_SH}")

    # ── Context loading ───────────────────────────────────────────────────────

    def test_poc_repo_dir_intent_not_loaded_as_context(self):
        """SUCCESS CRITERION 6 prerequisite: POC_REPO_DIR/INTENT.md must NOT
        appear in the INTENT_CTX loading block."""
        # Find the INTENT_CTX building block
        intent_ctx_block = re.search(
            r'INTENT_CTX=\(\)(.*?)if "\$SCRIPT_DIR/intent\.sh"',
            self.run_sh,
            re.DOTALL,
        )
        if intent_ctx_block:
            block_text = intent_ctx_block.group(1)
            # Should not find active (uncommented) INTENT.md context from POC_REPO_DIR
            lines = block_text.splitlines()
            active_lines = [l for l in lines if 'POC_REPO_DIR/INTENT.md' in l and not l.strip().startswith('#')]
            self.assertEqual(
                len(active_lines), 0,
                f"Found POC_REPO_DIR/INTENT.md still being loaded as context:\n" +
                '\n'.join(active_lines),
            )

    def test_infra_dir_intent_used_for_alignment(self):
        """Phase 2: intent-alignment step must read from INFRA_DIR/INTENT.md."""
        # Find the intent-alignment block
        alignment_block = re.search(
            r'[Ii]ntent.vs.outcome alignment.*?\n(.*?\n){0,10}',
            self.run_sh,
            re.DOTALL,
        )
        self.assertIn(
            'INFRA_DIR/INTENT.md',
            self.run_sh,
            "INFRA_DIR/INTENT.md not found anywhere in run.sh — alignment step not updated",
        )

    def test_intent_md_archived_to_infra_dir(self):
        """Phase 2: run.sh must copy INTENT.md from worktree to INFRA_DIR."""
        # Look for a cp command that copies INTENT.md to INFRA_DIR
        # PROJECT_WORKDIR is the scoped CWD (may be a subdir of SESSION_WORKTREE)
        self.assertRegex(
            self.run_sh,
            r'cp\s+.*INTENT\.md.*INFRA_DIR.*INTENT\.md|cp\s+.*(SESSION_WORKTREE|PROJECT_WORKDIR).*INTENT\.md.*INFRA_DIR',
            "run.sh does not contain a cp command archiving INTENT.md to INFRA_DIR",
        )

    def test_intent_md_removed_from_worktree(self):
        """Phase 2: INTENT.md must be removed from project workdir after archival."""
        # PROJECT_WORKDIR is the scoped CWD (subdir of SESSION_WORKTREE in linked-repo mode)
        self.assertRegex(
            self.run_sh,
            r'rm\s+.*(SESSION_WORKTREE|PROJECT_WORKDIR).*INTENT\.md',
            "run.sh does not remove INTENT.md from project workdir after archiving",
        )

    def test_task_prepend_uses_infra_dir_intent(self):
        """Phase 2: TASK prepend must read from INFRA_DIR/INTENT.md, not SESSION_WORKTREE."""
        # Find the TASK prepend block
        task_prepend = re.search(
            r'TASK="\$\(cat "(.*?)INTENT\.md"\)',
            self.run_sh,
        )
        if task_prepend:
            source = task_prepend.group(1)
            self.assertIn(
                'INFRA_DIR',
                source,
                f"TASK prepend reads from '{source}INTENT.md' not INFRA_DIR",
            )
        else:
            # Accept if the pattern looks different
            self.assertIn(
                'INFRA_DIR/INTENT.md',
                self.run_sh,
                "INFRA_DIR/INTENT.md not referenced for TASK prepend",
            )

    # ── Archival ordering ────────────────────────────────────────────────────

    def test_archival_before_task_prepend(self):
        """The cp (archival) must appear before the TASK= line that cats INFRA_DIR/INTENT.md."""
        # Try PROJECT_WORKDIR first (linked-repo mode), fall back to SESSION_WORKTREE
        cp_pos = self.run_sh.find('cp "$PROJECT_WORKDIR/INTENT.md"')
        if cp_pos == -1:
            cp_pos = self.run_sh.find('cp "$SESSION_WORKTREE/INTENT.md"')
        task_pos = self.run_sh.find('INFRA_DIR/INTENT.md")')
        if cp_pos == -1 or task_pos == -1:
            # Try alternate patterns
            cp_pos = self.run_sh.find('INFRA_DIR/INTENT.md\n')
            task_pos = self.run_sh.find('cat "$INFRA_DIR/INTENT.md"')
        if cp_pos != -1 and task_pos != -1:
            self.assertLess(
                cp_pos, task_pos,
                "Archival (cp) must appear before TASK prepend (cat INFRA_DIR/INTENT.md)",
            )


class TestIntentArchivalIsolation(unittest.TestCase):
    """Verify that the contract prevents session bleed-over."""

    def test_no_poc_repo_dir_intent_as_active_context_anywhere(self):
        """POC_REPO_DIR/INTENT.md must not appear as a --context-file in run.sh."""
        run_sh = read_run_sh()
        if not run_sh:
            self.skipTest("run.sh not found")

        # Find all --context-file occurrences that reference INTENT.md
        context_uses = re.findall(
            r'--context-file\s+"?\$([A-Z_]+)/INTENT\.md"?',
            run_sh,
        )
        # Only INFRA_DIR is allowed as a context source for INTENT.md
        for var in context_uses:
            self.assertEqual(
                var, 'INFRA_DIR',
                f"Found --context-file ${var}/INTENT.md — only INFRA_DIR is permitted",
            )


if __name__ == '__main__':
    unittest.main()
