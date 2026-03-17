#!/usr/bin/env python3
"""Create GitHub issues for Explore items from the intake analysis.

Runs OUTSIDE Claude Code — no permission issues with quoting or Bash.

Features:
- Deduplicates against existing open issues (fuzzy title match)
- Adds issues to the TeaParty GitHub project backlog
- Sets Source field to 'research-intake'
- Updates idea files with issue numbers

Usage:
    uv run python -m intake.create_issues intake/analysis/analysis-2026-03-16.md
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REPO = 'dlewissandy/teaparty'
PROJECT_NUMBER = 2
PROJECT_OWNER = 'dlewissandy'
PROJECT_ID = 'PVT_kwHOAH4OHc4BR81E'  # Node ID for gh project item-edit
LABEL = 'intake'

# Field and option IDs for the TeaParty project board
STATUS_FIELD_ID = 'PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs'
STATUS_BACKLOG_ID = 'a76a90c5'
SOURCE_FIELD_ID = 'PVTSSF_lAHOAH4OHc4BR81Ezg_oGlo'
SOURCE_INTAKE_ID = 'eced27cf'


def _run_gh(*args: str, input_text: str = '') -> str:
    """Run a gh CLI command and return stdout."""
    cmd = ['gh'] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=30,
        input=input_text or None,
    )
    if result.returncode != 0:
        print(f'  gh error: {result.stderr.strip()}', file=sys.stderr)
    return result.stdout.strip()


def _ensure_label() -> None:
    """Create the intake label if it doesn't exist."""
    _run_gh('label', 'create', LABEL,
            '--description', 'Research intake pipeline',
            '--color', '0E8A16',
            '--force',
            '--repo', REPO)


def _get_open_issues() -> list[dict]:
    """Fetch all open issues for duplicate checking."""
    output = _run_gh('issue', 'list',
                     '--state', 'open',
                     '--limit', '200',
                     '--json', 'number,title',
                     '--repo', REPO)
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip punctuation, remove stop words."""
    import re as _re
    stop = {
        'add', 'implement', 'investigate', 'evaluate', 'integrate', 'build',
        'create', 'use', 'using', 'for', 'from', 'the', 'a', 'an', 'in',
        'on', 'at', 'to', 'of', 'and', 'with', 'via', 'into', 'by',
        'new', 'based', 'system', 'approach',
    }
    text = _re.sub(r'[^a-z0-9\s]', ' ', text.lower())
    words = [w for w in text.split() if w not in stop and len(w) > 1]
    return ' '.join(words)


def _bigrams(text: str) -> set[str]:
    """Extract character bigrams from normalized text for fuzzy matching."""
    text = _normalize(text)
    if len(text) < 2:
        return set()
    return {text[i:i+2] for i in range(len(text) - 1)}


def _is_duplicate(title: str, existing: list[dict]) -> int | None:
    """Check if a similar issue already exists using bigram similarity.

    Uses Dice coefficient on character bigrams of normalized text.
    This catches semantic near-duplicates like:
      "Add autonomous context compression" vs
      "Investigate agent-controlled context compression for CfA phase boundaries"

    Returns the issue number of the duplicate, or None.
    """
    title_bigrams = _bigrams(title)
    if not title_bigrams:
        return None

    for issue in existing:
        issue_bigrams = _bigrams(issue['title'])
        if not issue_bigrams:
            continue

        # Dice coefficient: 2 * |intersection| / (|A| + |B|)
        intersection = len(title_bigrams & issue_bigrams)
        dice = (2 * intersection) / (len(title_bigrams) + len(issue_bigrams))

        if dice >= 0.45:
            return issue['number']

    return None


def _create_issue(title: str, body: str) -> int | None:
    """Create a GitHub issue and return its number."""
    output = _run_gh('issue', 'create',
                     '--title', title,
                     '--label', LABEL,
                     '--body', body,
                     '--repo', REPO)
    # Output is the issue URL like https://github.com/user/repo/issues/123
    match = re.search(r'/issues/(\d+)', output)
    if match:
        return int(match.group(1))
    return None


def _add_to_project(issue_number: int) -> None:
    """Add an issue to the TeaParty project and set Status=Backlog, Source=research-intake."""
    item_url = f'https://github.com/{REPO}/issues/{issue_number}'

    # Add to project
    _run_gh('project', 'item-add', str(PROJECT_NUMBER),
            '--owner', PROJECT_OWNER,
            '--url', item_url)

    # Find the item ID we just added
    items_json = _run_gh('project', 'item-list', str(PROJECT_NUMBER),
                         '--owner', PROJECT_OWNER,
                         '--format', 'json')
    if not items_json:
        return

    try:
        items = json.loads(items_json)
    except json.JSONDecodeError:
        return

    item_id = None
    for item in items.get('items', []):
        if item.get('content', {}).get('number') == issue_number:
            item_id = item.get('id')
            break

    if not item_id:
        return

    # Set Status=Backlog (uses --project-id node ID, not --owner)
    _run_gh('project', 'item-edit',
            '--project-id', PROJECT_ID,
            '--id', item_id,
            '--field-id', STATUS_FIELD_ID,
            '--single-select-option-id', STATUS_BACKLOG_ID)

    # Set Source=research-intake
    _run_gh('project', 'item-edit',
            '--project-id', PROJECT_ID,
            '--id', item_id,
            '--field-id', SOURCE_FIELD_ID,
            '--single-select-option-id', SOURCE_INTAKE_ID)


def _update_idea_file(ideas_dir: str, slug: str, issue_number: int) -> None:
    """Update an idea file's Status line with the issue number."""
    # Find matching idea file
    for fname in os.listdir(ideas_dir):
        if slug in fname.lower().replace('-', ' ').replace('_', ' '):
            fpath = os.path.join(ideas_dir, fname)
            try:
                with open(fpath, encoding='utf-8') as f:
                    content = f.read()
                updated = re.sub(
                    r'\*\*Status:\*\*\s*New.*',
                    f'**Status:** New (Issue #{issue_number})',
                    content,
                )
                if updated != content:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(updated)
                    print(f'  Updated {fname} with Issue #{issue_number}')
            except OSError:
                pass
            break


def parse_analysis(analysis_path: str) -> list[dict]:
    """Parse the analysis file to extract Explore items with details."""
    with open(analysis_path, encoding='utf-8') as f:
        content = f.read()

    explores = []

    # Find explore items from the summary matrix
    in_table = False
    for line in content.split('\n'):
        if '| # |' in line or '|---|' in line:
            in_table = True
            continue
        if in_table and line.startswith('|'):
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if len(cells) >= 4:
                verdict = cells[3].strip().lower().replace('*', '')
                if verdict == 'explore':
                    title = cells[1].strip().replace('*', '')
                    source = cells[2].strip().replace('*', '') if len(cells) > 2 else ''
                    explores.append({'title': title, 'source': source})
        elif in_table and not line.startswith('|'):
            in_table = False

    # Enrich with details from the detailed sections
    # Also load digest for URLs
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(analysis_path))
    digest_content = ''
    if date_match:
        digest_path = os.path.join(
            os.path.dirname(analysis_path), '..', 'digests',
            f'digest-{date_match.group(1)}.md',
        )
        if os.path.exists(digest_path):
            with open(digest_path, encoding='utf-8') as f:
                digest_content = f.read()

    # Build URL and techniques maps from digest
    digest_urls = {}
    digest_techniques = {}
    if digest_content:
        for sec in re.split(r'\n(?=##\s+\d+\.)', digest_content):
            header = re.match(r'##\s+\d+\.\s+(.+)\n', sec)
            if not header:
                continue
            name = header.group(1).strip().lower()
            url_line = re.search(r'\*\*URL:\*\*\s*(https?://\S+)', sec)
            if url_line:
                digest_urls[name] = url_line.group(1).rstrip(').,')
            # Extract Techniques & Methods section
            tech_match = re.search(
                r'###\s+Techniques\s+&\s+Methods\s*\n(.*?)(?=\n###|\n---|\Z)',
                sec, re.DOTALL,
            )
            if tech_match:
                digest_techniques[name] = tech_match.group(1).strip()

    # Extract detailed assessment for each explore item
    sections = re.split(r'\n(?=#{2,4}\s+)', content)
    for item in explores:
        name_lower = item['title'].lower()

        # Find URL from digest (fuzzy)
        url = digest_urls.get(name_lower, '')
        if not url:
            item_words = set(name_lower.split())
            for dk, durl in digest_urls.items():
                dk_words = set(dk.split())
                overlap = len(item_words & dk_words)
                if overlap >= len(item_words) * 0.6:
                    url = durl
                    break
        item['url'] = url

        # Find techniques from digest (fuzzy match)
        techniques = digest_techniques.get(name_lower, '')
        if not techniques:
            for dk, dt in digest_techniques.items():
                dk_words = set(dk.split())
                overlap = len(item_words & dk_words) if 'item_words' in dir() else 0
                if not techniques:
                    item_words_local = set(name_lower.split())
                    for dk2, dt2 in digest_techniques.items():
                        dk2_words = set(dk2.split())
                        if len(item_words_local & dk2_words) >= len(item_words_local) * 0.6:
                            techniques = dt2
                            break
        item['techniques'] = techniques

        # Find assessment section
        for sec in sections:
            if name_lower in sec.lower():
                # Extract first substantive paragraph
                for para in sec.split('\n\n'):
                    para = para.strip()
                    if para and not para.startswith('#') and not para.startswith('**Verdict') and len(para) > 30:
                        item['detail'] = para
                        break
                # Extract a quote if present
                quote_match = re.search(r'>\s*"(.+?)"', sec)
                if quote_match:
                    item['quote'] = quote_match.group(1)
                break

    return explores


def build_issue_body(item: dict, analysis_path: str) -> str:
    """Build a well-formed issue body modeled on INTENT.md quality standards.

    The issue body should read like an intent document: what outcome,
    why it matters, how to judge success, what it touches, and where
    the idea came from. A reader should be able to pick up this issue
    and start working without reading the digest or analysis.
    """
    detail = item.get('detail', '')
    url = item.get('url', '')
    source = item.get('source', '')
    quote = item.get('quote', '')
    techniques = item.get('techniques', '')
    date = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(analysis_path))
    date_str = date.group(1) if date else ''
    slug = re.sub(r'[^a-z0-9]+', '-', item['title'].lower()).strip('-')

    body = f"""## Why This Exists

{detail}

## Objective

Investigate and adapt the techniques from this research for the TeaParty orchestrator. The goal is not to replicate the paper's system wholesale, but to extract the specific patterns that address a current gap or limitation in our architecture.

## What It Would Touch

This needs investigation during planning. The idea file (`intake/ideas/{slug}.md`) contains a preliminary sketch of affected components, but the actual scope should be determined by reading the source material and the current codebase together.

## Success Criteria

1. The relevant technique is understood well enough to write a concrete implementation plan
2. The plan identifies specific files and modules that would change
3. The approach is validated against TeaParty's design principles (agents are autonomous, workflows are advisory, no silent fallbacks)

## Source

{source} — {url}
"""
    if quote:
        body += f'\n> "{quote}"\n'

    if techniques:
        body += f"""
### Key Techniques from Source

{techniques}
"""

    body += f"""
---
Idea file: `intake/ideas/{slug}.md`
Analysis: `intake/analysis/analysis-{date_str}.md`
"""
    return body.strip()


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m intake.create_issues <analysis-file>')
        sys.exit(1)

    analysis_path = sys.argv[1]
    if not os.path.exists(analysis_path):
        print(f'Analysis file not found: {analysis_path}')
        sys.exit(1)

    print(f'Parsing {analysis_path}...')
    explores = parse_analysis(analysis_path)

    if not explores:
        print('No Explore items found.')
        return

    print(f'Found {len(explores)} Explore items')

    # Ensure label exists
    _ensure_label()

    # Get existing issues for dedup
    existing = _get_open_issues()
    print(f'Checking against {len(existing)} open issues')

    ideas_dir = os.path.join(os.path.dirname(analysis_path), '..', 'ideas')
    created = []

    for item in explores:
        title = f"Add {item['title'].lower()}" if not item['title'].startswith(('Add', 'Implement', 'Evaluate', 'Integrate')) else item['title']

        # Check for duplicates
        dup = _is_duplicate(title, existing)
        if dup:
            print(f'  SKIP (duplicate of #{dup}): {title}')
            continue

        body = build_issue_body(item, analysis_path)
        print(f'  Creating: {title}')
        issue_num = _create_issue(title, body)

        if issue_num:
            print(f'  Created #{issue_num}')
            # Add to project backlog
            _add_to_project(issue_num)
            print(f'  Added #{issue_num} to project backlog')

            # Update idea file
            slug = re.sub(r'[^a-z0-9]+', '-', item['title'].lower()).strip('-')
            if os.path.isdir(ideas_dir):
                _update_idea_file(ideas_dir, slug, issue_num)

            created.append((issue_num, title))
            # Add to existing for dedup within this batch
            existing.append({'number': issue_num, 'title': title})
        else:
            print(f'  FAILED to create issue: {title}')

    print(f'\nDone. Created {len(created)} issues:')
    for num, title in created:
        print(f'  #{num}: {title}')


if __name__ == '__main__':
    main()
