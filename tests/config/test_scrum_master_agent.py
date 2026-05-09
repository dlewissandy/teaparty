"""Tests for the scrum-master project agent (issue #429).

Layered:
  1. Agent definition — agent.md frontmatter + settings.yaml shape
  2. Skill definitions — SKILL.md files for each of the seven skills
  3. Wiring — the agent's ``skills:`` frontmatter matches the on-disk
     skill directory exactly (no orphans, no missing) AND each skill's
     ``allowed-tools`` is a subset of the agent's allow list
  4. Body content — the agent.md and skill bodies encode the scope
     discipline and sync model the issue specifies (mechanics only,
     GitHub-first then cache, no tier judgment)
  5. State schema — ``sprint-plan`` documents the cache layout
     (``sprint.yaml``, ``index.md`` columns parsed from the table
     header, per-issue file frontmatter schema and section headers)
  6. Per-skill contracts — tier→status mapping in prioritize,
     read-mostly nature of sprint-plan, archive-sprint forbids
     milestone closure

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
    'refresh-board',
)

# MCP tools any skill body or allowed-tools list may reference.  The
# expected union of all skills' allowed-tools is the agent's MCP
# allow list — we enumerate it here so the permission test covers
# every tool, not just two of them.
ALL_BOARD_MCP_TOOLS = (
    'mcp__teaparty-config__list_milestones',
    'mcp__teaparty-config__list_milestone_issues',
    'mcp__teaparty-config__read_issue',
    'mcp__teaparty-config__list_project_boards',
    'mcp__teaparty-config__add_issue_to_board',
    'mcp__teaparty-config__set_board_status',
    'mcp__teaparty-config__read_board_status',
)

# Built-in tools the agent and its skills may legitimately use.
BUILTIN_TOOLS = ('Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash')


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


def _skill_allowed_tools(name: str) -> list[str]:
    """Parse a skill's ``allowed-tools`` frontmatter into a list."""
    fm, _ = _read_frontmatter_and_body(_skill_path(name))
    raw = fm.get('allowed-tools') or ''
    if isinstance(raw, list):
        return [str(s).strip() for s in raw]
    return [s.strip() for s in str(raw).split(',') if s.strip()]


def _agent_bare_allow() -> set[str]:
    """The agent's allow list with permission patterns stripped."""
    with open(AGENT_SETTINGS) as fh:
        settings = yaml.safe_load(fh) or {}
    allow = (settings.get('permissions') or {}).get('allow') or []
    return {entry.split('(', 1)[0].strip() for entry in allow}


def _normalize_apostrophes(s: str) -> str:
    """Replace fancy apostrophes with ASCII so substring checks work."""
    return s.replace('’', "'").replace('‘', "'")


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

    def test_agent_operational_frontmatter(self):
        """AC: ``model`` and ``maxTurns`` are operational contracts.
        Bumping the agent to opus changes cost; removing ``maxTurns``
        removes the runaway-loop guard.  Both must be pinned."""
        fm, _ = _read_frontmatter_and_body(AGENT_MD)
        self.assertEqual(
            fm.get('model'), 'sonnet',
            f'agent.md must declare ``model: sonnet`` (cost discipline); '
            f'got {fm.get("model")!r}',
        )
        self.assertIsInstance(
            fm.get('maxTurns'), int,
            f'agent.md must declare an integer ``maxTurns`` to bound '
            f'runaway loops; got {fm.get("maxTurns")!r}',
        )
        self.assertGreaterEqual(
            fm.get('maxTurns', 0), 1,
            f'agent.md ``maxTurns`` must be >= 1; got {fm.get("maxTurns")!r}',
        )

    def test_agent_settings_permits_every_required_tool(self):
        """AC1: every MCP tool referenced by any skill — and the file
        I/O tools the cache needs — must appear in the agent's allow
        list.  A missing entry aborts the relevant skill at runtime."""
        bare = _agent_bare_allow()

        for tool in BUILTIN_TOOLS:
            self.assertIn(
                tool, bare,
                f'scrum-master settings.yaml must allow {tool}; '
                f'cache I/O depends on it (archive-sprint uses Bash for '
                f'``mv`` to move the cache to the archive directory).  '
                f'Got allow list: {sorted(bare)}',
            )
        # Every github MCP tool the skills can call.  Stripping any one
        # of these silently breaks at least one skill at runtime; the
        # tests must reject that.
        for mcp_tool in ALL_BOARD_MCP_TOOLS:
            self.assertIn(
                mcp_tool, bare,
                f'scrum-master settings.yaml must allow {mcp_tool}; '
                f'at least one of the seven skills calls it.  '
                f'Got allow list: {sorted(bare)}',
            )

    def test_agent_settings_has_no_unused_permissions(self):
        """AC: the allow list must not include MCP tools that no skill
        uses.  Over-broad permissions invite a future skill author to
        reach for a tool the agent has no documented reason to invoke,
        which is scope-broadening through the back door."""
        bare = _agent_bare_allow()
        agent_mcp = {p for p in bare if p.startswith('mcp__')}
        skill_mcp: set[str] = set()
        for name in EXPECTED_SKILLS:
            for tool in _skill_allowed_tools(name):
                if tool.startswith('mcp__'):
                    skill_mcp.add(tool)
        unused = agent_mcp - skill_mcp
        self.assertEqual(
            unused, set(),
            f'scrum-master settings.yaml allows MCP tools no skill '
            f'declares in its ``allowed-tools``: {sorted(unused)}.  '
            f'Either a skill should call it or the permission should '
            f'be removed (mechanics-only discipline).',
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

    def test_each_skill_description_is_substantive(self):
        """A skill description is what the planning step matches against
        to decide whether to invoke the skill.  A one-character or
        single-word description satisfies a length-greater-than-zero
        check but is useless for matching, so we require a substantive
        description (>= 40 chars).  Skill descriptions describe what
        the skill does using semantic verbs ("Bootstrap", "Apply",
        "Move"); requiring the literal skill-name token would be
        overreach — dispatchers match on capability, not on echoing
        the name back."""
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                fm, _ = _read_frontmatter_and_body(_skill_path(name))
                desc = (fm.get('description') or '').strip()
                self.assertGreaterEqual(
                    len(desc), 40,
                    f'{name}/SKILL.md description must be substantive '
                    f'(>= 40 chars); got {len(desc)} chars: {desc!r}',
                )

    def test_each_skill_is_not_user_invocable(self):
        """AC: every scrum-master skill is reached via the agent, not
        by typing ``/<name>`` at a user prompt.  Flipping
        ``user-invocable: true`` makes the skill discoverable to any
        caller and breaks the agent's ownership of its mechanics."""
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                fm, _ = _read_frontmatter_and_body(_skill_path(name))
                self.assertEqual(
                    fm.get('user-invocable'), False,
                    f'{name}/SKILL.md frontmatter must declare '
                    f'``user-invocable: false``; this is the routing '
                    f'contract that says the skill is reached only via '
                    f'the scrum-master agent.  Got '
                    f'{fm.get("user-invocable")!r}.',
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

    def test_each_skill_allowed_tools_is_subset_of_agent_allow(self):
        """AC: at runtime every skill executes under the agent's
        permissions.  Any tool a skill declares in ``allowed-tools``
        must appear in the agent's allow list, or the skill aborts
        the first time it reaches that tool."""
        agent_allow = _agent_bare_allow()
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                tools = _skill_allowed_tools(name)
                missing = [t for t in tools if t not in agent_allow]
                self.assertEqual(
                    missing, [],
                    f'{name}/SKILL.md declares {missing!r} in '
                    f'allowed-tools, but the agent does not permit '
                    f'them.  Either add the tool to '
                    f'.teaparty/project/agents/scrum-master/settings.yaml '
                    f'or remove it from the skill.',
                )


# ── 4. Body content: scope discipline + sync model ─────────────────────────

class TestSkillsContent(unittest.TestCase):
    """Each skill body encodes the contracts the issue specifies."""

    def test_state_change_skills_specify_github_first_then_cache(self):
        """AC4 (sync model): for every state-change skill, the body
        must contain the literal phrase ``GitHub first`` (case-
        insensitive).  Requiring the canonical phrase is a documentation
        contract; positional substring checks are too permissive — they
        can be satisfied by an incidental mention of GitHub above the
        first ``cache`` mention even when the procedure itself reverses
        the order."""
        for name in STATE_CHANGE_SKILLS:
            with self.subTest(skill=name):
                _, body = _read_frontmatter_and_body(_skill_path(name))
                low = body.lower()
                self.assertIn(
                    'github first', low,
                    f'{name}/SKILL.md must contain the literal phrase '
                    f'"GitHub first" (case-insensitive) so the sync '
                    f'rule is encoded as a documentation contract.  '
                    f'Reversed write order leaves cache and board '
                    f'diverged on a transient GitHub failure.',
                )
                self.assertIn(
                    'cache', low,
                    f'{name}/SKILL.md must reference the cache; '
                    f'state-change skills update both halves',
                )

    def test_archive_sprint_milestone_rule_is_co_located(self):
        """AC: ``archive-sprint`` must explicitly forbid milestone
        closure.  We require the negative phrase to co-occur with
        ``milestone`` in the same paragraph — independent presence
        of the two is too loose."""
        _, body = _read_frontmatter_and_body(_skill_path('archive-sprint'))
        low = _normalize_apostrophes(body.lower())
        # Split on blank lines (paragraph boundary).
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', low) if p.strip()]
        co_located = any(
            'milestone' in p
            and ('do not close' in p or "don't close" in p or 'not close' in p)
            for p in paragraphs
        )
        self.assertTrue(
            co_located,
            'archive-sprint/SKILL.md must contain a paragraph that '
            'states "do not close the milestone" (or equivalent) — '
            'the negative phrase and "milestone" must appear in the '
            'same paragraph so a reader sees the rule together.  '
            'Independent presence of the two words across the body '
            'is too loose; the rule could be deleted while the words '
            'still occur incidentally.',
        )

    def test_agent_body_co_locates_each_exclusion_with_negative_framing(self):
        """AC5 (mechanics-only scope): each forbidden topic — tier,
        dependency, design — must appear in a paragraph that contains
        a negative framing.  Independent presence of the topic word
        and a negative phrase is too loose: ``tier`` appears in
        positive contexts (Tier 1 → Approved) and the negative phrase
        could refer to something else entirely."""
        _, body = _read_frontmatter_and_body(AGENT_MD)
        low = _normalize_apostrophes(body.lower())
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', low) if p.strip()]
        negative_phrases = ('do not', 'does not', 'not in scope', 'out of scope')
        for forbidden in ('tier', 'dependency', 'design'):
            with self.subTest(exclusion=forbidden):
                neg_paragraphs = [
                    p for p in paragraphs
                    if any(neg in p for neg in negative_phrases)
                    and forbidden in p
                ]
                self.assertGreater(
                    len(neg_paragraphs), 0,
                    f'agent.md must have at least one paragraph that '
                    f'co-locates "{forbidden}" with a negative framing '
                    f'(do not / does not / not in scope / out of scope).  '
                    f'Without co-location, the rule is undefended: the '
                    f'exclusion bullet could be rewritten in the '
                    f'affirmative or deleted while the keywords still '
                    f'occur elsewhere.',
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

    def test_agent_body_states_cache_is_read_source_of_truth(self):
        """AC4 (sync model — read half): the issue specifies that
        ``cached reads (the cache is the source of truth for everyone
        reading sprint state)``.  The agent body must encode this so
        a future skill author knows not to bypass the cache by
        re-querying GitHub on every status question."""
        _, body = _read_frontmatter_and_body(AGENT_MD)
        low = body.lower()
        # The body must have a paragraph that states reads come from
        # the cache and that the cache is the source of truth.
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', low) if p.strip()]
        read_paragraphs = [
            p for p in paragraphs
            if 'read' in p and 'cache' in p and 'source of truth' in p
        ]
        self.assertGreater(
            len(read_paragraphs), 0,
            'agent.md must contain a paragraph that names reads, the '
            'cache, and "source of truth" together — the read half of '
            'the sync model.  Without this, a future skill author can '
            'silently flip status reports to re-query GitHub on every '
            'question, undoing the design rationale of "centralizing '
            'reads against a local cache keeps GitHub API traffic flat '
            'as the team scales".',
        )


# ── 5. State schema ────────────────────────────────────────────────────────

class TestStateSchema(unittest.TestCase):
    """The cache schema is a long-lived artifact; ``sprint-plan`` must
    document it so downstream consumers don't read inconsistent files."""

    def test_sprint_plan_documents_cache_layout(self):
        """AC3: ``sprint-plan`` writes the three artifacts the issue
        names: ``sprint.yaml``, ``index.md``, ``issues/{N}.md``.  Each
        must be named in the body."""
        _, body = _read_frontmatter_and_body(_skill_path('sprint-plan'))
        for required_artifact in ('sprint.yaml', 'index.md', 'issues/'):
            self.assertIn(
                required_artifact, body,
                f'sprint-plan/SKILL.md must name {required_artifact!r} as '
                f'one of the three cache artifacts it writes; the schema '
                f'is the contract for every reader of the cache',
            )

    def test_sprint_plan_documents_index_columns_in_table_header(self):
        """AC3: the issue pins the index.md columns by name and order:
        ``issue # | title | status | tier | wave``.  We parse the
        markdown table inside the body and assert the header cells
        exactly — substring checks pass on incidental prose mentions
        of these words and don't catch reordering or renaming."""
        _, body = _read_frontmatter_and_body(_skill_path('sprint-plan'))
        # Find the first markdown table whose header row contains
        # ``tier`` and ``wave`` — that's the index.md schema example.
        # A markdown table is a header line, a separator (|---|), and
        # one or more data rows.
        header_re = re.compile(r'^\|(.+)\|\s*$', re.MULTILINE)
        headers = header_re.findall(body)
        index_header = None
        for h in headers:
            cells = [c.strip().lower() for c in h.split('|')]
            if 'tier' in cells and 'wave' in cells:
                index_header = cells
                break
        self.assertIsNotNone(
            index_header,
            'sprint-plan/SKILL.md must include a markdown table whose '
            'header documents the index.md columns (it must contain '
            '``tier`` and ``wave``).  Found no such table in the body.',
        )
        expected = ['issue #', 'title', 'status', 'tier', 'wave']
        self.assertEqual(
            index_header, expected,
            f'sprint-plan/SKILL.md index.md table header must be '
            f'exactly {expected} in this order; got {index_header}.  '
            f'Drift in the column set means status reports built on '
            f'top read different fields than refresh-board writes.',
        )

    def test_sprint_plan_documents_per_issue_file_schema(self):
        """AC3 (per-issue file schema): ``issues/{N}.md`` carries
        frontmatter the mark-* and prioritize skills read and write,
        plus the two sections the self-review tightening pinned
        (``Issue body`` snapshot + ``Triage notes``).  Drift here
        means refresh-board reads diverge from add-to-backlog writes."""
        _, body = _read_frontmatter_and_body(_skill_path('sprint-plan'))
        low = body.lower()
        # Required frontmatter keys for the per-issue file.  Each must
        # appear in the schema example in the body.
        for key in ('number', 'title', 'state', 'labels', 'status', 'tier', 'wave'):
            self.assertIn(
                f'{key}:', low,
                f'sprint-plan/SKILL.md must document the per-issue file '
                f'frontmatter key ``{key}`` (other skills read and write '
                f'this field).',
            )
        # The two body section headers from the self-review tightening.
        self.assertIn(
            'issue body', low,
            'sprint-plan/SKILL.md must document the "Issue body '
            '(planning-time snapshot)" section header in the per-issue '
            'file schema (refresh-board contract: the snapshot is frozen).',
        )
        self.assertIn(
            'triage notes', low,
            'sprint-plan/SKILL.md must document the "Triage notes" '
            'section header in the per-issue file schema (refresh-board '
            'contract: the notes are human-owned, never overwritten).',
        )


# ── 6. Per-skill contracts ─────────────────────────────────────────────────

class TestPerSkillContracts(unittest.TestCase):
    """The logical contracts of individual skills the issue pins."""

    def test_prioritize_documents_tier_to_status_mapping(self):
        """AC: ``prioritize`` applies the issue's mapping:
        Tier 1 → Approved, others → Backlog, Won't-Do → Won't Do.
        This is the load-bearing logical contract of the skill;
        rewriting the mapping is exactly the kind of mistake a
        sprint-mechanics agent must not silently introduce."""
        _, body = _read_frontmatter_and_body(_skill_path('prioritize'))
        low = _normalize_apostrophes(body.lower())
        # Tier 1 must map to Approved.  We require both tokens to
        # co-occur in the same paragraph or the same line to defend
        # against re-mapping that keeps both words in the body.
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', low) if p.strip()]

        def _has_co(word_a: str, word_b: str) -> bool:
            return any(word_a in p and word_b in p for p in paragraphs)

        self.assertTrue(
            _has_co('tier 1', 'approved'),
            'prioritize/SKILL.md must document Tier 1 → Approved in '
            'a paragraph that co-locates "tier 1" with "approved".  '
            'This is the load-bearing logical contract of prioritize.',
        )
        self.assertTrue(
            _has_co('backlog', 'tier'),
            'prioritize/SKILL.md must document tier ≥ 2 → Backlog '
            '(a paragraph co-locating "backlog" with "tier").',
        )
        self.assertIn(
            "won't do", low,
            'prioritize/SKILL.md must name "Won\'t Do" as the third '
            'mapping option (the issue specifies it as a tier-override).',
        )

    def test_sprint_plan_is_read_mostly(self):
        """AC: ``sprint-plan`` is read-mostly — it must not mutate the
        GitHub board.  Adding ``set_board_status`` or ``add_issue_to_board``
        to its allowed-tools is exactly the kind of regression that
        would conflate planning with prioritization (out of scope)."""
        tools = set(_skill_allowed_tools('sprint-plan'))
        for forbidden in (
            'mcp__teaparty-config__set_board_status',
            'mcp__teaparty-config__add_issue_to_board',
        ):
            self.assertNotIn(
                forbidden, tools,
                f'sprint-plan/SKILL.md allowed-tools must NOT include '
                f'{forbidden!r}; sprint-plan is read-mostly and must '
                f'not mutate the GitHub board.  Tier and status writes '
                f'belong to prioritize, mark-*, and add-to-backlog.',
            )

    def test_archive_sprint_does_not_close_milestone(self):
        """AC: ``archive-sprint`` archives the local cache only — it
        must explicitly NOT close the GitHub milestone.  This is
        retained as a stand-alone test for visibility; the stricter
        co-location check lives in TestSkillsContent."""
        _, body = _read_frontmatter_and_body(_skill_path('archive-sprint'))
        low = _normalize_apostrophes(body.lower())
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


if __name__ == '__main__':
    unittest.main()
