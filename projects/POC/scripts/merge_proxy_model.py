#!/usr/bin/env python3
"""Merge a session-scoped proxy confidence model back into the shared model.

Each POC session works against a snapshot of the proxy confidence model.
At session end, the session's outcomes need to be merged back into the
shared model without losing updates from other sessions that completed
in the meantime.

Merge strategy:
    - Counters (approve_count, correct_count, etc.) are monotonically
      increasing within a session. Take max(shared, session) for each.
    - EMA: if the session had more observations than shared, use the
      session's EMA (it's more current). Otherwise keep shared's.
    - Differentials: union with dedup by (timestamp, summary), capped at 20.
    - last_updated: most recent timestamp wins.

Called under exclusive file lock (via file_lock.py CLI) so this script
does not need its own locking.

Usage:
    python3 merge_proxy_model.py --session <path> --shared <path>
"""
import argparse
import json
import os
import sys
import tempfile


def _load(path):
    """Load JSON or return empty model structure."""
    if not os.path.isfile(path):
        return {'entries': {}, 'global_threshold': 0.8, 'generative_threshold': 0.95}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {'entries': {}, 'global_threshold': 0.8, 'generative_threshold': 0.95}


def merge(session_path, shared_path):
    """Merge session proxy model into shared model."""
    session = _load(session_path)
    shared = _load(shared_path)

    s_entries = session.get('entries', {})
    sh_entries = shared.get('entries', {})

    for key, s_entry in s_entries.items():
        if key not in sh_entries:
            # New entry from this session — copy it in
            sh_entries[key] = s_entry
            continue

        sh = sh_entries[key]

        # Counters: take max (monotonically increasing within a session)
        for counter in ('approve_count', 'correct_count', 'reject_count',
                        'total_count', 'clarify_count', 'withdraw_count'):
            sh[counter] = max(sh.get(counter, 0), s_entry.get(counter, 0))

        # EMA: use the more-observed session's value
        if s_entry.get('total_count', 0) > sh.get('total_count', 0):
            for ema_key in ('ema_approval_rate', 'ema_confidence'):
                if ema_key in s_entry:
                    sh[ema_key] = s_entry[ema_key]

        # Differentials: union, dedup by (timestamp, summary), cap at 20
        sh_diffs = sh.get('differentials', [])
        s_diffs = s_entry.get('differentials', [])
        existing = {(d.get('timestamp', ''), d.get('summary', ''))
                    for d in sh_diffs}
        for d in s_diffs:
            sig = (d.get('timestamp', ''), d.get('summary', ''))
            if sig not in existing:
                sh_diffs.append(d)
                existing.add(sig)
        sh['differentials'] = sh_diffs[-20:]

        # last_updated: most recent wins
        s_updated = s_entry.get('last_updated', '')
        sh_updated = sh.get('last_updated', '')
        if s_updated > sh_updated:
            sh['last_updated'] = s_updated

        sh_entries[key] = sh

    shared['entries'] = sh_entries

    # Atomic write
    out_dir = os.path.dirname(os.path.abspath(shared_path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(shared, f, indent=2)
        os.replace(tmp, shared_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Merge session proxy model overlay back into shared model"
    )
    parser.add_argument('--session', required=True, help='Path to session-scoped proxy model')
    parser.add_argument('--shared', required=True, help='Path to shared proxy model')
    args = parser.parse_args()

    try:
        merge(args.session, args.shared)
    except Exception as e:
        print(f"[merge_proxy_model] Error: {e}", file=sys.stderr)
        sys.exit(1)
