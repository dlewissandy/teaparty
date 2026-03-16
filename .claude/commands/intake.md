# Research Intake Pipeline

Run the full research intake pipeline: digest sources, triage ideas, then generate idea files.

## What To Do

Run these three skills in sequence. Each step produces output that feeds the next.

### Step 1: Digest
Run `/digest` — reads `intake/sources.md`, fetches/watches each source, writes a detailed summary to `intake/digests/digest-<date>.md`.

### Step 2: Triage
Run `/research-triage` — evaluates each idea from the digest for relevance and impact to TeaParty, writes `intake/analysis/analysis-<date>.md`.

### Step 3: Ideate
Run `/ideate` — creates individual idea files in `intake/ideas/` for opportunities marked "Explore" in the triage.

## After All Steps

Summarize what was produced:
- How many sources were digested
- How many ideas were triaged (and the Explore/Watch/Skip breakdown)
- How many idea files were created or updated
- List the idea files with their one-line summaries
