# Research Ideation

Turn triaged research opportunities into concrete idea files for the TeaParty project.

## What To Do

1. **Find the latest analysis.** Read the most recent file in `intake/analysis/` (by date in filename). If an argument is provided, use that as the analysis path instead.

2. **Filter to "Explore" verdicts.** Only ideas marked as "Explore" in the triage get idea files. Skip "Watch" and "Skip" items.

3. **For each Explore idea, create an idea file** at `intake/ideas/<slug>.md` where `<slug>` is a kebab-case name derived from the idea (e.g., `bayesian-preference-proxy.md`). If the file already exists, update it rather than creating a duplicate.

4. **Each idea file should contain:**
   - **Origin** — Which source(s) inspired this, with URLs
   - **Problem** — What limitation or gap in TeaParty does this address?
   - **Proposal** — What specifically would be built or changed? Be concrete — name the files, modules, or systems that would be affected.
   - **How it works** — Technical sketch of the approach. Not a full design, but enough that someone could start a design doc from this.
   - **Evidence** — What from the source material suggests this would work? Cite specific results, benchmarks, or demonstrations.
   - **Risks** — What could go wrong? What assumptions need to hold?
   - **Effort estimate** — Small (< 1 day), Medium (1-3 days), Large (3+ days)
   - **Dependencies** — What else needs to exist or change first?

5. **Update the ideas index.** After writing all idea files, update or create `intake/ideas/INDEX.md` with a table listing all idea files, their status, and a one-line summary.

## Output Format for Each Idea File

```markdown
# <Idea Title>

**Status:** New | Under Review | Accepted | Rejected | Implemented
**Origin:** <source title> — <URL>
**Date:** <YYYY-MM-DD>
**Effort:** Small | Medium | Large

## Problem
<What gap or limitation does this address?>

## Proposal
<What would be built or changed?>

## How It Works
<Technical sketch>

## Evidence
<What suggests this would work?>

## Risks
- ...

## Dependencies
- ...
```

## Important

- Be concrete. "Improve the proxy" is not an idea. "Add BALD-based uncertainty sampling to the proxy's questioning strategy in `proxy_agent.py`" is an idea.
- Each idea should be independently actionable — someone should be able to pick up an idea file and start working without needing to read the full digest or analysis.
- Don't create idea files for things TeaParty already does. Check the codebase first.
