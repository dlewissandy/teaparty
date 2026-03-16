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
    """Parse an analysis file and send a notification.

    Also reads the corresponding digest file (same date) to find URLs
    for each item, since the analysis may not include them.
    """
    with open(analysis_path, encoding='utf-8') as f:
        content = f.read()

    # Load digest for URL cross-reference
    digest_content = ''
    digest_dir = os.path.join(os.path.dirname(analysis_path), '..', 'digests')
    # Extract date from analysis filename: analysis-YYYY-MM-DD.md
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(analysis_path))
    if date_match:
        digest_path = os.path.join(digest_dir, f'digest-{date_match.group(1)}.md')
        if os.path.exists(digest_path):
            with open(digest_path, encoding='utf-8') as f:
                digest_content = f.read()

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
                verdict = cells[4].strip().lower().replace('*', '')
                item_name = cells[1].strip().replace('*', '')
                if verdict == 'explore':
                    explore_items.append(item_name)
                elif verdict == 'watch':
                    watch_count += 1
                elif verdict == 'skip':
                    skip_count += 1
        elif in_table and not line.startswith('|'):
            in_table = False

    total = len(explore_items) + watch_count + skip_count

    # Build explore details — find each explore section and extract detail + URL
    # Split content into sections by ### N. headers
    sections = re.split(r'\n(?=#{2,3}\s+\d+\.)', content)
    section_map = {}
    for sec in sections:
        # Extract the name from the header
        header_match = re.match(r'#{2,3}\s+\d+\.\s+(.+?)(?:\s+[—\-]+\s+\w+)?\s*\n', sec)
        if header_match:
            sec_name = header_match.group(1).strip()
            section_map[sec_name.lower()] = sec

    # Build a URL map from the digest (more reliable than analysis)
    digest_urls = {}
    if digest_content:
        for sec in re.split(r'\n(?=##\s+\d+\.)', digest_content):
            header = re.match(r'##\s+\d+\.\s+(.+)\n', sec)
            url_line = re.search(r'\*\*URL:\*\*\s*(https?://\S+)', sec)
            if header and url_line:
                digest_urls[header.group(1).strip().lower()] = url_line.group(1).rstrip(').,')

    explore_with_urls = []
    for item_name in explore_items:
        section = section_map.get(item_name.lower(), '')
        detail = ''
        url = ''

        # Try digest first for URL (fuzzy match), then analysis section
        item_lower = item_name.lower()
        url = digest_urls.get(item_lower, '')
        if not url:
            # Fuzzy: find digest key where most words overlap
            item_words = set(item_lower.split())
            best_score, best_url = 0, ''
            for dk, durl in digest_urls.items():
                dk_words = set(dk.split())
                overlap = len(item_words & dk_words)
                if overlap > best_score and overlap >= len(item_words) * 0.6:
                    best_score = overlap
                    best_url = durl
            url = best_url
        if not url and section:
            url_match = re.search(r'https?://\S+', section)
            if url_match:
                url = url_match.group(0).rstrip(').,')

        if section:
            # Extract first substantive paragraph as detail
            for para in section.split('\n\n'):
                para = para.strip()
                if para and not para.startswith('**') and not para.startswith('#') and len(para) > 20:
                    # Take first sentence
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    detail = sentences[0] if sentences else para[:120]
                    break
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
