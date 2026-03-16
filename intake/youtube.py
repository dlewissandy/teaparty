"""YouTube channel monitoring and transcript fetching.

Uses RSS feeds (no API key) to discover recent videos, and
youtube-transcript-api (no API key) to fetch transcripts.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


# ── Channel ID resolution ───────────────────────────────────────────────────

# YouTube channel URLs come in several forms:
#   https://www.youtube.com/@Handle
#   https://www.youtube.com/channel/UC...
#   https://www.youtube.com/c/CustomName
#
# RSS feeds require the channel ID (UC...).  For @handle URLs, we fetch the
# page and extract the channel ID from the HTML.

_CHANNEL_ID_RE = re.compile(r'channel/(UC[\w-]+)')
_HANDLE_RE = re.compile(r'youtube\.com/@([\w-]+)')

_CHANNEL_IDS_CACHE_PATH = os.path.join(os.path.dirname(__file__), '.channel-ids.json')


def _load_channel_id_cache(path: str = _CHANNEL_IDS_CACHE_PATH) -> dict[str, str]:
    """Load the channel-ID cache from disk. Returns {} if missing or unreadable."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_channel_id_cache(
    cache: dict[str, str],
    path: str = _CHANNEL_IDS_CACHE_PATH,
) -> None:
    """Persist the channel-ID cache to disk."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
        f.write('\n')


def resolve_channel_id(url: str) -> str:
    """Extract or resolve a YouTube channel ID from a URL.

    For /channel/UC... URLs, extracts directly.
    For /@handle URLs, checks the on-disk cache first; if not cached,
    fetches the page to find the channel ID and caches the result.
    Returns '' if resolution fails.
    """
    # Direct channel ID in URL — no cache needed
    m = _CHANNEL_ID_RE.search(url)
    if m:
        return m.group(1)

    # @handle or /c/ — try cache before hitting the network
    if '/@' in url or '/c/' in url:
        cache = _load_channel_id_cache()
        if url in cache:
            return cache[url]

        import requests
        try:
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0',
            })
            resp.raise_for_status()
            m = re.search(r'"channelId":"(UC[\w-]+)"', resp.text)
            if not m:
                # Fallback: look in link tags
                m = re.search(r'channel/(UC[\w-]+)', resp.text)
            if m:
                channel_id = m.group(1)
                cache[url] = channel_id
                _save_channel_id_cache(cache)
                return channel_id
        except Exception:
            pass

    return ''


# ── RSS feed ────────────────────────────────────────────────────────────────

@dataclass
class VideoEntry:
    """A video from a channel's RSS feed."""
    video_id: str
    title: str
    published: str  # ISO 8601
    channel: str
    url: str


def fetch_recent_videos(channel_id: str, max_results: int = 5) -> list[VideoEntry]:
    """Fetch recent videos from a channel's RSS feed.

    Returns up to max_results entries, newest first.
    No API key required.
    """
    feed_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    feed = feedparser.parse(feed_url)

    entries = []
    for entry in feed.entries[:max_results]:
        video_id = entry.get('yt_videoid', '')
        if not video_id:
            # Extract from link
            link = entry.get('link', '')
            m = re.search(r'v=([\w-]+)', link)
            video_id = m.group(1) if m else ''

        if not video_id:
            continue

        entries.append(VideoEntry(
            video_id=video_id,
            title=entry.get('title', ''),
            published=entry.get('published', ''),
            channel=feed.feed.get('title', ''),
            url=f'https://www.youtube.com/watch?v={video_id}',
        ))

    return entries


# ── Transcript fetching ─────────────────────────────────────────────────────

def fetch_transcript(video_id: str, max_chars: int = 15000) -> str:
    """Fetch the transcript for a YouTube video.

    Tries English first, then falls back to any available language.
    Returns the transcript as a single string, or an error message.

    Args:
        video_id: YouTube video ID.
        max_chars: Maximum characters to return (default 15000, roughly 2500
            words / 15-minute video).  When the transcript exceeds this limit,
            the first 2/3 and last 1/3 of the cap are kept so that both the
            intro and conclusion are preserved.  A splice note is inserted at
            the cut point.  Pass 0 to disable truncation.
    """
    try:
        api = YouTubeTranscriptApi()

        # Try English first, then fall back to any available
        try:
            segments = api.fetch(video_id, languages=['en'])
        except NoTranscriptFound:
            # List available and take the first one
            transcript_list = api.list(video_id)
            for t in transcript_list:
                segments = t.fetch()
                break
            else:
                return '[NO TRANSCRIPT AVAILABLE]'

        text = ' '.join(s.text for s in segments)

        if max_chars and len(text) > max_chars:
            original_len = len(text)
            head_chars = (max_chars * 2) // 3
            tail_chars = max_chars - head_chars
            head = text[:head_chars]
            tail = text[len(text) - tail_chars:]
            splice_note = (
                f' [TRANSCRIPT TRUNCATED — original was {original_len} chars] '
            )
            text = head + splice_note + tail

        return text

    except TranscriptsDisabled:
        return '[TRANSCRIPTS DISABLED]'
    except VideoUnavailable:
        return '[VIDEO UNAVAILABLE]'
    except Exception as e:
        return f'[TRANSCRIPT ERROR: {type(e).__name__}: {e}]'


# ── High-level: channel → transcripts ───────────────────────────────────────

@dataclass
class VideoDigest:
    """A video with its transcript, ready for the digest pipeline."""
    video_id: str
    title: str
    published: str
    channel: str
    url: str
    transcript: str


def digest_channel(
    channel_url: str,
    max_videos: int = 3,
    since: str = '',
    max_transcript_chars: int = 15000,
) -> list[VideoDigest]:
    """Fetch recent videos and their transcripts from a YouTube channel.

    Args:
        channel_url: YouTube channel URL (any format)
        max_videos: Max videos to fetch
        since: ISO date string — only return videos published after this date
        max_transcript_chars: Passed through to fetch_transcript(); 0 disables
            truncation.

    Returns list of VideoDigest with transcripts.
    """
    channel_id = resolve_channel_id(channel_url)
    if not channel_id:
        return []

    videos = fetch_recent_videos(channel_id, max_results=max_videos)

    if since:
        videos = [v for v in videos if v.published >= since]

    results = []
    for v in videos:
        transcript = fetch_transcript(v.video_id, max_chars=max_transcript_chars)
        results.append(VideoDigest(
            video_id=v.video_id,
            title=v.title,
            published=v.published,
            channel=v.channel,
            url=v.url,
            transcript=transcript,
        ))

    return results


# ── CLI for testing ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python -m intake.youtube <channel_url_or_video_id>')
        print('  Channel URL: fetches recent videos + transcripts')
        print('  Video ID: fetches single transcript')
        sys.exit(1)

    arg = sys.argv[1]

    if arg.startswith('http'):
        # Channel URL
        print(f'Resolving channel: {arg}')
        channel_id = resolve_channel_id(arg)
        if not channel_id:
            print('Could not resolve channel ID')
            sys.exit(1)
        print(f'Channel ID: {channel_id}')

        videos = fetch_recent_videos(channel_id, max_results=3)
        for v in videos:
            print(f'\n--- {v.title} ({v.published}) ---')
            print(f'URL: {v.url}')
            transcript = fetch_transcript(v.video_id)
            print(f'Transcript: {transcript[:500]}...' if len(transcript) > 500 else f'Transcript: {transcript}')
    else:
        # Video ID
        print(f'Fetching transcript for: {arg}')
        transcript = fetch_transcript(arg)
        print(transcript[:2000] if len(transcript) > 2000 else transcript)
