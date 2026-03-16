#!/usr/bin/env python3
"""Pre-fetch all intake sources into local files.

Runs OUTSIDE Claude Code — no permission issues.
Writes raw content to intake/raw/<date>/ so Claude only needs to read files.

Usage:
    uv run python -m intake.fetch              # fetch all sources
    uv run python -m intake.fetch --rss-only   # fetch RSS only
    uv run python -m intake.fetch --youtube-only
    uv run python -m intake.fetch --web-only
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

import requests

from intake.rss import fetch_feed
from intake.state import load_state, is_new, is_updated, content_hash, save_state
from intake.youtube import digest_channel


# ── Source definitions ──────────────────────────────────────────────────────

RSS_SOURCES = [
    ('LangChain Blog', 'https://blog.langchain.dev/rss/', 'https://blog.langchain.dev'),
    ('Latent Space', 'https://www.latent.space/feed', 'https://www.latent.space'),
    ('Interconnects', 'https://www.interconnects.ai/feed', 'https://www.interconnects.ai'),
    ('Import AI', 'https://importai.substack.com/feed', 'https://importai.substack.com'),
    ('One Useful Thing', 'https://www.oneusefulthing.org/feed', 'https://www.oneusefulthing.org'),
    ('Simon Willison', 'https://simonwillison.net/atom/everything/', 'https://simonwillison.net'),
    ('Ahead of AI', 'https://magazine.sebastianraschka.com/feed', 'https://magazine.sebastianraschka.com'),
    ('arXiv cs.AI', 'https://arxiv.org/rss/cs.AI', 'https://arxiv.org/list/cs.AI/recent'),
]

YOUTUBE_CHANNELS = [
    ('David Shapiro', 'https://www.youtube.com/@DavidShapiroAutomator'),
    ('AI Explained', 'https://www.youtube.com/@aiexplained-official'),
    ('Andrej Karpathy', 'https://www.youtube.com/@AndrejKarpathy'),
    ('Dwarkesh Patel', 'https://www.youtube.com/@DwarkeshPatel'),
]

WEB_SOURCES = [
    ('Anthropic', 'https://www.anthropic.com/news'),
    ('OpenAI', 'https://openai.com/news'),
    ('Lilian Weng', 'https://lilianweng.github.io'),
    ('BAIR Blog', 'https://bair.berkeley.edu/blog'),
    ('Allen AI', 'https://allenai.org/blog'),
    ('Hugging Face Papers', 'https://huggingface.co/papers'),
]

HEADERS = {'User-Agent': 'TeaParty-Intake/1.0 (research; +https://github.com/dlewissandy/teaparty)'}
# Some sites (OpenAI) return 403 for non-browser user agents
BROWSER_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'}
BROWSER_UA_DOMAINS = {'openai.com'}


# ── Output directory ────────────────────────────────────────────────────────

def _output_dir() -> str:
    today = date.today().isoformat()
    d = os.path.join(os.path.dirname(__file__), 'raw', today)
    os.makedirs(d, exist_ok=True)
    return d


def _safe_filename(name: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in name)


# ── RSS fetching ────────────────────────────────────────────────────────────

def fetch_rss(state: dict, out_dir: str) -> list[dict]:
    """Fetch RSS feeds, download full articles, write to out_dir/rss/.

    Returns list of {source, title, url, published, file, content_hash} dicts.
    """
    rss_dir = os.path.join(out_dir, 'rss')
    os.makedirs(rss_dir, exist_ok=True)
    results = []

    for name, feed_url, source_url in RSS_SOURCES:
        print(f'  RSS: {name}...', end=' ', flush=True)
        entries = fetch_feed(feed_url, source_name=name, max_entries=5)
        new_count = 0

        for entry in entries:
            if not is_new(state, source_url, entry.url, date=entry.published):
                continue

            # Fetch full article
            content = entry.summary or ''
            if not source_url.startswith('https://arxiv.org'):
                try:
                    resp = requests.get(entry.url, headers=HEADERS, timeout=20)
                    resp.raise_for_status()
                    content = resp.text
                except Exception as e:
                    content = f'[FETCH ERROR: {e}]\n\n{entry.summary}'

            h = content_hash(content)

            # Check for updates to previously seen content
            updated = is_updated(state, source_url, entry.url, h)

            fname = _safe_filename(f'{name}--{entry.title[:60]}') + '.txt'
            fpath = os.path.join(rss_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)

            results.append({
                'source': name,
                'source_url': source_url,
                'title': entry.title,
                'url': entry.url,
                'published': entry.published,
                'file': fpath,
                'content_hash': h,
                'updated': updated,
                'type': 'paper' if 'arxiv' in source_url else 'article',
            })
            new_count += 1

        print(f'{new_count} new' if new_count else 'no new')

    return results


# ── YouTube fetching ────────────────────────────────────────────────────────

def fetch_youtube(state: dict, out_dir: str) -> list[dict]:
    """Fetch YouTube transcripts, write to out_dir/youtube/.

    Returns list of {source, title, url, published, file, video_id} dicts.
    """
    yt_dir = os.path.join(out_dir, 'youtube')
    os.makedirs(yt_dir, exist_ok=True)
    results = []
    last_run = state.get('last_run', '')

    for name, channel_url in YOUTUBE_CHANNELS:
        print(f'  YouTube: {name}...', end=' ', flush=True)
        try:
            videos = digest_channel(channel_url, max_videos=3, since=last_run)
        except Exception as e:
            print(f'ERROR: {e}')
            continue

        count = 0
        for v in videos:
            if v.transcript.startswith('['):
                # Error marker — skip
                continue

            fname = _safe_filename(f'{name}--{v.title[:60]}') + '.txt'
            fpath = os.path.join(yt_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(v.transcript)

            results.append({
                'source': v.channel or name,
                'source_url': channel_url,
                'title': v.title,
                'url': v.url,
                'published': v.published,
                'file': fpath,
                'video_id': v.video_id,
                'type': 'video',
            })
            count += 1

        print(f'{count} videos' if count else 'no new')

    return results


# ── Web fetching ────────────────────────────────────────────────────────────

def fetch_web(state: dict, out_dir: str) -> list[dict]:
    """Fetch web source pages, write to out_dir/web/.

    Returns list of {source, title, url, published, file, content_hash} dicts.
    """
    web_dir = os.path.join(out_dir, 'web')
    os.makedirs(web_dir, exist_ok=True)
    results = []

    for name, url in WEB_SOURCES:
        print(f'  Web: {name}...', end=' ', flush=True)
        try:
            headers = BROWSER_HEADERS if any(d in url for d in BROWSER_UA_DOMAINS) else HEADERS
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            print(f'UNREACHABLE: {e}')
            # Write error marker
            fname = _safe_filename(name) + '.txt'
            fpath = os.path.join(web_dir, fname)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(f'[UNREACHABLE: {e}]')
            results.append({
                'source': name,
                'source_url': url,
                'title': f'{name} [UNREACHABLE]',
                'url': url,
                'published': '',
                'file': fpath,
                'content_hash': '',
                'type': 'web',
                'unreachable': True,
            })
            continue

        h = content_hash(content)

        # Check if content changed since last fetch
        updated = is_updated(state, url, url, h)
        if not is_new(state, url, url) and not updated:
            print('unchanged')
            continue

        fname = _safe_filename(name) + '.txt'
        fpath = os.path.join(web_dir, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)

        results.append({
            'source': name,
            'source_url': url,
            'title': name,
            'url': url,
            'published': date.today().isoformat(),
            'file': fpath,
            'content_hash': h,
            'updated': updated,
            'type': 'web',
        })
        print('updated' if updated else 'new')

    return results


# ── Manifest ────────────────────────────────────────────────────────────────

def write_manifest(results: list[dict], out_dir: str) -> str:
    """Write a manifest.json summarizing what was fetched.

    Claude reads this manifest to know what files to analyze.
    """
    manifest_path = os.path.join(out_dir, 'manifest.json')
    manifest = {
        'date': date.today().isoformat(),
        'fetched_at': datetime.now().isoformat(),
        'total_items': len(results),
        'items': results,
    }
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write('\n')
    return manifest_path


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    rss_only = '--rss-only' in sys.argv
    youtube_only = '--youtube-only' in sys.argv
    web_only = '--web-only' in sys.argv
    all_sources = not (rss_only or youtube_only or web_only)

    state = load_state()
    out_dir = _output_dir()
    all_results = []

    print(f'Intake fetch — {date.today().isoformat()}')
    print(f'Output: {out_dir}')
    print(f'Last run: {state.get("last_run", "(never)")}')
    print()

    if all_sources or rss_only:
        print('Fetching RSS feeds...')
        all_results.extend(fetch_rss(state, out_dir))
        print()

    if all_sources or youtube_only:
        print('Fetching YouTube channels...')
        all_results.extend(fetch_youtube(state, out_dir))
        print()

    if all_sources or web_only:
        print('Fetching web sources...')
        all_results.extend(fetch_web(state, out_dir))
        print()

    # Write manifest for Claude to read
    manifest_path = write_manifest(all_results, out_dir)
    new_count = len([r for r in all_results if not r.get('unreachable')])
    print(f'Done. {new_count} items fetched, manifest at {manifest_path}')

    return all_results


if __name__ == '__main__':
    main()
