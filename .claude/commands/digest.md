# Research Digest

Read curated sources and produce a detailed summary document.

## What To Do

1. **Read the source list** from `intake/sources.md`. Each entry has a URL and description.

2. **Fetch and consume each source.** Use the appropriate tool for each source type:
   - **Articles, papers, blog posts:** Use `WebFetch` to read the content.
   - **YouTube channels:** Use the `intake.youtube` module to get recent videos and transcripts. Run:
     ```python
     from intake.youtube import digest_channel
     results = digest_channel("https://www.youtube.com/@ChannelHandle", max_videos=3)
     for v in results:
         print(f"Title: {v.title}")
         print(f"Published: {v.published}")
         print(f"URL: {v.url}")
         print(f"Transcript: {v.transcript[:500]}")
     ```
     **Videos are first-class sources — do not skip them.** The transcript contains the full spoken content.
   - **PDFs:** Use `WebFetch` to download, or `Read` if already local.

3. **For each source, extract:**
   - **Key ideas** — the 2-5 most important concepts, findings, or proposals
   - **Techniques and methods** — any novel approaches, architectures, or algorithms
   - **Results and evidence** — what was demonstrated, measured, or claimed
   - **Quotes** — 1-3 verbatim quotes that capture the essence (with attribution)
   - **Relevance signal** — a one-sentence note on why this might matter for agent coordination, human-agent collaboration, or learning systems

4. **Write the digest** to `intake/digests/digest-<YYYY-MM-DD>.md` using today's date.

## Output Format

```markdown
# Research Digest — <YYYY-MM-DD>

Sources consumed: <count>

---

## 1. <Source title>
**URL:** <url>
**Type:** article | paper | video | podcast

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

## 2. <next source>
...
```

## Important

- **Do not skip videos.** Use `intake.youtube.digest_channel()` to fetch transcripts. Video sources often contain the most valuable insights because they include live demonstrations and informal reasoning that doesn't make it into papers.
- Be detailed. The triage and ideation skills downstream depend on the richness of this digest.
- If a source is unreachable, note it as `[UNREACHABLE]` with the error, don't silently skip it.
- For YouTube channels, fetch the 3 most recent videos per channel. If running daily, use the `since` parameter with yesterday's date to avoid re-digesting old videos.
