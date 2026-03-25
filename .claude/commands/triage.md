# Demo Triage

Review all open GitHub issues against the project documentation and codebase to identify what matters most for the Monday demo.

## What To Do

1. **Fetch all open GitHub issues** using `gh issue list --state open --limit 100` and read the details of each issue.

2. **Read the docs folder** — read everything under `docs/` (and nowhere else) to understand the project's claims, architecture, and design intent. Pay special attention to:
   - `docs/overview.md` — the master conceptual model
   - `docs/detailed-design/` — implementation status and gap analysis
   - `docs/experimental-results/` — what we claim to have demonstrated

3. **Review the codebase** — scan the source code to understand what is actually implemented vs. what the docs describe. Look for:
   - Features that are stubbed or incomplete
   - Broken or missing functionality
   - Test coverage gaps for claimed features

4. **Cross-reference issues against demo readiness** — for each open issue, assess:
   - Does this block a live demonstration of the system?
   - Does this undermine or contradict a claim made in the docs?
   - Is this cosmetic/deferrable or does it erode credibility?

## Output Format

Produce a prioritized list in two tiers:

### Tier 1: Demo Blockers
Issues or gaps that would prevent a successful live demonstration on Monday. These must be resolved before the demo.

```
## Blocker N: <name>
**Issue:** #<number> (or "undiscovered" if no issue exists)
**What breaks:** Specific demo scenario that fails.
**Claim at risk:** Which doc/claim this undermines.
**Fix scope:** Rough estimate of what needs to change.
```

### Tier 2: Credibility Risks
Issues or gaps that wouldn't crash the demo but would undermine the validity of claims if noticed or probed.

```
## Risk N: <name>
**Issue:** #<number> (or "undiscovered" if no issue exists)
**Claim at risk:** Which doc/claim this weakens.
**Visibility:** How likely is this to surface during a demo?
**Fix scope:** Rough estimate of what needs to change.
```

### Recommended Demo-Day Plan
A short bullet list of the order in which Tier 1 items should be tackled, plus any Tier 2 items worth squeezing in.
