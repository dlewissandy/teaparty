# Research Digest

Fetch new content from curated sources and produce a detailed summary document.

## What To Do

1. **Read the source list** from `intake/sources.md`. Each entry has a URL, fetch strategy (`rss`, `web`, or `youtube`), and description.

2. **Load state** to avoid re-digesting old content:
   ```python
   from intake.state import load_state, is_new, mark_seen, save_state
   state = load_state()
   ```

3. **Fetch new content by strategy.** Process sources in this order to manage context:

   ### RSS sources (newsletters, blogs with feeds)
   Use `intake/rss.py` to fetch only new entries:
   ```python
   from intake.rss import fetch_new_entries
   entries = fetch_new_entries(feed_url, state, source_url, source_name='...', max_entries=3)
   ```
   For each new entry, use `WebFetch` on the entry URL to get full content.

   ### YouTube channels
   Use `intake/youtube.py` to fetch recent videos with transcripts:
   ```python
   from intake.youtube import digest_channel
   last_run = state.get('last_run', '')  # only fetch videos since last completed run
   results = digest_channel(channel_url, max_videos=3, since=last_run)
   ```

   ### Web sources (blogs without RSS)
   Use `WebFetch` on the source URL. Check `is_new(state, url, page_url)` before processing.

4. **For each NEW piece of content, extract:**
   - **Key ideas** — the 2-5 most important concepts, findings, or proposals
   - **Techniques and methods** — any novel approaches, architectures, or algorithms
   - **Results and evidence** — what was demonstrated, measured, or claimed
   - **Quotes** — 1-3 verbatim quotes that capture the essence (with attribution)
   - **Relevance signal** — a one-sentence note on why this might matter for agent coordination, human-agent collaboration, or learning systems

5. **Write the digest** to `intake/digests/digest-<YYYY-MM-DD>.md` using today's date.

6. **Only after the digest is fully written**, save state so the next run skips these items:
   ```python
   from datetime import date
   for source_url, content_url, published_date in processed_items:
       mark_seen(state, source_url, content_url, date=published_date)
   state['last_run'] = date.today().isoformat()
   save_state(state)
   ```
   State is saved AFTER completion so that a failed/interrupted run re-processes everything on the next attempt.

## Output Format

```markdown
# Research Digest — <YYYY-MM-DD>

New items found: <count>
Sources checked: <count>

---

## 1. <Source title>
**Source:** <source name>
**URL:** <url>
**Type:** article | paper | video | podcast
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

---

## 2. <next item>
...
```

## Important

- **Only digest NEW content.** Use the state file to skip items already processed. If nothing is new, write a digest that says "No new content found" — don't re-process old items.
- **Do not skip videos.** Use `intake.youtube.digest_channel()` to fetch transcripts. Video sources often contain the most valuable insights.
- If a source is unreachable, note it as `[UNREACHABLE: <error>]`, don't silently skip it.
- Process sources in batches — write intermediate results to the digest file as you go, rather than accumulating everything in memory.
- If the digest would exceed ~30 items, stop and note the remaining sources as "[DEFERRED — context limit]".
