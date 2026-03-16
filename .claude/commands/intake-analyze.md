# Intake Analyze

Analyze pre-fetched research content and produce digest, triage, and idea files.

**This skill reads only local files.** All network fetching was done by `intake/fetch.py` before this skill runs. No Bash, WebFetch, or osascript needed.

## What To Do

### Step 1: Read the manifest

The argument to this skill is the path to a `manifest.json` file. Read it — it contains a list of items with:
- `source` — source name
- `title` — article/video title
- `url` — original URL
- `published` — publication date
- `file` — path to the pre-fetched content file on disk
- `type` — article, paper, video, web
- `updated` — true if this is an update to previously-seen content
- `unreachable` — true if the fetch failed

### Step 2: Produce the digest

For each item in the manifest (skip `unreachable` items):
1. Read the content file at the `file` path
2. Extract: key ideas, techniques & methods, results & evidence, notable quotes, relevance signal
3. For `updated` items, prefix the title with `[UPDATED]` and focus on what changed
4. For arXiv papers, the content is the abstract — that's enough

Write the digest to `intake/digests/digest-<YYYY-MM-DD>.md` using today's date:

```markdown
# Research Digest — <YYYY-MM-DD>

New items found: <count>
Sources checked: 18

---

## 1. <Title>
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

### Step 3: Triage

Read `intake/priorities.md` for current research priorities. Evaluate each digest item:
- **Relevance** (High/Medium/Low) — tied to a specific priority
- **Impact** (High/Medium/Low) — what it would change in TeaParty
- **Verdict** — Explore / Watch / Skip

Write to `intake/analysis/analysis-<YYYY-MM-DD>.md` with a summary matrix.

Be ruthless. Items about GPU economics, math puzzles, enterprise partnerships, general AI trajectory, image generation, robotics — Skip. Only items directly addressing agent coordination, human-agent collaboration, preference learning, multi-agent protocols, or agent evaluation get Explore.

### Step 4: Ideate

For each "Explore" verdict, create an idea file in `intake/ideas/<slug>.md`:
- Status: New
- Origin, Date, Effort estimate
- Problem, Proposal, How It Works, Evidence, Risks, Dependencies

Update `intake/ideas/INDEX.md` with all idea files.

## Important

- You have NO network access. All content is in local files listed in the manifest.
- If a content file starts with `[UNREACHABLE:` or `[FETCH ERROR:`, note it and move on.
- Write all outputs before finishing — the caller depends on the files existing.
