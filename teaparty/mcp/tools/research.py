"""Research tools: YouTube transcripts, arXiv, Semantic Scholar, PubMed."""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, quote_plus


# ── YouTube transcript ────────────────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    """Extract YouTube video ID from a URL or return the string as-is."""
    # youtu.be/ID
    m = re.search(r'youtu\.be/([A-Za-z0-9_-]{11})', url)
    if m:
        return m.group(1)
    # youtube.com/watch?v=ID
    m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', url)
    if m:
        return m.group(1)
    # bare ID (11 chars, youtube ID charset)
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', url.strip()):
        return url.strip()
    raise ValueError(f'Cannot extract YouTube video ID from: {url!r}')


async def youtube_transcript_handler(url: str, include_timestamps: bool = False) -> str:
    """Retrieve the transcript for a YouTube video.

    Args:
        url: YouTube video URL (youtube.com/watch?v=..., youtu.be/...) or bare video ID.
        include_timestamps: If True, prefix each line with its timestamp in [MM:SS] format.

    Returns:
        Full transcript text, one line per caption entry.
    """
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

    try:
        video_id = _extract_video_id(url)
    except ValueError as exc:
        return f'Error: {exc}'

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Prefer manually-created transcripts; fall back to auto-generated.
        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
        except Exception:
            transcript = transcript_list.find_generated_transcript(['en'])
        entries = transcript.fetch()
    except TranscriptsDisabled:
        return f'Error: transcripts are disabled for video {video_id}.'
    except NoTranscriptFound:
        return f'Error: no English transcript found for video {video_id}.'
    except Exception as exc:
        return f'Error retrieving transcript for {video_id}: {exc}'

    lines = []
    for entry in entries:
        text = entry.get('text', '').replace('\n', ' ').strip()
        if include_timestamps:
            seconds = int(entry.get('start', 0))
            mm, ss = divmod(seconds, 60)
            lines.append(f'[{mm:02d}:{ss:02d}] {text}')
        else:
            lines.append(text)

    return '\n'.join(lines)


# ── arXiv ────────────────────────────────────────────────────────────────────

async def arxiv_search_handler(query: str, max_results: int = 10) -> str:
    """Search arXiv for papers matching a query.

    Args:
        query: Search query (supports arXiv query syntax, e.g. "ti:transformer AND cat:cs.LG").
        max_results: Maximum number of results to return (1–50).

    Returns:
        Formatted list of papers with title, authors, year, abstract summary, and arXiv URL.
    """
    import aiohttp

    max_results = min(max(1, max_results), 50)
    params = urlencode({
        'search_query': f'all:{query}',
        'max_results': max_results,
        'sortBy': 'relevance',
        'sortOrder': 'descending',
    })
    url = f'http://export.arxiv.org/api/query?{params}'

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return f'Error: arXiv API returned status {resp.status}'
                xml_text = await resp.text()
    except Exception as exc:
        return f'Error contacting arXiv API: {exc}'

    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'arxiv': 'http://arxiv.org/schemas/atom',
    }
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return f'Error parsing arXiv response: {exc}'

    entries = root.findall('atom:entry', ns)
    if not entries:
        return f'No arXiv results found for query: {query!r}'

    results = []
    for entry in entries:
        title = (entry.findtext('atom:title', '', ns) or '').replace('\n', ' ').strip()
        authors = [
            a.findtext('atom:name', '', ns)
            for a in entry.findall('atom:author', ns)
        ]
        published = (entry.findtext('atom:published', '', ns) or '')[:4]  # year
        abstract = (entry.findtext('atom:summary', '', ns) or '').replace('\n', ' ').strip()
        if len(abstract) > 300:
            abstract = abstract[:297] + '...'
        link = ''
        for l in entry.findall('atom:link', ns):
            if l.get('type') == 'text/html':
                link = l.get('href', '')
                break

        results.append(
            f'**{title}** ({published})\n'
            f'Authors: {", ".join(authors[:5])}{"..." if len(authors) > 5 else ""}\n'
            f'Abstract: {abstract}\n'
            f'URL: {link}'
        )

    return f'arXiv results for {query!r} ({len(results)} of {max_results} requested):\n\n' + \
           '\n\n---\n\n'.join(results)


# ── Semantic Scholar ──────────────────────────────────────────────────────────

async def semantic_scholar_search_handler(query: str, max_results: int = 10) -> str:
    """Search Semantic Scholar for academic papers.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (1–100).

    Returns:
        Formatted list of papers with title, authors, year, citation count, and URL.
    """
    import aiohttp

    max_results = min(max(1, max_results), 100)
    fields = 'title,authors,year,abstract,citationCount,url,externalIds'
    params = urlencode({
        'query': query,
        'fields': fields,
        'limit': max_results,
    })
    api_url = f'https://api.semanticscholar.org/graph/v1/paper/search?{params}'

    headers = {}
    api_key = os.environ.get('S2_API_KEY', '')
    if api_key:
        headers['x-api-key'] = api_key

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f'Error: Semantic Scholar API returned status {resp.status}'
                data = await resp.json()
    except Exception as exc:
        return f'Error contacting Semantic Scholar API: {exc}'

    papers = data.get('data', [])
    if not papers:
        return f'No Semantic Scholar results found for query: {query!r}'

    results = []
    for paper in papers:
        title = paper.get('title') or '(no title)'
        year = paper.get('year') or '?'
        authors = [a.get('name', '') for a in (paper.get('authors') or [])]
        citations = paper.get('citationCount', 0)
        abstract = (paper.get('abstract') or '').replace('\n', ' ').strip()
        if len(abstract) > 300:
            abstract = abstract[:297] + '...'
        url = paper.get('url') or ''

        results.append(
            f'**{title}** ({year}) — {citations} citations\n'
            f'Authors: {", ".join(authors[:5])}{"..." if len(authors) > 5 else ""}\n'
            f'Abstract: {abstract}\n'
            f'URL: {url}'
        )

    return f'Semantic Scholar results for {query!r} ({len(results)} results):\n\n' + \
           '\n\n---\n\n'.join(results)


# ── PubMed ───────────────────────────────────────────────────────────────────

async def pubmed_search_handler(query: str, max_results: int = 10) -> str:
    """Search PubMed for biomedical literature.

    Args:
        query: PubMed search query (supports MeSH terms, field tags, boolean operators).
        max_results: Maximum number of results to return (1–100).

    Returns:
        Formatted list of articles with title, authors, journal, year, PMID, and abstract.
    """
    import aiohttp

    max_results = min(max(1, max_results), 100)
    api_key = os.environ.get('NCBI_API_KEY', '')

    # Step 1: esearch to get PMIDs
    search_params: dict = {
        'db': 'pubmed',
        'term': query,
        'retmax': max_results,
        'retmode': 'json',
        'sort': 'relevance',
    }
    if api_key:
        search_params['api_key'] = api_key

    try:
        async with aiohttp.ClientSession() as session:
            search_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
            async with session.get(
                search_url,
                params=search_params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f'Error: PubMed esearch returned status {resp.status}'
                search_data = await resp.json()

            ids = search_data.get('esearchresult', {}).get('idlist', [])
            if not ids:
                return f'No PubMed results found for query: {query!r}'

            # Step 2: esummary to get article metadata
            summary_params: dict = {
                'db': 'pubmed',
                'id': ','.join(ids),
                'retmode': 'json',
            }
            if api_key:
                summary_params['api_key'] = api_key

            summary_url = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'
            async with session.get(
                summary_url,
                params=summary_params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f'Error: PubMed esummary returned status {resp.status}'
                summary_data = await resp.json()

    except Exception as exc:
        return f'Error contacting PubMed API: {exc}'

    result_map = summary_data.get('result', {})
    results = []
    for pmid in ids:
        article = result_map.get(pmid, {})
        if not article or pmid == 'uids':
            continue
        title = article.get('title') or '(no title)'
        authors = [a.get('name', '') for a in (article.get('authors') or [])]
        journal = article.get('fulljournalname') or article.get('source') or ''
        pub_date = article.get('pubdate') or ''
        results.append(
            f'**{title}**\n'
            f'Authors: {", ".join(authors[:5])}{"..." if len(authors) > 5 else ""}\n'
            f'Journal: {journal} ({pub_date})\n'
            f'PMID: {pmid} — https://pubmed.ncbi.nlm.nih.gov/{pmid}/'
        )

    if not results:
        return f'No PubMed results found for query: {query!r}'

    return f'PubMed results for {query!r} ({len(results)} results):\n\n' + \
           '\n\n---\n\n'.join(results)
