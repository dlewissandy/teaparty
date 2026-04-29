"""Regression: every project-scope leaf agent has a settings.yaml that
declares the tools its prompt names (issue #423 follow-on).

Without per-agent settings.yaml, ``_load_agent_tools`` returns ``None``,
the MCP ``tools/list`` filter falls into pass-through (advertises every
tool the server has), but ``--tools`` only contains scope-base + baseline.
The agent sees tools it cannot invoke; calls fall to the permission-
prompt path and stall.

Live joke-book runs surfaced this as 23 permission failures on
``mcp__teaparty-config__semantic_scholar_search`` etc. when the
project ``arxiv-researcher`` (no settings.yaml) tried tools the
project's pass-through MCP filter advertised.

The contract this test pins:

1. Every project-scope leaf agent (everything under
   ``.teaparty/project/agents/`` that isn't a lead) has a
   ``settings.yaml`` with a non-empty ``permissions.allow``.

2. The agent's prompt-named tools (heuristically: tool names that
   appear in the agent.md body) are present in its allow list.
   Catches drift where a prompt says *"use WebSearch"* but
   ``settings.yaml`` doesn't grant it.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Tools the agent prompt may name explicitly. Maps the prompt token
# to the settings.yaml allow-list entry that grants it.
PROMPT_TO_PERMISSION: dict[str, str] = {
    'WebSearch': 'WebSearch',
    'WebFetch': 'WebFetch',
    'Bash': 'Bash',
    'Read': 'Read',
    'Write': 'Write',
    'Edit': 'Edit',
    'Glob': 'Glob',
    'Grep': 'Grep',
    'curl': 'Bash',  # curl is invoked via Bash
}

# Agents to skip from the leaf scan: anything matching these is a
# lead (covered by lead role tests) or a non-agent directory.
SKIP_NAMES: set[str] = set()  # per-name skip handled by the -lead suffix


class LeafAgentSettingsCompletenessTest(unittest.TestCase):
    """Every project-scope leaf agent has a complete settings.yaml."""

    def setUp(self) -> None:
        self.leaves: list[Path] = []
        for d in (REPO_ROOT / '.teaparty/project/agents').iterdir():
            if not d.is_dir():
                continue
            if '-lead' in d.name:
                continue
            if d.name in SKIP_NAMES:
                continue
            if not (d / 'agent.md').is_file():
                continue
            self.leaves.append(d)
        # Sanity: there are several leaf agents to test.
        self.assertGreater(
            len(self.leaves), 5,
            f'Expected to find multiple project leaf agents at '
            f'.teaparty/project/agents/. Got {len(self.leaves)}.',
        )

    def test_every_leaf_has_settings_yaml(self) -> None:
        """Each leaf has its own settings.yaml — the source of the
        agent's permissions.allow whitelist."""
        missing = [
            d.name for d in self.leaves
            if not (d / 'settings.yaml').is_file()
        ]
        self.assertEqual(
            missing, [],
            f'Project-scope leaf agents missing settings.yaml: '
            f'{missing}. Without settings.yaml the agent\'s '
            f'permissions.allow is empty; the MCP filter falls to '
            f'pass-through and the agent sees tools it cannot '
            f'invoke. Live joke-book runs hit this wall.',
        )

    def test_every_leaf_settings_has_non_empty_allow_list(self) -> None:
        """settings.yaml exists AND declares at least one tool — an
        empty allow list defeats the purpose of the file."""
        import yaml as _yaml
        empty: list[str] = []
        for d in self.leaves:
            f = d / 'settings.yaml'
            if not f.is_file():
                continue
            data = _yaml.safe_load(f.read_text()) or {}
            allow = (data.get('permissions') or {}).get('allow') or []
            if not allow:
                empty.append(d.name)
        self.assertEqual(
            empty, [],
            f'Project-scope leaf agents with empty permissions.allow: '
            f'{empty}. Settings.yaml must declare at least the tools '
            f'the agent\'s prompt names.',
        )

    def test_prompt_named_tools_present_in_allow(self) -> None:
        """For each leaf, scan the prompt for tool names; assert the
        corresponding allow-list entry exists. Catches drift where a
        prompt promises a tool that settings.yaml does not grant.

        Heuristic: only flag prompts that name a tool with capitalized
        identifier syntax (e.g., ``Use WebSearch to find...``).
        Avoids false positives on prose like ``write a clear prompt``.
        """
        import yaml as _yaml
        # Regex: capitalized identifier or a backtick-wrapped tool name.
        # Tightens the heuristic to avoid matching common English words.
        tool_pattern = re.compile(
            r'\b(?:Use|use)\s+(?:the\s+)?(WebSearch|WebFetch|Bash|Read|'
            r'Write|Edit|Glob|Grep|curl)\b'
        )

        gaps: list[tuple[str, str, str]] = []  # (agent, tool, permission)
        for d in self.leaves:
            agent_md = (d / 'agent.md').read_text()
            # Body only — skip frontmatter to avoid `tools:` field.
            body_start = agent_md.find('---', 3)
            body = agent_md[body_start + 3:] if body_start > -1 else agent_md

            tools_named = set(
                m.group(1) for m in tool_pattern.finditer(body)
            )
            if not tools_named:
                continue

            settings_path = d / 'settings.yaml'
            if not settings_path.is_file():
                # Covered by the previous test; don't double-report.
                continue
            data = _yaml.safe_load(settings_path.read_text()) or {}
            allow = (data.get('permissions') or {}).get('allow') or []
            allow_set = {a.split('(')[0].strip() for a in allow}

            for tool in tools_named:
                permission = PROMPT_TO_PERMISSION.get(tool)
                if permission is None:
                    continue
                if permission not in allow_set:
                    gaps.append((d.name, tool, permission))

        self.assertEqual(
            gaps, [],
            f'Prompt-named tools missing from settings.yaml '
            f'permissions.allow:\n' +
            '\n'.join(
                f'  {agent}: prompt names "{tool}" but allow list '
                f'lacks "{perm}"'
                for agent, tool, perm in gaps
            ),
        )


if __name__ == '__main__':
    unittest.main()
