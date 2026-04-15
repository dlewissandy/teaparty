"""Patent search tools: USPTO PatentsView and EPO Open Patent Services."""
from __future__ import annotations

import json
import os
from urllib.parse import urlencode


# ── USPTO PatentsView ─────────────────────────────────────────────────────────

async def patent_search_uspto_handler(query: str, max_results: int = 10) -> str:
    """Search US patents via the USPTO PatentsView API.

    No API key required. Returns patent numbers, titles, assignees, filing
    dates, and abstracts.

    Args:
        query: Keyword query to search in patent titles and abstracts.
        max_results: Maximum number of results to return (1–25).

    Returns:
        Formatted list of matching patents.
    """
    import aiohttp

    max_results = min(max(1, max_results), 25)

    payload = {
        'q': {'_text_any': {'patent_title': query, 'patent_abstract': query}},
        'f': ['patent_number', 'patent_title', 'patent_date', 'patent_abstract',
              'assignee_organization', 'inventor_last_name'],
        'o': {'per_page': max_results, 'sort': [{'patent_date': 'desc'}]},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                'https://api.patentsview.org/patents/query',
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f'Error: USPTO API returned status {resp.status}: {text[:200]}'
                data = await resp.json()
    except Exception as exc:
        return f'Error contacting USPTO PatentsView API: {exc}'

    patents = data.get('patents') or []
    if not patents:
        return f'No USPTO patents found for query: {query!r}'

    results = []
    for p in patents:
        number = p.get('patent_number') or '?'
        title = p.get('patent_title') or '(no title)'
        date = p.get('patent_date') or '?'
        abstract = (p.get('patent_abstract') or '').strip()
        if len(abstract) > 300:
            abstract = abstract[:297] + '...'
        assignees = [
            a.get('assignee_organization') or ''
            for a in (p.get('assignees') or [])
            if a.get('assignee_organization')
        ]
        url = f'https://patents.google.com/patent/US{number}'
        results.append(
            f'**US{number}** — {title}\n'
            f'Filed/Issued: {date}'
            + (f'\nAssignee: {", ".join(assignees)}' if assignees else '') +
            f'\nAbstract: {abstract}\n'
            f'URL: {url}'
        )

    return f'USPTO results for {query!r} ({len(results)} patents):\n\n' + \
           '\n\n---\n\n'.join(results)


# ── EPO Open Patent Services ──────────────────────────────────────────────────

async def patent_search_epo_handler(query: str, max_results: int = 10) -> str:
    """Search European patents via EPO Open Patent Services (OPS).

    Requires EPO_OPS_KEY and EPO_OPS_SECRET environment variables.
    Register at https://developers.epo.org/ to obtain credentials.

    Args:
        query: CQL query string (e.g. 'ti="machine learning" AND pa="Google"').
        max_results: Maximum number of results to return (1–25).

    Returns:
        Formatted list of matching EP patents.
    """
    import aiohttp

    client_id = os.environ.get('EPO_OPS_KEY', '')
    client_secret = os.environ.get('EPO_OPS_SECRET', '')
    if not client_id or not client_secret:
        return (
            'Error: EPO_OPS_KEY and EPO_OPS_SECRET environment variables are required. '
            'Register at https://developers.epo.org/ to obtain credentials.'
        )

    max_results = min(max(1, max_results), 25)

    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: OAuth token
            async with session.post(
                'https://ops.epo.org/3.2/auth/accesstoken',
                data={'grant_type': 'client_credentials'},
                auth=aiohttp.BasicAuth(client_id, client_secret),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return f'Error: EPO OAuth failed with status {resp.status}'
                token_data = await resp.json()
                token = token_data.get('access_token', '')

            if not token:
                return 'Error: EPO OAuth returned no access token.'

            # Step 2: Search
            search_url = 'https://ops.epo.org/3.2/rest-services/published-data/search'
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            }
            params = {
                'q': query,
                'Range': f'1-{max_results}',
            }
            async with session.get(
                search_url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f'Error: EPO search returned status {resp.status}: {text[:200]}'
                data = await resp.json()

    except Exception as exc:
        return f'Error contacting EPO OPS API: {exc}'

    try:
        docs = (
            data
            .get('ops:world-patent-data', {})
            .get('ops:biblio-search', {})
            .get('ops:search-result', {})
            .get('exchange-documents', [])
        )
        if isinstance(docs, dict):
            docs = [docs]
    except (AttributeError, TypeError):
        docs = []

    if not docs:
        return f'No EPO results found for query: {query!r}'

    results = []
    for doc in docs[:max_results]:
        exch = doc.get('exchange-document', doc)
        doc_id = exch.get('@doc-number') or exch.get('@country', '') + exch.get('@doc-number', '')
        country = exch.get('@country', 'EP')
        title_section = exch.get('bibliographic-data', {}).get('invention-title', [])
        if isinstance(title_section, list):
            title = next((t.get('$', '') for t in title_section if t.get('@lang') == 'en'), '')
            title = title or (title_section[0].get('$', '') if title_section else '(no title)')
        elif isinstance(title_section, dict):
            title = title_section.get('$', '(no title)')
        else:
            title = '(no title)'
        url = f'https://worldwide.espacenet.com/patent/search?q={doc_id}'
        results.append(f'**{country}{doc_id}** — {title}\nURL: {url}')

    return f'EPO results for {query!r} ({len(results)} patents):\n\n' + \
           '\n\n---\n\n'.join(results)
