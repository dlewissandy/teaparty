"""Regression: leads' tools and skills are declared in their CONFIG.

Issue #423 introduced ``Delegate`` and ``attempt-task``.  An earlier
attempt added them via role-conditional injection in the launcher
(``_role_implied_tools`` / ``_role_implied_skills``) — that was
case-specific code and got removed.  Tools and skills travel through
the same mechanism every other agent uses:

  - tools: ``settings.yaml``'s ``permissions.allow``
  - skills: ``agent.md``'s frontmatter ``skills:`` list

This file pins two invariants:

1. Every project-lead-shaped agent has ``mcp__teaparty-config__Delegate``
   in its ``settings.yaml``'s ``permissions.allow``.  Without it the
   lead cannot dispatch to workgroup-leads via the workflow-prefix
   mechanism the ``execute`` skill prescribes.

2. Every workgroup-lead has ``attempt-task`` in its ``agent.md``
   frontmatter ``skills:`` list.  Without it, the launcher's skill
   staging does not copy the body into the worktree, and the
   workgroup-lead's first message (``Run the /attempt-task skill...``)
   resolves to "unknown skill" at runtime.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Project-lead-shaped agents — every entry must allow Delegate.
# OM heads the management team (members include project-leads +
# workgroup-leads + proxy); the rest head a project (members are
# workgroup-leads).  Both shapes dispatch to recipients that run
# their own workflow skill on launch, so both need Delegate.
PROJECT_LEAD_SETTINGS_PATHS = (
    REPO_ROOT / '.teaparty/management/agents/office-manager/settings.yaml',
    REPO_ROOT / '.teaparty/project/agents/project-lead/settings.yaml',
    REPO_ROOT / '.teaparty/project/agents/teaparty-lead/settings.yaml',
)


class ProjectLeadDelegateInSettingsTest(unittest.TestCase):
    """Project-lead-shaped agents declare Delegate in their settings.yaml."""

    def test_each_project_lead_settings_has_delegate(self) -> None:
        import yaml as _yaml
        missing = []
        for p in PROJECT_LEAD_SETTINGS_PATHS:
            self.assertTrue(
                p.is_file(),
                f'project-lead-shaped settings.yaml missing at {p}',
            )
            data = _yaml.safe_load(p.read_text()) or {}
            allow = (data.get('permissions') or {}).get('allow') or []
            if 'mcp__teaparty-config__Delegate' not in allow:
                missing.append(str(p))
        self.assertEqual(
            missing, [],
            f'Project-lead-shaped agents missing '
            f'mcp__teaparty-config__Delegate in their settings.yaml '
            f'permissions.allow:\n' +
            '\n'.join(f'  {p}' for p in missing) +
            '\nWithout this declaration the lead cannot dispatch to '
            'workgroup-leads via the workflow-skill mechanism the '
            'execute skill prescribes.',
        )


class WorkgroupLeadAttemptTaskInFrontmatterTest(unittest.TestCase):
    """Every workgroup-lead has ``attempt-task`` in its agent.md
    frontmatter ``skills:`` list."""

    def setUp(self) -> None:
        # Workgroup-leads in both scope trees, excluding project-shaped
        # leads (OM, project-lead, teaparty-lead, joke-book-lead etc.)
        # and any non-lead directories.  Heuristic: name ends in
        # ``-lead`` AND is not in the project-shaped exclusion set.
        excluded = {'office-manager', 'project-lead', 'teaparty-lead'}
        self.lead_files: list[Path] = []
        for scope in ('management/agents', 'project/agents'):
            base = REPO_ROOT / '.teaparty' / scope
            if not base.is_dir():
                continue
            for d in base.iterdir():
                if not d.is_dir():
                    continue
                name = d.name
                if name in excluded or '-lead' not in name:
                    continue
                f = d / 'agent.md'
                if f.is_file():
                    self.lead_files.append(f)
        self.assertGreater(
            len(self.lead_files), 5,
            'expected to find multiple workgroup-lead agent.md files',
        )

    def test_each_workgroup_lead_skills_contains_attempt_task(self) -> None:
        """Frontmatter ``skills:`` list must include ``attempt-task``."""
        missing = []
        for f in self.lead_files:
            text = f.read_text()
            # Extract YAML frontmatter block.
            if not text.startswith('---'):
                missing.append(str(f) + ' (no frontmatter)')
                continue
            end = text.find('\n---', 3)
            if end == -1:
                missing.append(str(f) + ' (frontmatter unterminated)')
                continue
            frontmatter = text[3:end]
            # Look for a ``skills:`` block followed by lines that include
            # ``- attempt-task``.  YAML parser would be cleaner; the
            # regex is sufficient because the format is consistent.
            skills_match = re.search(
                r'^skills:\n((?:- [^\n]*\n)+)',
                frontmatter, flags=re.MULTILINE,
            )
            if skills_match is None:
                missing.append(str(f) + ' (no skills: block)')
                continue
            skills_block = skills_match.group(1)
            if 'attempt-task' not in skills_block:
                missing.append(str(f) + ' (skills: block lacks attempt-task)')

        self.assertEqual(
            missing, [],
            f'Workgroup-leads without ``attempt-task`` in their '
            f'agent.md frontmatter skills::\n' +
            '\n'.join(f'  {m}' for m in missing) +
            '\n\nWithout this declaration the launcher\'s skill '
            'staging does not copy attempt-task into the worktree, '
            'and the lead\'s first dispatched message '
            '(``Run the /attempt-task skill...``) resolves to '
            '"unknown skill" at runtime.',
        )


if __name__ == '__main__':
    unittest.main()
