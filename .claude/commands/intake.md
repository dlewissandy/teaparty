# Research Intake Pipeline

Run the full research intake pipeline: pre-fetch sources, analyze with parallel agents, then notify.

## Architecture

```
  Python pre-fetch (intake/fetch.py)
            │
            ▼
      manifest.json + raw files
            │
        ┌───┼───┐
        ▼   ▼   ▼
      Agent Agent Agent    (parallel analysis)
      RSS   YT    Web
        │   │   │
        ▼   ▼   ▼
      .partial-rss  .partial-youtube  .partial-web
            │
            ▼
         merge → digest-<date>.md
            │
            ▼
      /research-triage → analysis-<date>.md
            │
            ▼
         /ideate → intake/ideas/*.md
            │
            ▼
  Python notify (intake/notify.py)
```

## Step 1: Pre-fetch

Run the Python pre-fetcher to download all source content to local files. This handles all network I/O outside Claude Code — no WebFetch or Bash permissions needed for agents.

```bash
uv run python -m intake.fetch
```

The manifest is at `intake/raw/<YYYY-MM-DD>/manifest.json`. Read it to get the list of fetched items and their local file paths.

If the manifest has 0 non-unreachable items, skip to Step 5 with a "no new content" notification.

## Step 2: Parallel Analysis (fan-out)

Read the manifest and partition items by type:
- **RSS items**: `type` is `article` or `paper`
- **YouTube items**: `type` is `video`
- **Web items**: `type` is `web`

Launch three agents in parallel. Each reads its assigned items from the manifest, reads the local content files, and writes a partial digest:

1. **RSS Agent** — reads RSS items from manifest, reads each content file, extracts key ideas/techniques/evidence/quotes/relevance. Writes `intake/digests/.partial-rss-<date>.md`.

2. **YouTube Agent** — reads YouTube items, reads each transcript file, extracts key ideas/techniques/evidence/quotes/relevance. Writes `intake/digests/.partial-youtube-<date>.md`.

3. **Web Agent** — reads Web items, reads each content file, extracts key ideas/techniques/evidence/quotes/relevance. For HF Papers HTML, focus on agent-related papers. Writes `intake/digests/.partial-web-<date>.md`.

Each agent should:
- Skip items with `unreachable: true` or content starting with `[UNREACHABLE:` or `[FETCH ERROR:`
- For arXiv RSS items, the content is the abstract — focus on papers about agents, multi-agent systems, coordination, RLHF, preference learning. Skip unrelated papers.
- Mark `updated` items with `[UPDATED]` prefix
- Use the digest entry format:
  ```markdown
  ## <N>. <Title>
  **Source:** <source name>
  **URL:** <url>
  **Type:** <type>
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

**All content is in local files.** Agents must NOT use WebFetch — everything they need is on disk.

## Step 3: Merge Digest

After all three agents complete:

1. Read the three partial files
2. Skip any containing only `<!-- NO NEW CONTENT -->`
3. If ALL are empty, skip to Step 6 with "no new content"
4. Merge into `intake/digests/digest-<YYYY-MM-DD>.md`, renumbering entries sequentially
5. Delete the `.partial-*` files

## Step 4: Triage

Read `intake/priorities.md` for current research priorities. Read the merged digest. Evaluate each idea:
- **Relevance** (High/Medium/Low) — tied to a specific priority
- **Impact** (High/Medium/Low)
- **Verdict** — Explore / Watch / Skip

Write to `intake/analysis/analysis-<YYYY-MM-DD>.md`. Follow `/research-triage`.

Be ruthless — GPU economics, math puzzles, enterprise partnerships, general commentary, image generation, robotics: Skip.

## Step 5: Ideate

For each "Explore" verdict, create an idea file in `intake/ideas/<slug>.md`. Follow `/ideate`.

## Step 6: Create GitHub Issues for Explore Items

Run the issue creation script. This handles everything: dedup against existing issues, creating with proper labels, adding to the project backlog with Status=Backlog and Source=research-intake, and updating idea files with issue numbers.

```bash
uv run python -m intake.create_issues intake/analysis/analysis-<YYYY-MM-DD>.md
```

The script:
- Checks all open issues for duplicates (fuzzy title matching, 60% word overlap threshold)
- Skips items that already have a similar open issue
- Creates issues with the `intake` label and a well-formed intent (Scope, Value, Source)
- Adds each issue to the TeaParty GitHub project (#2) with Status=Backlog, Source=research-intake
- Updates the corresponding idea file's Status line with the issue number

## Step 7: Update State and Notify

Update the state file so the next run skips these items:
```bash
uv run python -c "
from intake.state import load_state, mark_seen, save_state
from datetime import date
import json
state = load_state()
manifest = json.load(open('intake/raw/$(date +%Y-%m-%d)/manifest.json'))
for item in manifest['items']:
    if item.get('unreachable'): continue
    content_id = item.get('video_id', item['url'])
    mark_seen(state, item['source_url'], content_id,
              date=item.get('published', ''),
              content_hash=item.get('content_hash', ''))
state['last_run'] = date.today().isoformat()
save_state(state)
"
```

Send notification — include the issue numbers in the body:
```bash
uv run python -m intake.notify intake/analysis/analysis-<YYYY-MM-DD>.md
```

If no new content, use `uv run python -m intake.notify --no-new`.

## Summary

Print to conversation:
- Sources checked, new content found
- Triage breakdown (Explore / Watch / Skip)
- Idea files created with one-line summaries
- GitHub issues created (with numbers and links)
