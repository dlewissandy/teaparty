#!/usr/bin/env python3
"""Send intake results to Apple Reminders.

Runs OUTSIDE Claude Code — no permission issues.
Reads the analysis file to build the notification.

Usage:
    uv run python -m intake.notify intake/analysis/analysis-2026-03-16.md
    uv run python -m intake.notify --no-new    # report no new content
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date


def _send_reminder(title: str, body: str) -> bool:
    """Create an Apple Reminder with a due date (triggers push notification)."""
    # Escape single quotes for AppleScript
    title = title.replace("'", "\\'")
    body = body.replace("'", "\\'")
    # Escape backslashes
    title = title.replace('\\', '\\\\')
    body = body.replace('\\', '\\\\')

    script = f"""
tell application "Reminders"
    set myList to list "Reminders"
    tell myList
        make new reminder with properties {{name:"{title}", body:"{body}", due date:(current date)}}
    end tell
end tell
"""
    try:
        subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except Exception:
        return False


def notify_from_analysis(analysis_path: str) -> None:
    """Parse an analysis file and send a notification."""
    with open(analysis_path, encoding='utf-8') as f:
        content = f.read()

    # Parse summary matrix for counts
    explore_items = []
    watch_count = 0
    skip_count = 0

    # Find the summary matrix table
    in_table = False
    for line in content.split('\n'):
        if '| # |' in line or '|---|' in line:
            in_table = True
            continue
        if in_table and line.startswith('|'):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) >= 5:
                verdict = cells[4].strip().lower()
                if verdict == 'explore':
                    explore_items.append(cells[1].strip())
                elif verdict == 'watch':
                    watch_count += 1
                elif verdict == 'skip':
                    skip_count += 1
        elif in_table and not line.startswith('|'):
            in_table = False

    total = len(explore_items) + watch_count + skip_count

    # Build explore details — find the section for each explore item
    explore_details = []
    for item_name in explore_items:
        # Find the section and extract the "What Could Be Added" or relevance
        pattern = re.escape(item_name)
        match = re.search(
            rf'##\s+\d+\.\s+{pattern}.*?(?:###\s+What Could Be Added\s*\n(.*?)(?:\n###|\n---|\Z))',
            content, re.DOTALL | re.IGNORECASE,
        )
        if match:
            detail = match.group(1).strip().split('\n')[0].strip()
        else:
            detail = ''
        explore_details.append((item_name, detail))

    # Also try to find URLs for explore items
    explore_with_urls = []
    for item_name, detail in explore_details:
        pattern = re.escape(item_name)
        url_match = re.search(
            rf'##\s+\d+\.\s+{pattern}.*?\*\*Source:\*\*.*?(https?://\S+)',
            content, re.DOTALL | re.IGNORECASE,
        )
        url = url_match.group(1).rstrip(')') if url_match else ''
        explore_with_urls.append((item_name, url, detail))

    # Build notification
    title = f'RESEARCH INTAKE: {total} New, {len(explore_items)} to Explore'

    body_lines = []
    for i, (name, url, detail) in enumerate(explore_with_urls, 1):
        body_lines.append(f'{i}. {name}')
        if url:
            body_lines.append(f'   {url}')
        if detail:
            body_lines.append(f'   {detail}')
        body_lines.append('')

    body = '\n'.join(body_lines).strip()

    print(f'Sending notification: {title}')
    if _send_reminder(title, body):
        print('Reminder created successfully')
    else:
        print('Failed to create reminder', file=sys.stderr)


def notify_no_new() -> None:
    """Send a "no new content" notification."""
    title = 'RESEARCH INTAKE: No new content today'
    body = f'18 sources checked on {date.today().isoformat()}, nothing new.'
    _send_reminder(title, body)
    print('No-new-content reminder created')


if __name__ == '__main__':
    if '--no-new' in sys.argv:
        notify_no_new()
    elif len(sys.argv) >= 2:
        notify_from_analysis(sys.argv[1])
    else:
        print('Usage: python -m intake.notify <analysis-file>')
        print('       python -m intake.notify --no-new')
        sys.exit(1)
