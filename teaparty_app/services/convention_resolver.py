"""Resolve virtual files at convention paths with org-level cascade.

All convention-based features (CLAUDE.md, workflows, hooks, commands) follow
the same pattern: virtual files at known prefixes with org files providing
defaults that workgroup files can override by filename.
"""

from __future__ import annotations

from teaparty_app.models import Organization, Workgroup


def resolve_effective_files(
    org_files: list[dict] | None,
    workgroup_files: list[dict] | None,
    prefix: str,
    extension: str = ".md",
) -> list[dict]:
    """Gather files from workgroup + org, workgroup overrides org by filename.

    Args:
        org_files: The organization's files list (may be None).
        workgroup_files: The workgroup's files list (may be None).
        prefix: Path prefix to filter on (e.g. "workflows", "commands").
        extension: File extension to filter on.

    Returns:
        Merged list of file dicts, workgroup files overriding org files
        with the same filename.
    """
    def _matching(files: list[dict] | None) -> list[dict]:
        if not files:
            return []
        result = []
        for f in files:
            path = f.get("path", "")
            if not path.startswith(prefix + "/"):
                continue
            if extension and not path.endswith(extension):
                continue
            result.append(f)
        return result

    org_matched = _matching(org_files)
    wg_matched = _matching(workgroup_files)

    # Build lookup by filename (last path segment) — workgroup wins.
    by_filename: dict[str, dict] = {}
    for f in org_matched:
        path = f.get("path", "")
        filename = path.rsplit("/", 1)[-1]
        by_filename[filename] = {**f, "_source": "org"}

    for f in wg_matched:
        path = f.get("path", "")
        filename = path.rsplit("/", 1)[-1]
        by_filename[filename] = {**f, "_source": "workgroup"}

    return list(by_filename.values())


def extract_claude_md(files: list[dict] | None, max_chars: int = 4000) -> str:
    """Extract CLAUDE.md content from a files list, capped at max_chars."""
    if not files:
        return ""
    for f in files:
        if f.get("path") == "CLAUDE.md":
            content = (f.get("content") or "").strip()
            return content[:max_chars] if content else ""
    return ""
