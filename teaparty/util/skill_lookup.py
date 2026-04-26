"""Skill frontmatter parsing.

The CfA engine used to do its own embedding-based skill lookup before
the planning phase ran (System 1 fast path).  Skill selection moved
into the planning skill itself — it picks based on the frontmatter
descriptions Claude Code injects into context — so the lookup pipeline
is gone.  What remains is the frontmatter parser as a small shared
helper for any caller that needs to read a SKILL.md's metadata.
"""
from __future__ import annotations


def _parse_frontmatter(path: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter from a skill markdown file.

    Returns (metadata_dict, body_text).  Keeps parsing simple:
    flat key: value pairs only, consistent with the project's
    memory_entry.py approach.
    """
    with open(path) as f:
        content = f.read()

    if not content.startswith('---'):
        return {}, content

    end = content.find('---', 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    meta: dict[str, str] = {}
    for line in fm_text.split('\n'):
        if ':' in line:
            key, _, value = line.partition(':')
            meta[key.strip()] = value.strip()

    return meta, body
