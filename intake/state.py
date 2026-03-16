"""State file management for the intake pipeline.

Tracks which content has already been processed to avoid re-fetching
and re-summarising items across runs.

State file format (intake/.state.json):
{
    "last_run": "2026-03-16",
    "sources": {
        "https://blog.langchain.dev": {
            "last_url": "https://blog.langchain.dev/some-post",
            "last_date": "2026-03-15",
            "content_hash": "abc123"
        },
        "https://www.youtube.com/@AndrejKarpathy": {
            "last_video_id": "xyz789",
            "last_date": "2026-03-14"
        }
    }
}
"""
from __future__ import annotations

import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), '.state.json')


def load_state(path: str = _DEFAULT_PATH) -> dict:
    """Load state from disk. Returns empty state dict if file doesn't exist."""
    if not os.path.exists(path):
        return {'last_run': '', 'sources': {}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Ensure required keys are present
        data.setdefault('last_run', '')
        data.setdefault('sources', {})
        return data
    except (json.JSONDecodeError, OSError):
        return {'last_run': '', 'sources': {}}


def save_state(state: dict, path: str = _DEFAULT_PATH) -> None:
    """Save state to disk, creating the directory if needed."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write('\n')


def is_new(state: dict, source_url: str, content_url_or_id: str, date: str = '') -> bool:
    """Return True if this content has not been seen before.

    Primary check is date-based: if the content's date is on or before the
    source's last_date, it's old.  Falls back to URL/ID matching if dates
    are unavailable.
    """
    sources = state.get('sources', {})
    entry = sources.get(source_url)

    if entry is None:
        return True

    # Date-based: anything on or before last_date is old
    if date and entry.get('last_date'):
        if date <= entry['last_date']:
            return False
        return True

    # Fallback: exact URL/ID match
    stored_id = entry.get('last_url') or entry.get('last_video_id', '')
    if stored_id and stored_id == content_url_or_id:
        return False

    return True


def is_updated(state: dict, source_url: str, content_url_or_id: str, content_hash: str) -> bool:
    """Return True if this content was seen before but has changed.

    Compares content_hash against the stored hash for this source+URL.
    Returns False if the content is new (never seen) or unchanged.
    """
    if not content_hash:
        return False
    sources = state.get('sources', {})
    entry = sources.get(source_url)
    if entry is None:
        return False  # never seen — it's new, not updated

    stored_hash = entry.get('content_hash', '')
    if not stored_hash:
        return False  # no prior hash to compare

    stored_url = entry.get('last_url', '')
    if stored_url != content_url_or_id:
        return False  # different URL — it's new, not updated

    return stored_hash != content_hash


def content_hash(text: str) -> str:
    """Compute a short hash of content for change detection."""
    import hashlib
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:16]


def mark_seen(
    state: dict,
    source_url: str,
    content_url_or_id: str,
    date: str = '',
    content_hash: str = '',
) -> None:
    """Record that content was processed.

    Decides whether to store the value as last_url or last_video_id
    based on whether it looks like a full URL.
    """
    sources = state.setdefault('sources', {})
    entry = sources.setdefault(source_url, {})

    if content_url_or_id.startswith('http'):
        entry['last_url'] = content_url_or_id
    else:
        entry['last_video_id'] = content_url_or_id

    if date:
        entry['last_date'] = date

    if content_hash:
        entry['content_hash'] = content_hash
