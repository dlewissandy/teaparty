"""Scratch file lifecycle — orchestrator-written .context/ working memory.

The orchestrator extracts important content from the stream into scratch
files as it flows by, so agents can compact aggressively without losing
decisions, human input, or dead ends.

Design reference: docs/proposals/context-budget/proposal.md
Example scratch file: docs/proposals/context-budget/examples/scratch-file.md
Extraction patterns: docs/proposals/context-budget/references/extraction-patterns.md
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime


# File modification tool names that represent artifact changes.
_FILE_MOD_TOOLS = frozenset({'Write', 'Edit'})

# Maximum lines for scratch.md render output.
_MAX_RENDER_LINES = 200


@dataclass
class ScratchModel:
    """In-memory model of extracted content for a job/task.

    The orchestrator feeds stream events via :meth:`extract`.
    The model is serialized to ``{worktree}/.context/scratch.md``
    via :class:`ScratchWriter` at turn boundaries.
    """

    job: str = ''
    phase: str = ''

    human_inputs: list[str] = field(default_factory=list)
    state_changes: list[dict] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)

    def extract(self, event: dict) -> None:
        """Extract content from a stream-json event.

        Only mechanically extractable categories are handled:
        - ``user`` events → human input
        - ``system``/``state_changed`` events → CfA transitions
        - ``tool_use`` Write/Edit events → file modifications
        """
        etype = event.get('type', '')

        if etype == 'user':
            msg = event.get('message', {})
            content = msg.get('content', '') if isinstance(msg, dict) else ''
            if content:
                self.human_inputs.append(content)
            return

        if etype == 'system' and event.get('subtype') == 'state_changed':
            self.state_changes.append({
                'from': event.get('from', ''),
                'to': event.get('to', ''),
            })
            return

        if etype == 'tool_use' and event.get('name') in _FILE_MOD_TOOLS:
            inp = event.get('input', {})
            path = inp.get('file_path', '')
            if path and path not in self.artifacts:
                self.artifacts.append(path)
            return

    def add_dead_end(self, description: str) -> None:
        """Record a failed approach."""
        self.dead_ends.append(description)

    def render(self) -> str:
        """Render the scratch file as markdown, kept under 200 lines.

        Produces a concise index with pointers to detail files,
        following the progressive disclosure pattern.
        """
        lines: list[str] = []
        lines.append(f'# Job: {self.job}')
        lines.append(f'Phase: {self.phase}')
        lines.append(f'Updated: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
        lines.append('')

        # Budget for each section — leave room for headers and spacing.
        # Reserve lines for structure: ~10 lines for headers/spacing.
        budget = _MAX_RENDER_LINES - 10
        section_budget = max(budget // 4, 10)

        if self.human_inputs:
            lines.append('## Human Input')
            count = len(self.human_inputs)
            shown = self.human_inputs[-section_budget:]
            for i, msg in enumerate(shown, start=count - len(shown) + 1):
                # Truncate long messages to one line.
                summary = msg[:120].replace('\n', ' ')
                lines.append(f'- #{i}: {summary}')
            lines.append(f'{count} interactions recorded \u2192 .context/human-input.md')
            lines.append('')

        if self.state_changes:
            lines.append('## State Changes')
            shown = self.state_changes[-section_budget:]
            for sc in shown:
                lines.append(f'- {sc["from"]} \u2192 {sc["to"]}')
            lines.append('')

        if self.dead_ends:
            lines.append('## Dead Ends')
            shown = self.dead_ends[-section_budget:]
            for i, de in enumerate(shown, start=1):
                summary = de[:120].replace('\n', ' ')
                lines.append(f'- #{i}: {summary}')
            lines.append(f'\u2192 .context/dead-ends.md')
            lines.append('')

        if self.artifacts:
            lines.append('## Artifacts')
            shown = self.artifacts[-section_budget:]
            for path in shown:
                lines.append(f'- {path}')
            lines.append('')

        # Final safety: hard-truncate to 200 lines.
        if len(lines) > _MAX_RENDER_LINES:
            lines = lines[:_MAX_RENDER_LINES - 1]
            lines.append('(truncated)')

        return '\n'.join(lines)


class ScratchWriter:
    """Serializes a ScratchModel to the ``.context/`` directory.

    The orchestrator is the sole writer.  Agents only read.
    """

    def __init__(self, worktree: str) -> None:
        self._worktree = worktree
        self._context_dir = os.path.join(worktree, '.context')

    def _ensure_dir(self) -> None:
        os.makedirs(self._context_dir, exist_ok=True)

    def write_scratch(self, model: ScratchModel) -> None:
        """Rewrite scratch.md atomically (temp file + rename)."""
        self._ensure_dir()
        content = model.render()
        scratch_path = os.path.join(self._context_dir, 'scratch.md')

        # Atomic write: write to temp file in same directory, then rename.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._context_dir, prefix='.scratch_', suffix='.tmp',
        )
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            os.replace(tmp_path, scratch_path)
        except BaseException:
            # Clean up temp file on failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def append_human_input(self, text: str) -> None:
        """Append a human message to the detail file."""
        self._ensure_dir()
        path = os.path.join(self._context_dir, 'human-input.md')
        with open(path, 'a') as f:
            f.write(f'\n---\n{text}\n')

    def append_dead_end(self, description: str) -> None:
        """Append a dead end to the detail file."""
        self._ensure_dir()
        path = os.path.join(self._context_dir, 'dead-ends.md')
        with open(path, 'a') as f:
            f.write(f'\n---\n{description}\n')

    def cleanup(self) -> None:
        """Remove the entire .context/ directory."""
        if os.path.exists(self._context_dir):
            shutil.rmtree(self._context_dir)
