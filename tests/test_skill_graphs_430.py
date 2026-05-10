"""Issue #430: structural invariants for the skill-graph skills.

Two new skills land in #430:

- ``.teaparty/project/skills/sprint/`` — discoverable by the
  ``project-lead`` agent; drives a sprint end-to-end via Delegate to
  scrum-master and software-development-lead.

- ``.teaparty/management/skills/fix-issue/`` — discoverable by the
  ``software-development-lead`` agent; resolves a single GitHub issue
  via Delegate to coding-lead, quality-control-lead, and
  quality-assurance-lead.

Both are skill graphs: one SKILL.md plus N phase-*.md files linked by
prose pointers naming the next file to read. The runtime that loads
them does not validate the graph — if a pointer names a file that
does not exist, the agent only discovers it at runtime when the phase
it is on tells it to read a missing file. This test pins three
invariants so structural drift surfaces in CI:

1. Each skill has a SKILL.md with name, description, and
   ``user-invocable: false`` in its frontmatter.

2. Every phase-*.md file the skill graph names (in SKILL.md or in any
   phase file) actually exists in the skill's directory.

3. The skill is registered on the agent that is supposed to invoke it
   — ``sprint`` on ``project-lead``, ``fix-issue`` on
   ``software-development-lead``. Without registration, the launcher
   does not stage the skill into the agent's launch and the agent
   sees "Unknown skill" at runtime.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


PHASE_REF_RE = re.compile(r'`(phase-[a-z0-9-]+\.md)`')


def _read_frontmatter(path: Path) -> dict:
    import yaml as _yaml
    text = path.read_text()
    if not text.startswith('---'):
        raise AssertionError(f'{path}: missing frontmatter')
    end = text.find('\n---', 3)
    if end == -1:
        raise AssertionError(f'{path}: unterminated frontmatter')
    return _yaml.safe_load(text[3:end]) or {}


def _find_phase_refs(skill_dir: Path) -> set[str]:
    """Collect every phase-*.md filename referenced inside a skill directory."""
    refs: set[str] = set()
    for f in skill_dir.glob('*.md'):
        for m in PHASE_REF_RE.finditer(f.read_text()):
            refs.add(m.group(1))
    return refs


SPRINT_DIR = REPO_ROOT / '.teaparty/project/skills/sprint'
FIX_ISSUE_DIR = REPO_ROOT / '.teaparty/management/skills/fix-issue'


class SkillGraphStructureTest(unittest.TestCase):
    """SKILL.md frontmatter and phase-pointer resolution."""

    skill_dirs = (SPRINT_DIR, FIX_ISSUE_DIR)

    def test_each_skill_has_skill_md(self) -> None:
        for d in self.skill_dirs:
            self.assertTrue(d.is_dir(), f'skill directory missing: {d}')
            self.assertTrue(
                (d / 'SKILL.md').is_file(),
                f'SKILL.md missing in {d}',
            )

    def test_skill_md_frontmatter_required_fields(self) -> None:
        for d in self.skill_dirs:
            fm = _read_frontmatter(d / 'SKILL.md')
            self.assertEqual(
                fm.get('name'), d.name,
                f'{d}/SKILL.md frontmatter name must equal directory name',
            )
            self.assertTrue(
                isinstance(fm.get('description'), str)
                and fm['description'].strip(),
                f'{d}/SKILL.md frontmatter is missing description',
            )
            self.assertIs(
                fm.get('user-invocable'), False,
                f'{d}/SKILL.md must declare user-invocable: false '
                '(agent-only skill).',
            )

    def test_every_phase_pointer_resolves(self) -> None:
        """Every `phase-*.md` referenced in a skill file must exist
        as a sibling file in the same skill directory."""
        broken: list[str] = []
        for d in self.skill_dirs:
            refs = _find_phase_refs(d)
            for ref in sorted(refs):
                target = d / ref
                if not target.is_file():
                    broken.append(f'{d}: pointer to {ref} resolves nowhere')
        self.assertEqual(
            broken, [],
            'Broken phase pointers in skill graphs:\n' +
            '\n'.join(f'  {b}' for b in broken),
        )

    def test_every_phase_file_is_reachable(self) -> None:
        """Every phase-*.md file in a skill directory is named by at
        least one pointer somewhere in the same skill — i.e. no
        orphan phase files that no other file routes to."""
        orphans: list[str] = []
        for d in self.skill_dirs:
            refs = _find_phase_refs(d)
            for f in d.glob('phase-*.md'):
                if f.name not in refs:
                    orphans.append(f'{d}: {f.name} is not referenced by any sibling file')
        self.assertEqual(
            orphans, [],
            'Orphan phase files (present but unreferenced):\n' +
            '\n'.join(f'  {o}' for o in orphans),
        )


class SkillRegisteredOnInvokingAgentTest(unittest.TestCase):
    """The skill is listed in the invoking agent's frontmatter
    skills:, so launcher staging copies it into the launch."""

    cases = (
        (
            'sprint',
            REPO_ROOT / '.teaparty/project/agents/project-lead/agent.md',
        ),
        (
            'fix-issue',
            REPO_ROOT / '.teaparty/management/agents/software-development-lead/agent.md',
        ),
    )

    def test_each_skill_is_registered_on_its_agent(self) -> None:
        missing: list[str] = []
        for skill_name, agent_path in self.cases:
            self.assertTrue(
                agent_path.is_file(),
                f'agent.md missing at {agent_path}',
            )
            fm = _read_frontmatter(agent_path)
            skills = fm.get('skills') or []
            if skill_name not in skills:
                missing.append(
                    f'{agent_path}: skills: list does not contain '
                    f'"{skill_name}" (got {skills!r}). Without this '
                    'declaration the launcher will not stage the skill '
                    'into the agent\'s launch and `/' + skill_name +
                    '` will resolve to "Unknown skill" at runtime.'
                )
        self.assertEqual(missing, [], '\n'.join(missing))


if __name__ == '__main__':
    unittest.main()
