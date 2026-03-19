# Research Ideation

Turn triaged research opportunities into concrete idea statements for the TeaParty project.

## What To Do

1. **Find the latest analysis.** Read the most recent file in `intake/analysis/` (by date in filename). If an argument is provided, use that as the analysis path instead.

2. **Filter to "Explore" verdicts.** Only ideas marked as "Explore" in the triage get idea files. Skip "Watch" and "Skip" items.

3. **Read the source material.** For each Explore idea, go back to the original content file (the manifest in `intake/raw/<date>/manifest.json` has the paths). Do not write an idea file from the triage summary alone — you need the source.

4. **Read the relevant TeaParty code and design docs.** Use the priority area to find the right files:
   - **Human proxy agent** → `projects/POC/orchestrator/engine.py`, `projects/POC/orchestrator/actors.py`, `docs/detailed-design/act-r-proxy-memory.md`, `docs/detailed-design/act-r-proxy-sensorium.md`, `docs/human-proxies.md`
   - **Dispatch coordination** → `projects/POC/orchestrator/dispatch_cli.py`, `projects/POC/orchestrator/session.py`, `docs/hierarchical-teams.md`
   - **Learning system** → `projects/POC/orchestrator/learnings.py`, `docs/learning-system.md`
   - **CfA protocol** → `projects/POC/orchestrator/engine.py`, `docs/cfa-state-machine.md`
   - **Session resilience** → `projects/POC/orchestrator/session.py`

   You must understand the current behavior before you can describe how the idea changes it.

5. **For each Explore idea, create an idea file** at `intake/ideas/<slug>.md` where `<slug>` is a kebab-case name derived from the idea (e.g., `bayesian-preference-proxy.md`). If the file already exists, update it rather than creating a duplicate.

6. **Update the ideas index.** After writing all idea files, update or create `intake/ideas/INDEX.md` with a table listing all idea files, their status, and a one-line summary.

## What Goes in an Idea File

Each idea file is an **idea statement** — a self-contained argument for why a specific technique from the source material would improve a specific part of TeaParty, written concretely enough that someone could start a design doc from it.

```markdown
# <Idea Title>

**Status:** New | Under Review | Accepted | Rejected | Implemented
**Origin:** <source title> — <URL>
**Date:** <YYYY-MM-DD>
**Effort:** Small | Medium | Large

## The Idea

<2-3 paragraphs. What is the core insight from the source material? What specific
mechanism or technique does it introduce? Why does it matter for TeaParty specifically —
not "this is about learning and we do learning" but "this paper's X mechanism solves
the specific problem of Y in our Z component because...">

## Current Behavior

<Describe what TeaParty does today in the relevant area. Name the functions, the data
flow, the decision points. This section should be accurate to the code — you read it
in step 4. A reader should understand what exists before they read what would change.>

## Proposed Change

<Describe what would be different. Use pseudocode to show the new logic — not Python,
but clear enough that the shape of the change is obvious. The pseudocode should show
the decision flow, not implementation details.>

```
// Example pseudocode style:
on gate arrival:
    prior ← predict without artifact
    posterior ← predict with artifact
    if prior and posterior agree → habitual path (auto-approve)
    else → deliberative path (escalate with surprise context)
```

## Why This Would Work

<What evidence from the source material suggests this approach is sound? Cite specific
results, benchmarks, ablations, or demonstrations. "The paper shows good results" is
not evidence. "Their ablation on Table 3 shows the dual-system switch reduced
unnecessary escalations by 40% compared to a static threshold" is evidence.>

## Risks

- ...

## Dependencies

- ...
```

## Important

- **Read the code.** An idea file that doesn't reference actual functions or current behavior is too shallow to act on.
- **Use pseudocode, not Python.** The idea is conceptual. Pseudocode communicates the shape of the change without prematurely committing to an implementation.
- **The "Current Behavior" section is mandatory.** If you can't describe what TeaParty does today, you can't describe how the idea changes it.
- **Each idea should be independently actionable.** Someone should be able to pick up an idea file and start a design doc without reading the digest, analysis, or source paper.
- Don't create idea files for things TeaParty already does. The "Current Behavior" section should make it obvious whether the idea is novel.
