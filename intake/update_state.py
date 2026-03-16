#!/usr/bin/env python3
"""Update intake state from a manifest file.

Marks all items in the manifest as seen and sets last_run to today.

Usage:
    uv run python -m intake.update_state intake/raw/2026-03-16/manifest.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

from intake.state import load_state, mark_seen, save_state


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m intake.update_state <manifest.json>')
        sys.exit(1)

    manifest_path = sys.argv[1]
    if not os.path.exists(manifest_path):
        print(f'Manifest not found: {manifest_path}')
        sys.exit(1)

    with open(manifest_path, encoding='utf-8') as f:
        manifest = json.load(f)

    state = load_state()
    count = 0

    for item in manifest['items']:
        if item.get('unreachable'):
            continue
        content_id = item.get('video_id', item['url'])
        mark_seen(
            state, item['source_url'], content_id,
            date=item.get('published', ''),
            content_hash=item.get('content_hash', ''),
        )
        count += 1

    state['last_run'] = date.today().isoformat()
    save_state(state)
    print(f'State updated: {count} items marked seen, last_run={state["last_run"]}')


if __name__ == '__main__':
    main()
