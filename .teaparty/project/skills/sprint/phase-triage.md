# Phase 2: Triage (the loop hub)

This phase is the routing hub. Every other phase returns here; from here you decide what to do next.

## What to do

1. Read `.teaparty/project/sprint/index.md` to see the full sprint at a glance.
2. Read the per-issue files (`.teaparty/project/sprint/issues/{N}.md`) for any issue whose tier or wave is blank, or whose situation has changed since you last looked.
3. Decide tier assignments **in conversation with the human originator**. Use `AskQuestion` when the intent of an issue is unclear, when two issues conflict, or when the priority is genuinely a human decision. Do not invent priorities silently.

The output of triage is one of four routing decisions, listed below.

## Routing

Pick exactly one branch.

- **You have one or more new tier decisions to commit to the board.**
  Go to `phase-prioritize.md` with the tier assignments you decided.

- **The cache is stale relative to GitHub** — for example, the human says new issues have been filed against the milestone, or that an issue has been closed externally, or you spot a row in `index.md` that does not match what the cache claims about it.
  Go to `phase-refresh.md`.

- **There is at least one Tier 1 issue with status `Approved` and no thread already open on it.**
  Go to `phase-dispatch.md`.

- **The sprint is over** — the milestone is closed, the human says the team is done, or every Tier 1 issue is `Done` / `Won't Do` and there are no pending Approved items waiting on you.
  Go to `phase-archive.md`.

If none of the above apply (you triaged, no new decisions, cache fresh, no Approved Tier 1 work, but the sprint is not over), stop and `AskQuestion` to the human: report what you observed and ask what they want next. Do not loop on yourself.

---

**Next:** Read the file named in the branch you picked.
