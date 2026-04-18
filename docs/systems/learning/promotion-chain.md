# Promotion Chain

Learnings are written at the most specific scope where they apply. The promotion chain moves validated learnings upward — team → session → project → global — with increasingly aggressive filtering at each level. The point is to prevent scope pollution: a correction that applied to one specific task shouldn't automatically become global policy.

Implemented in `teaparty/learning/promotion.py`.

## What promotes, and what doesn't

Promotion moves learnings upward **within type** — institutional never becomes task-based, proxy never becomes institutional:

```
Team institutional.md  ──promotes──>  Project institutional.md  ──promotes──>  Global institutional.md
Team tasks/            ──promotes──>  Project tasks/            ──promotes──>  Global tasks/
```

**Proxy learnings do not promote.** They describe a specific human. `is_proxy_learning()` filters proxy-sourced paths (`proxy.md`, `proxy-tasks/`) before any promotion clustering runs.

## The three gates

`promotion.py` implements three gates evaluated at session close, after rollup scopes extract their entries and before reinforcement tracking updates counts.

### Session → Project

`find_recurring_learnings()` walks `.sessions/*/tasks/` across all sessions for the project, clusters entries by similarity (pluggable: embedding-based with exact-match fallback), and promotes entries that recur in **3 or more distinct sessions**.

Three is the threshold where a pattern has survived enough independent evidence to be worth carrying forward. Entries already promoted are detected via similarity against `project/tasks/` and skipped — the chain is idempotent.

### Proxy exclusion

`is_proxy_learning()` filters any entry sourced from proxy paths before clustering runs. A human's preferences shouldn't leak into the project's institutional record, regardless of how often they recur.

### Project → Global

`filter_project_agnostic()` evaluates entries via a pluggable judge function — typically an LLM asked whether the learning generalizes beyond the current project. The default is conservative: **nothing promotes on judge failure**. Silent fallback to "promote by default" is exactly the failure mode the promotion chain exists to prevent.

Infrastructure-ready but not yet triggered automatically — project-to-global promotion runs manually for now while the judge prompt is tuned.

## Provenance

`MemoryEntry` carries optional `promoted_from` and `promoted_at` fields (empty-string defaults) so every promoted learning records where it came from. This matters for two reasons:

1. **Retraction.** If a project-level learning is later disproven, entries promoted from it can be traced and reviewed.
2. **Attribution.** Credit assignment — which session produced a learning that graduated to global — is a signal we want to preserve for the [case study](../../case-study/learnings.md) and for debugging.

## Extraction scopes

After each completed session, the system orchestrates extraction across multiple scopes before promotion runs:

- **Streams** — observations, escalation, intent-alignment
- **Rollups** — team, session, project, global
- **Temporal** — prospective, in-flight, corrective

Each scope extracts structured entries with YAML frontmatter, filtering for patterns durable enough to warrant promotion. The `promote()` function in `teaparty/learning/episodic/summarize.py` implements all rollup and temporal scopes, and `teaparty/learning/extract.py::_call_promote` orchestrates the scope-by-scope walk for each session. Post-write compaction runs for session, project, and global scopes via `_try_compact()`.

All rollup scopes (team, session, project, global) and temporal scopes (prospective, in-flight, corrective) are implemented end-to-end. The reflection points that feed prospective and in-flight were added as CfA phase-transition hooks in `engine.py` (`write_premortem` at intent→planning, `write_assumption_checkpoint` at phase milestones). Signal quality currently varies across the temporal scopes — retrospective is richest, prospective mostly mirrors the approved PLAN, in-flight assumptions are heuristically inferred. The milestone-4 calibration-stack rewrite will revisit signal quality across the four moments.
