#!/usr/bin/env python3
"""Pre-fetch GitHub issues and design doc index for the audit pipeline.

Writes context files that audit reviewers can Read without needing
Bash or WebSearch tools, avoiding permission escalation.

Usage:
    audit_prefetch.py [--outdir audit/context]
"""
import argparse
import glob
import json
import os
import subprocess
import sys


def fetch_issues(state: str = "open", limit: int = 100) -> list[dict]:
    """Fetch GitHub issues via gh CLI."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--state", state,
                "--limit", str(limit),
                "--json", "number,title,labels,body,state,createdAt,updatedAt",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[audit_prefetch] gh issue list failed: {exc}", file=sys.stderr)
        return []

    if result.returncode != 0 or not result.stdout.strip():
        print(f"[audit_prefetch] gh returned {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"[audit_prefetch] stderr: {result.stderr[:200]}", file=sys.stderr)
        return []

    return json.loads(result.stdout)


def build_design_docs_index(docs_dir: str) -> str:
    """Build a markdown index of design docs with their first heading."""
    lines = ["# Design Documents Index", ""]
    pattern = os.path.join(docs_dir, "**", "*.md")
    for path in sorted(glob.glob(pattern, recursive=True)):
        relpath = os.path.relpath(path, start=os.getcwd())
        # Extract first heading
        heading = ""
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("# "):
                        heading = line[2:].strip()
                        break
        except Exception:
            pass
        if heading:
            lines.append(f"- `{relpath}` — {heading}")
        else:
            lines.append(f"- `{relpath}`")
    return "\n".join(lines) + "\n"


def build_dismissed_template() -> str:
    """Return a template for the dismissed findings file."""
    return """# Dismissed Findings

Findings listed here will be skipped by the triage phase on future runs.
Add entries when a finding is reviewed and determined to be a non-issue.

<!-- Example:
## D-001: subprocess.run without shell=True in claude_runner.py
**Dismissed:** 2026-03-18
**Reason:** Intentional — we control the command array, no user input
-->
"""


def main():
    parser = argparse.ArgumentParser(description="Pre-fetch audit context")
    parser.add_argument(
        "--outdir", default="audit/context",
        help="Output directory for context files (default: audit/context)",
    )
    parser.add_argument(
        "--docs-dir", default="docs/detailed-design",
        help="Design documents directory (default: docs/detailed-design)",
    )
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    # Fetch open issues
    open_issues = fetch_issues(state="open")
    open_path = os.path.join(args.outdir, "issues-open.json")
    with open(open_path, "w") as f:
        json.dump(open_issues, f, indent=2)
    print(f"[audit_prefetch] {len(open_issues)} open issues → {open_path}")

    # Fetch recently closed issues
    closed_issues = fetch_issues(state="closed", limit=50)
    closed_path = os.path.join(args.outdir, "issues-recent-closed.json")
    with open(closed_path, "w") as f:
        json.dump(closed_issues, f, indent=2)
    print(f"[audit_prefetch] {len(closed_issues)} closed issues → {closed_path}")

    # Build design docs index
    index = build_design_docs_index(args.docs_dir)
    index_path = os.path.join(args.outdir, "design-docs-index.md")
    with open(index_path, "w") as f:
        f.write(index)
    print(f"[audit_prefetch] design docs index → {index_path}")

    # Create dismissed template if it doesn't exist
    dismissed_path = os.path.join("audit", "audit-dismissed.md")
    if not os.path.exists(dismissed_path):
        os.makedirs("audit", exist_ok=True)
        with open(dismissed_path, "w") as f:
            f.write(build_dismissed_template())
        print(f"[audit_prefetch] dismissed template → {dismissed_path}")


if __name__ == "__main__":
    main()
