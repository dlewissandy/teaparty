#!/usr/bin/env python3
"""Memory entry schema with YAML frontmatter for the POC learning subsystem.

Each memory entry has structured metadata (type, domain, importance, phase, etc.)
stored as YAML frontmatter followed by the learning content text.

Format:
    ---
    id: <uuid4>
    type: procedural
    domain: team
    importance: 0.7
    phase: specification
    status: active
    reinforcement_count: 0
    last_reinforced: '2026-03-01'
    created_at: '2026-03-01'
    ---
    ## [2026-03-01] Session Learning
    Content of the learning...

No external dependencies — uses stdlib only (re, uuid, datetime).
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ── Constants ──────────────────────────────────────────────────────────────────

VALID_TYPES = frozenset(['declarative', 'procedural', 'directive', 'corrective'])
VALID_DOMAINS = frozenset(['task', 'team'])
VALID_STATUSES = frozenset(['active', 'retired', 'compacted'])

REQUIRED_FIELDS = [
    'id', 'type', 'domain', 'importance', 'phase',
    'status', 'reinforcement_count', 'last_reinforced', 'created_at',
]


# ── Entry schema ───────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """A single learning entry with structured metadata."""
    id: str                    # uuid4 string
    type: str                  # declarative|procedural|directive|corrective
    domain: str                # task|team
    importance: float          # 0.0–1.0
    phase: str                 # project phase (e.g. 'specification', 'implementation')
    status: str                # active|retired|compacted
    reinforcement_count: int   # incremented when entry appears in retrieval
    last_reinforced: str       # ISO date string e.g. '2026-03-01'
    created_at: str            # ISO date string
    content: str               # the learning text (after frontmatter)
    session_id: str = ""       # originating session ID (e.g. 'session-20260309-064427')
    session_task: str = ""     # originating task description (truncated)
    promoted_from: str = ""    # scope this entry was promoted from (e.g. 'session')
    promoted_at: str = ""      # ISO date when promoted (e.g. '2026-03-26')


# ── Factory ────────────────────────────────────────────────────────────────────

def make_entry(
    content: str,
    type: str = 'procedural',
    domain: str = 'team',
    importance: float = 0.5,
    phase: str = 'unknown',
    session_id: str = '',
    session_task: str = '',
) -> MemoryEntry:
    """Create a new MemoryEntry with a fresh uuid4 id and today's date."""
    today = date.today().isoformat()
    return MemoryEntry(
        id=str(uuid.uuid4()),
        type=type if type in VALID_TYPES else 'procedural',
        domain=domain if domain in VALID_DOMAINS else 'team',
        importance=max(0.0, min(1.0, float(importance))),
        phase=phase or 'unknown',
        status='active',
        reinforcement_count=0,
        last_reinforced=today,
        created_at=today,
        content=content,
        session_id=session_id,
        session_task=session_task[:200] if session_task else '',
    )


# ── Frontmatter parsing ────────────────────────────────────────────────────────

def _parse_yaml_value(raw: str):
    """Parse a YAML scalar value — typed but no external yaml dependency."""
    v = raw.strip()
    # Strip surrounding quotes
    if (v.startswith("'") and v.endswith("'")) or \
       (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    # Boolean
    if v.lower() in ('true', 'yes'):
        return True
    if v.lower() in ('false', 'no'):
        return False
    # Integer
    try:
        return int(v)
    except ValueError:
        pass
    # Float
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_frontmatter(text: str) -> tuple:
    """Parse YAML frontmatter from '---\\nkey: val\\n---\\ncontent' format.

    Returns (metadata_dict, content_str).
    Raises ValueError if no valid frontmatter block found.
    """
    text = text.strip()
    if not text.startswith('---'):
        raise ValueError("No YAML frontmatter found (does not start with '---')")

    # Find the closing '---'
    lines = text.split('\n')
    close_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            close_idx = i
            break

    if close_idx is None:
        raise ValueError("Unclosed YAML frontmatter (no closing '---' found)")

    fm_lines = lines[1:close_idx]
    content_lines = lines[close_idx + 1:]

    metadata = {}
    for line in fm_lines:
        if not line.strip() or line.strip().startswith('#'):
            continue
        m = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if m:
            key = m.group(1)
            raw_val = m.group(2).strip()
            metadata[key] = _parse_yaml_value(raw_val)

    # Type coercion for known numeric fields
    if 'importance' in metadata:
        try:
            metadata['importance'] = float(metadata['importance'])
        except (TypeError, ValueError):
            metadata['importance'] = 0.5

    if 'reinforcement_count' in metadata:
        try:
            metadata['reinforcement_count'] = int(metadata['reinforcement_count'])
        except (TypeError, ValueError):
            metadata['reinforcement_count'] = 0

    content = '\n'.join(content_lines).strip()
    return metadata, content


# ── Serialization ──────────────────────────────────────────────────────────────

def serialize_entry(entry: MemoryEntry) -> str:
    """Serialize a MemoryEntry to YAML frontmatter + content text."""
    lines = [
        '---',
        f'id: {entry.id}',
        f'type: {entry.type}',
        f'domain: {entry.domain}',
        f'importance: {entry.importance}',
        f'phase: {entry.phase}',
        f'status: {entry.status}',
        f'reinforcement_count: {entry.reinforcement_count}',
        f"last_reinforced: '{entry.last_reinforced}'",
        f"created_at: '{entry.created_at}'",
    ]
    if entry.session_id:
        lines.append(f"session_id: '{entry.session_id}'")
    if entry.session_task:
        # Escape single quotes in task description
        safe_task = entry.session_task.replace("'", "''")
        lines.append(f"session_task: '{safe_task}'")
    if entry.promoted_from:
        lines.append(f"promoted_from: {entry.promoted_from}")
    if entry.promoted_at:
        lines.append(f"promoted_at: '{entry.promoted_at}'")
    lines.extend(['---', entry.content])
    return '\n'.join(lines)


# ── Single entry parsing ───────────────────────────────────────────────────────

def _default_entry(content: str) -> MemoryEntry:
    """Create a MemoryEntry with defaults from raw content (old-format fallback)."""
    today = date.today().isoformat()
    return MemoryEntry(
        id=str(uuid.uuid4()),
        type='procedural',
        domain='team',
        importance=0.5,
        phase='unknown',
        status='active',
        reinforcement_count=0,
        last_reinforced=today,
        created_at=today,
        content=content.strip(),
    )


def parse_entry(text: str) -> MemoryEntry:
    """Parse one frontmatter+content block into a MemoryEntry.

    Old-format entries (no YAML frontmatter) receive default values.
    Missing optional fields in frontmatter also receive defaults.
    """
    text = text.strip()
    if not text:
        return _default_entry('')

    today = date.today().isoformat()

    try:
        metadata, content = parse_frontmatter(text)
    except ValueError:
        # Old-format entry — no frontmatter
        return _default_entry(text)

    return MemoryEntry(
        id=str(metadata.get('id') or uuid.uuid4()),
        type=str(metadata.get('type', 'procedural')),
        domain=str(metadata.get('domain', 'team')),
        importance=float(metadata.get('importance', 0.5)),
        phase=str(metadata.get('phase', 'unknown')),
        status=str(metadata.get('status', 'active')),
        reinforcement_count=int(metadata.get('reinforcement_count', 0)),
        last_reinforced=str(metadata.get('last_reinforced', today)),
        created_at=str(metadata.get('created_at', today)),
        content=content,
        promoted_from=str(metadata.get('promoted_from', '')),
        promoted_at=str(metadata.get('promoted_at', '')),
    )


# ── Memory file parsing ────────────────────────────────────────────────────────

def parse_memory_file(text: str) -> list:
    """Split a full MEMORY.md file into individual MemoryEntry objects.

    Handles both old-format (## [date] header sections) and new YAML
    frontmatter entries. Entries are separated by '---' boundaries.

    Returns list of MemoryEntry. Empty or whitespace-only input returns [].
    """
    if not text or not text.strip():
        return []

    entries = []

    # Split on YAML frontmatter boundaries.
    # A '---' on its own line marks either the start or end of a frontmatter block.
    # We need to be careful: old-format entries don't have '---' at all.

    # Strategy: split text into blocks separated by standalone '---' lines.
    # Then reconstruct: if a block starts with '---', it's the opening of a
    # frontmatter block; pair it with the next '---' block as closing.

    # Simpler approach: find all positions of '---' on their own lines.
    # Use them to identify YAML frontmatter blocks.

    lines = text.split('\n')

    # Find all line indices where '---' appears as a standalone line
    separator_indices = [
        i for i, line in enumerate(lines)
        if line.strip() == '---'
    ]

    if not separator_indices:
        # No YAML frontmatter at all — treat entire text as old-format entries.
        # Split on blank lines + ## headers.
        return _parse_old_format(text)

    # Parse by scanning for frontmatter blocks (pairs of '---' lines)
    # and old-format content between them.
    consumed_up_to = 0  # line index
    i = 0

    while i < len(separator_indices):
        sep_start = separator_indices[i]

        # Anything between consumed_up_to and sep_start is old-format content
        if sep_start > consumed_up_to:
            old_block = '\n'.join(lines[consumed_up_to:sep_start]).strip()
            if old_block:
                for entry in _parse_old_format(old_block):
                    entries.append(entry)

        # Look for closing '---'
        if i + 1 < len(separator_indices):
            sep_end = separator_indices[i + 1]
        else:
            # No closing separator — treat remainder as old-format
            remainder = '\n'.join(lines[sep_start:]).strip()
            if remainder and remainder != '---':
                entries.extend(_parse_old_format(remainder))
            break

        # Reconstruct the frontmatter block: '---' + fm_lines + '---' + content
        # The content runs from sep_end+1 to the next sep_start (or end of file)
        if i + 2 < len(separator_indices):
            next_sep_start = separator_indices[i + 2]
        else:
            next_sep_start = len(lines)

        fm_block_lines = lines[sep_start:sep_end + 1]  # includes both '---'
        content_lines = lines[sep_end + 1:next_sep_start]

        # Remove trailing '---' lines from content (they belong to next entry)
        while content_lines and content_lines[-1].strip() == '---':
            content_lines = content_lines[:-1]
            next_sep_start -= 1

        full_block = '\n'.join(fm_block_lines) + '\n' + '\n'.join(content_lines)
        entry = parse_entry(full_block.strip())
        if entry.content or entry.id:
            entries.append(entry)

        consumed_up_to = next_sep_start
        i += 2  # skip past the closing '---'

    # Any remaining content after last processed separator
    if consumed_up_to < len(lines):
        remainder = '\n'.join(lines[consumed_up_to:]).strip()
        if remainder and remainder != '---':
            for entry in _parse_old_format(remainder):
                entries.append(entry)

    return [e for e in entries if e.content.strip() or e.id]


def _parse_old_format(text: str) -> list:
    """Parse old-format MEMORY.md text (no YAML frontmatter).

    Splits on '## [' section headers. Each section becomes one MemoryEntry
    with default metadata.
    """
    if not text.strip():
        return []

    # Split on '## [' headers (each is a new learning entry)
    sections = re.split(r'(?=## \[)', text)
    entries = []
    for section in sections:
        section = section.strip()
        if section:
            entries.append(_default_entry(section))
    return entries


# ── Memory file serialization ──────────────────────────────────────────────────

def serialize_memory_file(entries: list) -> str:
    """Join serialized entries into a full MEMORY.md file content.

    Entries are separated by a blank line.
    Returns empty string for empty list.
    """
    if not entries:
        return ''
    return '\n\n'.join(serialize_entry(e) for e in entries)


# ── CLI (for testing) ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path) as f:
            text = f.read()
        entries = parse_memory_file(text)
        print(f"Parsed {len(entries)} entries from {path}")
        for e in entries[:3]:
            print(f"  [{e.status}] {e.type}/{e.domain} importance={e.importance} phase={e.phase}")
            print(f"    content[:60]: {e.content[:60]!r}")
