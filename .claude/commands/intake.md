# Research Intake Pipeline

Run the full research intake pipeline with parallel digest agents, then triage and ideate.

## Architecture

```
        ┌─── Agent 1: /digest-rss ──────→ .partial-rss-<date>.md
        │
intake ─┼─── Agent 2: /digest-youtube ──→ .partial-youtube-<date>.md
        │
        └─── Agent 3: /digest-web ──────→ .partial-web-<date>.md
                                                    │
                              merge ←───────────────┘
                                │
                    digest-<date>.md
                                │
                      /research-triage
                                │
                    analysis-<date>.md
                                │
                          /ideate
                                │
                      intake/ideas/*.md
```

## Step 1: Parallel Digest (fan-out)

Launch three agents in parallel. Each writes a partial digest file:

1. **RSS Agent** — runs `/digest-rss`. Fetches 7 RSS feeds (LangChain, Latent Space, Interconnects, Import AI, One Useful Thing, Simon Willison, Ahead of AI, arXiv cs.AI). Writes `intake/digests/.partial-rss-<date>.md`.

2. **YouTube Agent** — runs `/digest-youtube`. Fetches 4 YouTube channels (David Shapiro, AI Explained, Karpathy, Dwarkesh). Writes `intake/digests/.partial-youtube-<date>.md`.

3. **Web Agent** — runs `/digest-web`. Fetches 6 web sources (Anthropic, OpenAI, Lilian Weng, BAIR, Ai2, HF Papers). Writes `intake/digests/.partial-web-<date>.md`.

Launch all three using the Agent tool with `run_in_background: true`. Wait for all to complete.

## Step 2: Merge Digest

After all three agents complete:

1. Read the three partial files from `intake/digests/`
2. Check for `<!-- NO NEW CONTENT -->` markers — skip empty partials
3. If ALL three are empty, report "No new content today" and stop
4. Merge non-empty partials into `intake/digests/digest-<YYYY-MM-DD>.md`:
   ```markdown
   # Research Digest — <YYYY-MM-DD>

   New items found: <total count>
   Sources checked: 18

   ---

   <merged entries, renumbered sequentially>
   ```
5. Parse the `<!-- PROCESSED -->` blocks from each partial and update state:
   ```python
   from intake.state import load_state, mark_seen, save_state
   from datetime import date
   state = load_state()
   # ... mark each processed item ...
   state['last_run'] = date.today().isoformat()
   save_state(state)
   ```
6. Delete the `.partial-*` files

## Step 3: Triage

Read the merged digest. Read `intake/priorities.md` for current project focus areas. Evaluate each idea for relevance and impact to TeaParty. Write the analysis to `intake/analysis/analysis-<YYYY-MM-DD>.md`. Follow the instructions in `/research-triage`.

## Step 4: Ideate

Read the analysis. For each "Explore" verdict, create a concrete idea file in `intake/ideas/`. Follow the instructions in `/ideate`.

## Step 5: Notify

Send a summary to Apple Reminders so it syncs to all devices (iPhone, iPad, Mac):

```bash
osascript -e 'tell application "Reminders"
    set myList to list "Reminders"
    tell myList
        make new reminder with properties {name:"<TITLE>", body:"<BODY>"}
    end tell
end tell'
```

**Title format:** `Research Intake: <N> new items, <E> to explore`

**Body format:**
```
<N> new items from <S> sources
Triage: <E> Explore, <W> Watch, <K> Skip
<list of Explore ideas, one per line>

Full digest: intake/digests/digest-<date>.md
```

If no new content was found, use:
- Title: `Research Intake: No new content today`
- Body: `18 sources checked, nothing new.`

## Summary

After all steps, also print the same summary to the conversation:
- How many sources were checked, how many had new content
- How many ideas were triaged (Explore / Watch / Skip breakdown)
- How many idea files were created or updated
- List the idea files with their one-line summaries
