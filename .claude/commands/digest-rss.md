# Digest: RSS Sources

Fetch new content from RSS-based sources and write partial digest results.

**This skill is called by `/intake` as part of a parallel fan-out. Do not run standalone.**

## What To Do

1. **Load state:**
   ```python
   from intake.state import load_state, is_new, is_updated, mark_seen, content_hash
   state = load_state()
   ```

2. **Fetch these RSS feeds** using `intake/rss.py`, max 3 entries each:

   | Source | Feed URL | Source URL |
   |--------|----------|------------|
   | LangChain Blog | https://blog.langchain.dev/rss/ | https://blog.langchain.dev |
   | Latent Space | https://www.latent.space/feed | https://www.latent.space |
   | Nathan Lambert — Interconnects | https://www.interconnects.ai/feed | https://www.interconnects.ai |
   | Import AI — Jack Clark | https://importai.substack.com/feed | https://importai.substack.com |
   | Ethan Mollick — One Useful Thing | https://www.oneusefulthing.org/feed | https://www.oneusefulthing.org |
   | Simon Willison | https://simonwillison.net/atom/everything/ | https://simonwillison.net |
   | Sebastian Raschka — Ahead of AI | https://magazine.sebastianraschka.com/feed | https://magazine.sebastianraschka.com |
   | arXiv cs.AI | https://arxiv.org/rss/cs.AI | https://arxiv.org/list/cs.AI/recent |

   ```python
   from intake.rss import fetch_new_entries
   entries = fetch_new_entries(feed_url, state, source_url, source_name='...', max_entries=3)
   ```

3. **For each new entry**, use `WebFetch` on the entry URL to get full content. Extract:
   - **Key ideas** — 2-5 most important concepts
   - **Techniques and methods** — novel approaches or architectures
   - **Results and evidence** — what was demonstrated or claimed
   - **Quotes** — 1-3 verbatim quotes with attribution
   - **Relevance signal** — one sentence on why this matters for agent coordination

4. **Write results** to `intake/digests/.partial-rss-<YYYY-MM-DD>.md` using the digest entry format:
   ```markdown
   ## <N>. <Title>
   **Source:** <source name>
   **URL:** <url>
   **Type:** article | paper | newsletter
   **Published:** <date>

   ### Key Ideas
   - ...
   ### Techniques & Methods
   - ...
   ### Results & Evidence
   - ...
   ### Notable Quotes
   > "..." — <attribution>
   ### Relevance Signal
   <one sentence>
   ```

5. **Track what was processed** — at the end of the file, append a machine-readable block:
   ```markdown
   <!-- PROCESSED
   source_url|content_url|published_date
   source_url|content_url|published_date
   -->
   ```

## Digest Diff — Detecting Updated Content

After fetching full content for an entry, check if it's an update to previously-seen content:

```python
from intake.state import is_updated, content_hash
h = content_hash(fetched_text)
if is_updated(state, source_url, entry_url, h):
    # This URL was seen before but content changed — flag as [UPDATED]
```

When an entry is updated (not new), prefix its title with `[UPDATED]` in the digest. Focus the summary on **what changed** rather than re-summarizing the whole piece.

When calling `mark_seen`, include the hash:
```python
mark_seen(state, source_url, entry_url, date=published, content_hash=h)
```

## Important
- Only process NEW or UPDATED entries (use state for dedup, content_hash for diff).
- If a feed is unreachable, note it as `[UNREACHABLE: <error>]`.
- For arXiv, the RSS contains abstracts — that's enough for the digest entry, no need to fetch the full paper.
- If no new or updated entries are found across all feeds, write a file containing only `<!-- NO NEW CONTENT -->`.
