"""RSS feed fetching for the intake pipeline.

Fetches RSS/Atom feeds and returns new entries, using the intake
state file to filter out already-processed content.

CLI test mode:
    python -m intake.rss https://lilianweng.github.io/feed.xml
"""
from __future__ import annotations

from dataclasses import dataclass

import feedparser


@dataclass
class FeedEntry:
    title: str
    url: str
    published: str   # ISO 8601 or whatever the feed provides
    summary: str     # feed description/summary if available
    source_name: str


def fetch_feed(
    feed_url: str,
    source_name: str = '',
    max_entries: int = 5,
) -> list[FeedEntry]:
    """Fetch a feed and return up to max_entries recent entries.

    Returns an empty list on any fetch or parse error.
    """
    try:
        feed = feedparser.parse(feed_url)
    except Exception:
        return []

    # feedparser doesn't raise on network errors — it sets bozo=True
    if not feed.entries:
        return []

    resolved_name = source_name or feed.feed.get('title', feed_url)

    entries: list[FeedEntry] = []
    for item in feed.entries[:max_entries]:
        url = item.get('link', '')
        if not url:
            continue

        # published_parsed gives a time.struct_time; fall back to the raw string
        published = item.get('published', '')
        if not published:
            published = item.get('updated', '')

        summary = item.get('summary', '') or item.get('description', '')
        # Strip basic HTML tags from summary if present
        if summary and '<' in summary:
            import re
            summary = re.sub(r'<[^>]+>', '', summary).strip()

        entries.append(FeedEntry(
            title=item.get('title', ''),
            url=url,
            published=published,
            summary=summary[:500] if summary else '',
            source_name=resolved_name,
        ))

    return entries


def fetch_new_entries(
    feed_url: str,
    state: dict,
    source_url: str,
    source_name: str = '',
    max_entries: int = 5,
) -> list[FeedEntry]:
    """Fetch a feed and return only entries not yet recorded in state.

    source_url is the canonical URL used as the key in the state file
    (may differ from feed_url, e.g. blog homepage vs. /feed.xml).
    """
    from intake.state import is_new

    entries = fetch_feed(feed_url, source_name=source_name, max_entries=max_entries)
    return [e for e in entries if is_new(state, source_url, e.url, e.published)]


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python -m intake.rss <feed_url> [source_name]')
        sys.exit(1)

    feed_url = sys.argv[1]
    source_name = sys.argv[2] if len(sys.argv) > 2 else ''

    print(f'Fetching: {feed_url}')
    entries = fetch_feed(feed_url, source_name=source_name, max_entries=10)

    if not entries:
        print('No entries returned (feed unreachable or empty).')
        sys.exit(0)

    print(f'Found {len(entries)} entries:\n')
    for e in entries:
        print(f'  [{e.published}] {e.title}')
        print(f'  {e.url}')
        if e.summary:
            preview = e.summary[:120].replace('\n', ' ')
            print(f'  {preview}...' if len(e.summary) > 120 else f'  {e.summary}')
        print()
