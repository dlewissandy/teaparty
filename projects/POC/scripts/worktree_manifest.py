#!/usr/bin/env python3
"""Worktree manifest manager — tracks worktrees with self-describing names.

Principle 4 of the State Hygiene spec:
  - Worktrees get self-describing names: TEAM-SHORT_ID--TASK_SLUG (dispatches)
    or session-SHORT_ID--TASK_SLUG (sessions).
  - A worktrees.json manifest at the repo root links each worktree to its
    dispatch with a lifecycle status.
  - ops/status.sh reads the manifest to print a summary table.

Manifest schema (worktrees.json):
  {
    "worktrees": [
      {
        "name":       "coding-ab12cd34--implement-login",
        "path":       "/abs/path/to/worktree",
        "type":       "session" | "dispatch",
        "team":       "coding",
        "task":       "first 120 chars of task description",
        "session_id": "20260310-083240",
        "created_at": "2026-03-10T08:32:40+00:00",
        "status":     "active" | "complete" | "failed" | "abandoned",
        "updated_at": "2026-03-10T08:45:00+00:00"   # only after status update
      }
    ]
  }

No external dependencies — stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional


# ── Slugify ────────────────────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 40) -> str:
    """Convert arbitrary text to a filesystem-safe slug.

    Steps:
      1. Lowercase
      2. Replace runs of non-alphanumeric chars with a single hyphen
      3. Strip leading/trailing hyphens
      4. Truncate to max_len, then strip any trailing hyphen created by truncation
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    text = text[:max_len].rstrip('-')
    return text or 'task'


# ── Manifest path ──────────────────────────────────────────────────────────────

def _git_root(start_dir: str) -> Optional[str]:
    """Return the git repo root containing start_dir, or None if not in a repo."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            cwd=start_dir,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def manifest_path(repo_dir: Optional[str] = None) -> str:
    """Return the absolute path to worktrees.json.

    Resolution order:
      1. repo_dir argument (used as-is — caller passes the git root)
      2. POC_REPO_DIR environment variable
      3. git rev-parse --show-toplevel from the current directory
      4. Current directory (last resort)
    """
    base = repo_dir
    if base is None:
        base = os.environ.get('POC_REPO_DIR')
    if base is None:
        base = _git_root(os.getcwd())
    if base is None:
        base = os.getcwd()
    return os.path.join(base, 'worktrees.json')


# ── Manifest I/O ───────────────────────────────────────────────────────────────

def load_manifest(path: str) -> dict:
    """Load manifest from disk; return empty structure if file is missing."""
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'worktrees': []}


def save_manifest(path: str, manifest: dict) -> None:
    """Atomically write manifest to disk (tmp file + os.replace)."""
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(manifest, f, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        # Clean up tmp if replace failed
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_add(args: argparse.Namespace) -> None:
    """Register a new worktree in the manifest (upserts on name)."""
    path = manifest_path(args.repo_dir)
    manifest = load_manifest(path)

    entry: dict = {
        'name':       args.name,
        'path':       args.worktree_path,
        'type':       args.type,
        'team':       args.team or '',
        'task':       args.task or '',
        'session_id': args.session_id or '',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status':     'active',
    }

    # Upsert: remove existing entry with same name so we don't accumulate dupes
    manifest['worktrees'] = [
        w for w in manifest['worktrees'] if w.get('name') != args.name
    ]
    manifest['worktrees'].append(entry)
    save_manifest(path, manifest)


def cmd_update_status(status: str, args: argparse.Namespace) -> None:
    """Update the lifecycle status of a named worktree entry."""
    path = manifest_path(args.repo_dir)
    manifest = load_manifest(path)

    updated = False
    for entry in manifest['worktrees']:
        if entry.get('name') == args.name:
            entry['status'] = status
            entry['updated_at'] = datetime.now(timezone.utc).isoformat()
            updated = True
            break

    if updated:
        save_manifest(path, manifest)


_STATUS_EMOJI = {
    'active':    '🔄',
    'complete':  '✅',
    'failed':    '❌',
    'abandoned': '🚫',
}


def cmd_list(args: argparse.Namespace) -> None:
    """Print an emoji status table of all worktrees in the manifest."""
    path = manifest_path(args.repo_dir)
    manifest = load_manifest(path)
    entries = manifest.get('worktrees', [])

    if not entries:
        print('  (no worktrees in manifest)')
        return

    for entry in entries:
        status = entry.get('status', 'unknown')
        emoji  = _STATUS_EMOJI.get(status, '❓')
        name   = entry.get('name', '')
        wtype  = entry.get('type', '')
        team   = entry.get('team', '')
        task   = (entry.get('task', '') or '')[:60]
        sid    = entry.get('session_id', '')

        team_tag = f'  [{team}]' if team else ''
        sid_tag  = f'  id={sid}' if sid else ''
        print(f'  {emoji}  {name:<52}  {wtype:<10}{team_tag}{sid_tag}')
        if task:
            print(f'       {task}')


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Worktree manifest manager (Principle 4 — State Hygiene)',
    )
    parser.add_argument(
        '--repo-dir',
        metavar='DIR',
        default=None,
        help='Git repo root (default: auto-detect via git rev-parse)',
    )
    sub = parser.add_subparsers(dest='cmd', metavar='SUBCOMMAND')

    # ── add ──
    p_add = sub.add_parser('add', help='Register a new worktree in the manifest')
    p_add.add_argument('--name',          required=True, help='Self-describing worktree name')
    p_add.add_argument('--worktree-path', required=True, help='Absolute path to the worktree')
    p_add.add_argument('--type',          required=True, choices=['session', 'dispatch'],
                       help='Worktree kind')
    p_add.add_argument('--team',       default='', help='Team name (for dispatches)')
    p_add.add_argument('--task',       default='', help='Task description (truncated to 120 chars)')
    p_add.add_argument('--session-id', default='', help='Session or dispatch timestamp ID')
    # Allow --repo-dir after the subcommand (SUPPRESS avoids clobbering top-level value)
    p_add.add_argument('--repo-dir', metavar='DIR', default=argparse.SUPPRESS,
                       help='Git repo root (overrides top-level --repo-dir)')

    # ── complete / fail / abandon ──
    for status_cmd in ('complete', 'fail', 'abandon'):
        p_s = sub.add_parser(status_cmd, help=f'Mark a worktree as {status_cmd}d')
        p_s.add_argument('--name', required=True, help='Worktree name to update')
        p_s.add_argument('--repo-dir', metavar='DIR', default=argparse.SUPPRESS,
                         help='Git repo root (overrides top-level --repo-dir)')

    # ── list ──
    p_list = sub.add_parser('list', help='Print emoji status table of all worktrees')
    p_list.add_argument('--repo-dir', metavar='DIR', default=argparse.SUPPRESS,
                        help='Git repo root (overrides top-level --repo-dir)')

    args = parser.parse_args()

    if args.cmd is None:
        parser.print_help()
        sys.exit(1)

    if args.cmd == 'add':
        cmd_add(args)
    elif args.cmd == 'complete':
        cmd_update_status('complete', args)
    elif args.cmd == 'fail':
        cmd_update_status('failed', args)
    elif args.cmd == 'abandon':
        cmd_update_status('abandoned', args)
    elif args.cmd == 'list':
        cmd_list(args)


if __name__ == '__main__':
    main()
