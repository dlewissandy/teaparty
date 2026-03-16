# Digest: Web Sources

Fetch new content from web-based sources (no RSS, no YouTube) and write partial digest results.

**This skill is called by `/intake` as part of a parallel fan-out. Do not run standalone.**

## What To Do

1. **Load state:**
   ```python
   from intake.state import load_state, is_new, is_updated, mark_seen, content_hash
   state = load_state()
   ```

2. **Fetch these web sources** using `WebFetch`:

   | Source | URL |
   |--------|-----|
   | Anthropic | https://www.anthropic.com/news |
   | OpenAI | https://openai.com/news |
   | Lilian Weng — Lil'Log | https://lilianweng.github.io |
   | BAIR Blog | https://bair.berkeley.edu/blog |
   | Allen Institute for AI | https://allenai.org/blog |
   | Hugging Face Papers | https://huggingface.co/papers |

3. **For each source:**
   - `WebFetch` the URL to get the page content
   - Identify the most recent post/article on the page
   - Check `is_new(state, source_url, article_url, date=published_date)` — skip if already seen
   - For new articles, `WebFetch` the article URL if it's different from the listing page
   - Extract:
     - **Key ideas** — 2-5 most important concepts
     - **Techniques and methods** — novel approaches
     - **Results and evidence** — what was demonstrated or claimed
     - **Quotes** — 1-3 verbatim quotes with attribution
     - **Relevance signal** — one sentence on why this matters for agent coordination

4. **Write results** to `intake/digests/.partial-web-<YYYY-MM-DD>.md` using the digest entry format:
   ```markdown
   ## <N>. <Title>
   **Source:** <source name>
   **URL:** <url>
   **Type:** article | paper | blog post
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

5. **Track what was processed** — at the end of the file, append:
   ```markdown
   <!-- PROCESSED
   source_url|content_url|published_date
   -->
   ```

## Digest Diff — Detecting Updated Content

After fetching full article content, check if it's an update to a previously-seen URL:

```python
h = content_hash(fetched_text)
if not is_new(state, source_url, article_url) and is_updated(state, source_url, article_url, h):
    # Same URL, different content — flag as [UPDATED]
```

When an article is updated (not new), prefix its title with `[UPDATED]` in the digest. Focus the summary on **what changed** rather than re-summarizing the whole piece.

When calling `mark_seen`, include the hash:
```python
mark_seen(state, source_url, article_url, date=published, content_hash=h)
```

## Important
- Only process NEW or UPDATED content (use state for dedup, content_hash for diff).
- These are listing/index pages — look for the most recent 1-2 articles, don't try to process the entire archive.
- For Hugging Face Papers, focus on papers with "agent", "coordination", "multi-agent", "RLHF", or "human-AI" in the title.
- If a source is unreachable, note it as `[UNREACHABLE: <error>]`.
- If no new or updated content found, write a file containing only `<!-- NO NEW CONTENT -->`.
