"""Tests for the scrum-master project agent (issue #429).

Layered:
  1. Agent definition — agent.md frontmatter + settings.yaml shape
  2. Skill definitions — SKILL.md files for each of the seven skills
  3. Wiring — the agent's ``skills:`` frontmatter matches the on-disk
     skill directory exactly (no orphans, no missing)
  4. Body content — the agent.md and skill bodies encode the scope
     discipline and sync model the issue specifies (mechanics only,
     GitHub-first then cache, no tier judgment)
  5. State schema — ``sprint-plan`` documents the cache layout
     (``sprint.yaml``, ``index.md``, ``issues/{N}.md``) the issue
     requires

Each test maps to one or more acceptance criteria from issue #429.
The tests inspect the static files on disk; they do not invoke the
agent.  These artifacts are the deliverable.
"""
from __future__ import annotations

import os
import re
import unittest

import yaml


# ── Project paths ───────────────────────────────────────────────────────────

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'),
)
PROJECT_AGENTS = os.path.join(REPO_ROOT, '.teaparty', 'project', 'agents')
PROJECT_SKILLS = os.path.join(REPO_ROOT, '.teaparty', 'project', 'skills')

AGENT_DIR = os.path.join(PROJECT_AGENTS, 'scrum-master')
AGENT_MD = os.path.join(AGENT_DIR, 'agent.md')
AGENT_SETTINGS = os.path.join(AGENT_DIR, 'settings.yaml')

# The seven skills the issue specifies, in declaration order.  Exact
# names — directory and frontmatter ``name:`` must both match.
EXPECTED_SKILLS = (
    'sprint-plan',
    'prioritize',
    'refresh-board',
    'mark-in-progress',
    'mark-done',
    'add-to-backlog',
    'archive-sprint',
)

STATE_CHANGE_SKILLS = (
    'prioritize',
    'mark-in-progress',
    'mark-done',
    'add-to-backlog',
)


_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)\Z', re.DOTALL)


def _read_frontmatter_and_body(path: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and return ``(frontmatter, body)``.

    Asserts (via the caller) that the file starts with ``---`` and has
    a closing ``---`` — every agent.md and SKILL.md in the project
    catalog uses this convention, so missing frontmatter is a defect.
    """
    with open(path) as fh:
        content = fh.read()
    m = _FRONTMATTER_RE.match(content)
    if not m:
        raise AssertionError(
            f'{path} is missing YAML frontmatter (must start with --- and '
            f'have a closing --- before the body)'
        )
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _skill_path(name: str) -> str:
    return os.path.join(PROJECT_SKILLS, name, 'SKILL.md')


# ── 1. Agent definition ────────────────────────────────────────────────────

class TestScrumMasterAgentDefinition(unittest.TestCase):
    """The agent.md and settings.yaml at .teaparty/project/agents/scrum-master/."""

    def test_agent_directory_exists(self):
        """AC1: agent definition lives in the project catalog, not .claude/.

        The user explicitly required project-catalog placement; the file
        layout is the contract that future loaders walk.
        """
        self.assertTrue(
            os.path.isdir(AGENT_DIR),
            f'expected scrum-master agent directory at {AGENT_DIR}',
        )

    def test_agent_md_exists(self):
        self.assertTrue(
            os.path.isfile(AGENT_MD),
            f'expected agent definition at {AGENT_MD}',
        )

    def test_agent_settings_exists(self):
        self.assertTrue(
            os.path.isfile(AGENT_SETTINGS),
            f'expected agent settings at {AGENT_SETTINGS}',
        )

    def test_agent_frontmatter_name_matches_directory(self):
        """The frontmatter ``name:`` is the routing key; mismatched
        name vs. directory silently breaks ``GetAgent`` lookups."""
        fm, _ = _read_frontmatter_and_body(AGENT_MD)
        self.assertEqual(
            fm.get('name'), 'scrum-master',
            f'agent.md frontmatter name must equal the directory name '
            f'"scrum-master"; got {fm.get("name")!r}',
        )

    def test_agent_description_states_purpose(self):
        """AC1: the description must communicate WHEN to invoke this
        agent.  ``description`` is what every dispatcher matches against
        — vague phrasing means callers can't decide if it applies."""
        fm, _ = _read_frontmatter_and_body(AGENT_MD)
        desc = (fm.get('description') or '').lower()
        self.assertIn(
            'sprint', desc,
            f'agent description must mention sprint; got {fm.get("description")!r}',
        )
        # The user spelled the purpose out: "execute sprint workflows
        # and provide status reports".  Both halves are required so the
        # description doesn't reduce to "sprint stuff".
        self.assertTrue(
            'workflow' in desc or 'execute' in desc,
            f'agent description must convey "execute sprint workflows"; '
            f'got {fm.get("description")!r}',
        )
        self.assertIn(
            'status', desc,
            f'agent description must convey "status reports"; '
            f'got {fm.get("description")!r}',
        )

    def test_agent_skills_frontmatter_lists_exactly_seven(self):
        """AC2: the agent declares the seven skills the issue specifies,
        and no others.  An eighth skill silently broadens scope; a
        missing one means the agent can't perform a documented duty."""
        fm, _ = _read_frontmatter_and_body(AGENT_MD)
        skills = fm.get('skills')
        self.assertIsInstance(
            skills, list,
            f'agent.md frontmatter ``skills:`` must be a list; '
            f'got {type(skills).__name__}',
        )
        self.assertEqual(
            tuple(skills), EXPECTED_SKILLS,
            f'agent.md frontmatter ``skills:`` must list exactly '
            f'{list(EXPECTED_SKILLS)}; got {skills!r}',
        )

    def test_agent_settings_permits_required_io(self):
        """AC1: the agent needs file I/O for the cache and the github
        MCP tools for board/issue writes.  A missing entry here means
        the skill aborts with a permission error at runtime."""
        with open(AGENT_SETTINGS) as fh:
            settings = yaml.safe_load(fh) or {}
        allow = (settings.get('permissions') or {}).get('allow') or []
        # Strip permission patterns so ``Write(/path/**)`` matches "Write".
        bare = {entry.split('(', 1)[0].strip() for entry in allow}

        for tool in ('Read', 'Write', 'Edit', 'Glob', 'Grep'):
            self.assertIn(
                tool, bare,
                f'scrum-master settings.yaml must allow {tool}; '
                f'cache I/O depends on it.  Got allow list: {sorted(bare)}',
            )
        # MCP tools the seven skills call: list_milestones,
        # list_milestone_issues, list_project_boards, add_issue_to_board,
        # set_board_status, read_board_status, read_issue, create_comment.
        # Verify at least the board-mutating ones are allowed (all four
        # state-change skills go through one of these).
        for mcp_tool in (
            'mcp__teaparty-config__add_issue_to_board',
            'mcp__teaparty-config__set_board_status',
        ):
            self.assertIn(
                mcp_tool, bare,
                f'scrum-master settings.yaml must allow {mcp_tool}; '
                f'mark-* / add-to-backlog cannot mutate the board without it. '
                f'Got allow list: {sorted(bare)}',
            )


# ── 2. Skill definitions ───────────────────────────────────────────────────

class TestScrumMasterSkills(unittest.TestCase):
    """Each of the seven skills has a well-formed SKILL.md."""

    def test_each_skill_directory_exists(self):
        """AC2: every skill the issue lists has a SKILL.md on disk."""
        missing = [
            name for name in EXPECTED_SKILLS
            if not os.path.isfile(_skill_path(name))
        ]
        self.assertEqual(
            missing, [],
            f'missing SKILL.md for {missing}; '
            f'expected files at .teaparty/project/skills/<name>/SKILL.md',
        )

    def test_each_skill_frontmatter_name_matches_directory(self):
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                fm, _ = _read_frontmatter_and_body(_skill_path(name))
                self.assertEqual(
                    fm.get('name'), name,
                    f'{name}/SKILL.md frontmatter name must equal {name!r}; '
                    f'got {fm.get("name")!r}',
                )

    def test_each_skill_has_description(self):
        """A skill without a description can't be matched by the
        planning step — it becomes invisible to the agent."""
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                fm, _ = _read_frontmatter_and_body(_skill_path(name))
                desc = fm.get('description') or ''
                self.assertGreater(
                    len(desc.strip()), 0,
                    f'{name}/SKILL.md must declare a non-empty description',
                )


# ── 3. Wiring: agent.skills ↔ on-disk skill directories ────────────────────

class TestSkillsWiring(unittest.TestCase):
    """The agent's frontmatter ``skills:`` and the on-disk directory
    set must be identical.  Drift in either direction is a bug —
    a skill missing from frontmatter is unreachable; a skill listed
    in frontmatter without a directory raises at staging time."""

    def test_no_orphan_skill_directories(self):
        """Skill directories that aren't declared in the agent's
        ``skills:`` are orphans (or, for a future second agent, fine —
        but at this point in the tree only scrum-master uses
        ``.teaparty/project/skills/``)."""
        if not os.path.isdir(PROJECT_SKILLS):
            self.fail(
                f'{PROJECT_SKILLS} does not exist; sprint-plan and the '
                f'other six skills cannot be staged without it',
            )
        on_disk = sorted(
            d for d in os.listdir(PROJECT_SKILLS)
            if os.path.isfile(os.path.join(PROJECT_SKILLS, d, 'SKILL.md'))
        )
        self.assertEqual(
            sorted(on_disk), sorted(EXPECTED_SKILLS),
            f'.teaparty/project/skills/ must contain exactly the seven '
            f'scrum-master skills; got {on_disk}',
        )

    def test_agent_skills_frontmatter_matches_on_disk(self):
        fm, _ = _read_frontmatter_and_body(AGENT_MD)
        declared = set(fm.get('skills') or [])
        on_disk = {
            d for d in os.listdir(PROJECT_SKILLS)
            if os.path.isfile(os.path.join(PROJECT_SKILLS, d, 'SKILL.md'))
        } if os.path.isdir(PROJECT_SKILLS) else set()
        self.assertEqual(
            declared, on_disk,
            f'agent.md ``skills:`` ({sorted(declared)}) must equal the '
            f'on-disk skill set ({sorted(on_disk)}); drift means a skill '
            f'is either unreachable or missing',
        )


# ── 4. Body content: scope discipline + sync model ─────────────────────────

class TestSkillsContent(unittest.TestCase):
    """Each skill body encodes the contracts the issue specifies."""

    def test_state_change_skills_specify_github_first_then_cache(self):
        """AC4 (sync model): for every state-change skill, the body
        must order writes as ``GitHub first, then cache``.  The reverse
        order means a GitHub failure leaves cache and board diverged."""
        # We grep for ordered phrasing.  Either "github" appears before
        # "cache" in a sentence containing both, or the body explicitly
        # names the rule.  We accept either of two phrasings:
        #   - the literal phrase "GitHub first" (case-insensitive)
        #   - both "github" and "cache" mentioned, with "github"
        #     appearing before "cache" in the body
        for name in STATE_CHANGE_SKILLS:
            with self.subTest(skill=name):
                _, body = _read_frontmatter_and_body(_skill_path(name))
                low = body.lower()
                self.assertIn(
                    'github', low,
                    f'{name}/SKILL.md must reference GitHub writes; '
                    f'a state-change skill that never says github is '
                    f'unmoored from the sync model',
                )
                self.assertIn(
                    'cache', low,
                    f'{name}/SKILL.md must reference the cache; '
                    f'state-change skills update both halves',
                )
                gh_first = (
                    'github first' in low
                    or low.find('github') < low.find('cache')
                )
                self.assertTrue(
                    gh_first,
                    f'{name}/SKILL.md must order writes GitHub-first '
                    f'then cache; reversed order can leave cache and '
                    f'board diverged on GitHub failure',
                )

    def test_archive_sprint_does_not_close_milestone(self):
        """AC: ``archive-sprint`` archives the local cache only — it
        must explicitly NOT close the GitHub milestone (per issue:
        "do not close the milestone — that's a human decision")."""
        _, body = _read_frontmatter_and_body(_skill_path('archive-sprint'))
        low = body.lower()
        # Negative-space assertion: closing the milestone is forbidden.
        # The body must say so explicitly so a reviewer (or an agent
        # editing the skill) sees the rule.
        self.assertTrue(
            'do not close' in low or "don't close" in low or 'not close' in low,
            'archive-sprint/SKILL.md must explicitly forbid closing the '
            'milestone (the issue calls this out as a human decision)',
        )
        self.assertIn(
            'milestone', low,
            'archive-sprint/SKILL.md must mention the milestone in the '
            'context of the do-not-close rule',
        )

    def test_agent_body_states_mechanics_only_scope(self):
        """AC5: the agent body must spell out that tier analysis,
        dependency reasoning, and design judgment are NOT in scope.
        Without this, future skill authors will quietly broaden scope."""
        _, body = _read_frontmatter_and_body(AGENT_MD)
        low = body.lower()
        # The agent body must explicitly disclaim at least the three
        # exclusions the issue calls out.  We check for the keywords
        # plus a "do not" / "not" / "out of scope" framing nearby.
        for forbidden in ('tier', 'dependency', 'design'):
            self.assertIn(
                forbidden, low,
                f'agent.md must address the "{forbidden}" exclusion '
                f'(scope discipline is the whole point of this agent)',
            )
        # Negative framing: at least one "do not" / "not" / "no" near
        # the scope discussion.  We grep for the literal phrasing the
        # issue uses ("does NOT") and accept lower-case variants.
        self.assertTrue(
            'do not' in low or 'does not' in low or 'not in scope' in low
            or 'out of scope' in low,
            'agent.md must explicitly negate the out-of-scope items '
            '(tier analysis, dependency reasoning, design judgment); '
            'positive description alone leaves scope ambiguous',
        )

    def test_agent_body_states_when_to_use(self):
        """User-explicit requirement: the body must give the agent
        unambiguous signals for when to engage.  The user said:
        "expand definition so agent will know unambiguously when to use it"."""
        _, body = _read_frontmatter_and_body(AGENT_MD)
        low = body.lower()
        self.assertIn(
            'when to use', low,
            'agent.md must contain a "When to use" section; the user '
            'explicitly required unambiguous when-to-engage guidance',
        )


# ── 5. State schema ────────────────────────────────────────────────────────

class TestStateSchema(unittest.TestCase):
    """The cache schema is a long-lived artifact; ``sprint-plan`` must
    document it so downstream consumers don't read inconsistent files."""

    def test_sprint_plan_documents_cache_layout(self):
        """AC3: ``sprint-plan`` writes the three artifacts the issue
        names: ``sprint.yaml``, ``index.md``, ``issues/{N}.md``.  Each
        must be named in the body so a reader (human or agent) knows
        the schema."""
        _, body = _read_frontmatter_and_body(_skill_path('sprint-plan'))
        for required_artifact in ('sprint.yaml', 'index.md', 'issues/'):
            self.assertIn(
                required_artifact, body,
                f'sprint-plan/SKILL.md must name {required_artifact!r} as '
                f'one of the three cache artifacts it writes; the schema '
                f'is the contract for every reader of the cache',
            )

    def test_sprint_plan_documents_index_columns(self):
        """``index.md`` is the fast-lookup file; the issue specifies
        its columns as ``issue # | title | status | tier | wave``.  Drift
        in column set means status reports built on top read different
        fields than refresh-board writes."""
        _, body = _read_frontmatter_and_body(_skill_path('sprint-plan'))
        low = body.lower()
        # The five required columns must all be named in the body.
        for column in ('issue', 'title', 'status', 'tier', 'wave'):
            self.assertIn(
                column, low,
                f'sprint-plan/SKILL.md must document the index.md '
                f'``{column}`` column (the issue pins these five '
                f'columns by name)',
            )


if __name__ == '__main__':
    unittest.main()
