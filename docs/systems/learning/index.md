# Learning & Memory

TeaParty's learning system is hierarchical memory across three kinds of knowledge — episodic (session memories), procedural (skills and patterns), and research (ingested literature). It is designed retrieval-first, not storage-first: the hard problem is not writing things down, it is getting the right knowledge to the right agent at the right moment, at the right level of the hierarchy.

## Why it exists

Hierarchical teams bound each agent's context by role. That scoping carries the durability of agent coordination — but it also means a scoped agent cannot see the organizational knowledge it needs to stay aligned with values, conventions, and prior lessons. Without a memory system, scoped agents drift. With the wrong kind of memory system, they drown.

The wrong kind is flat, undifferentiated prose, retrieved indiscriminately. We observed both failure modes directly in the POC:

- **Context rot.** When all learning is injected regardless of relevance, signal-to-noise collapses as the store grows. Claude Code's native MEMORY.md caps injection at 200 lines precisely because indiscriminate loading becomes counterproductive.
- **No validation loop.** A learning written once and never tested has the same standing as one confirmed fifty times. Wrong conclusions from single sessions persist and mislead.

The deeper framing: memory is a retrieval problem, not a storage problem. And retrieval must differentiate by purpose. An organization's values, a team's task-specific procedures, and a human's decision patterns are three different kinds of knowledge that should never compete for the same injection budget. See [ACT-R](../../research/act-r.md) for the cognitive architecture this differentiation draws from, and [self-compacting memory](../../research/self-compacting-memory.md) for the retrieval-centric framing.

## How it works

**Three memory types.** Institutional learnings (values, norms, conventions) are prose and always loaded at matching scope. Task-based learnings are YAML-frontmattered markdown files fuzzy-retrieved against the current task. Proxy learnings capture the human's preferences and decision patterns. Each type has its own storage format, its own retrieval strategy, and its own budget.

**Promotion chain through gates.** Learnings are written at the most specific scope where they apply, and validated ones flow upward: team → session → project → global. Each gate filters more aggressively — session-to-project requires a pattern seen in three or more distinct sessions; project-to-global requires project-agnostic applicability evaluated by an LLM judge. Proxy learnings never promote — they describe a specific human.

**Temporal decay and retirement.** Prominence combines importance, reinforcement count, and a 90-day exponential half-life with a 10% decay floor. Old entries fade but never become invisible. Entries that survive reinforcement and avoid contradiction accumulate weight; stale or disproven ones are retired.

**Four learning moments.** The design defines four moments where signal is captured: prospective (before execution), in-flight (at milestones), corrective (at mismatch), and retrospective (after completion). Corrective and retrospective extraction are operational today — corrective captures gate mismatches, retrospective runs a post-session LLM pass and produces the richest entries. Prospective and in-flight extraction are designed but not yet implemented (see Status below). The corrective and retrospective signal feeds the promotion chain.

**Continuous skill refinement.** Beyond text learnings, the system crystallizes successful plans into reusable skills — parameterized workflows with fixed structure and variable parameters. When execution under a skill hits friction (permission denials, fallback retries, gate corrections), the refinement pipeline traces the failure back to the skill itself and patches its structure.

**Bidirectional proxy coupling.** Learning and the [human proxy](../human-proxy/index.md) co-evolve. Proxy corrections at gates emit entries to `proxy-tasks/`, which flow back to agents through normal task retrieval. Agent learnings reach the proxy through its own retrieval calls. The proxy's intake dialog — where it predicts the human's answers and compares them to reality — is one of the richest learning signals in the system; every prediction-vs-actual delta is direct evidence of where the proxy's model is wrong.

## Status

Operational:

- Promotion chain with recurrence detection, proxy exclusion, project-agnostic filtering
- Continuous skill refinement: friction detection, LLM-driven skill updates, per-skill quality monitoring
- Skill crystallization: candidate clustering, category-scoped generalization, lookup-time matching
- Temporal decay: 90-day half-life, 10% decay floor, reinforcement resets the clock
- Type-aware retrieval with per-type budget allocation
- Bidirectional proxy feedback via `proxy-tasks/`
- Contradiction detection for proxy memory and for task/institutional learnings

Designed, not yet implemented:

- In-flight extraction (assumption checkpoints at milestones during execution)
- Prospective extraction (reflection on retrieved learnings before execution)

See the [learnings case study](../../case-study/learnings.md) for how these mechanisms played out across real dispatches.

## Deeper topics

- [Episodic memory](episodic.md) — session extraction, storage hierarchy, FTS5 index, hybrid retrieval, reinforcement, decay
- [Procedural memory](procedural.md) — skill crystallization, continuous refinement, quality monitoring
- [Promotion chain](promotion-chain.md) — session-to-project-to-global gates, proxy exclusion, project-agnostic filtering
- [Research pipeline](research-pipeline.md) — PDF extraction, arXiv and Semantic Scholar ingestion, paper indexing
