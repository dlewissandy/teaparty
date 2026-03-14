# Hierarchical Memory and Learning

The learning system is TeaParty's second pillar: where hierarchical teams enforce context boundaries, the learning system bridges them — getting the right organizational knowledge to the right agent at the right moment, so scoped agents don't drift from the values and conventions they can no longer see.

## The Problem

Agent memory systems that treat all learning as undifferentiated prose in flat files face two structural failures observed directly in our work:

**Indiscriminate retrieval.** All stored knowledge is injected regardless of relevance. As the store grows, signal-to-noise drops — useful learnings are buried in irrelevant ones. Claude Code's native MEMORY.md has a 200-line injection limit precisely because indiscriminate loading becomes counterproductive. The POC hit this limit within the first few sessions; learnings accumulated faster than they could be curated.

**No validation loop.** A learning written once and never tested has the same standing as one confirmed fifty times. The POC's early learning files contained entries that were wrong — conclusions drawn from a single session that did not generalize. Without reinforcement, decay, or contradiction detection, these persisted and actively misled subsequent sessions.

The deeper problem: flat memory treats learning as a storage problem when it is actually a retrieval problem. Storing things is easy. Getting the right thing at the right moment — that is the hard part.

Learning also requires differentiation by purpose. Not all knowledge serves the same function:

- **Institutional learning** — the organization's values, norms, conventions, and working agreements.
- **Task learning** — procedural knowledge about how to perform specific types of work effectively.
- **Proxy learning** — the human's preferences, risk tolerance, and decision patterns, so the system can act as an accurate stand-in.

## Three Learning Types

### Institutional Learning

How organizations and workgroups get better at working together. Institutional learnings change slowly, are broadly applicable within scope, and are curated rather than automatically generated. In the POC, institutional learnings are stored in `institutional.md` at each scope level and always loaded into agent context — the same injection pattern as CLAUDE.md.

Examples from the POC's actual `institutional.md`:
- Dispatch coordination norms (how the uber team sequences work across liaisons)
- Code review conventions (reviewer runs tests first, then reads diff)
- Cross-team communication protocols (liaisons relay, never bypass)

### Task-Based Learning

How teams get better at specific types of tasks. Task learnings change with each outcome, are narrowly relevant to matching task types, and have fuzzy boundaries — a "database migration" learning may apply to schema redesigns, ORM changes, and data backfills. In the POC, task learnings are stored as individual YAML-frontmattered markdown files in `tasks/` directories at each scope level.

The POC currently has 36+ task learning files, structured as:
- Rules: "Always backup before migrating a database"
- Procedures: "For API endpoints: schema, route, tests, docs"
- Skills: executable workflows that emerged from successful plans (see [strategic planning — warm start](strategic-planning.md#warm-start-accumulated-skills))
- Causal abstractions: "When X, doing Y leads to Z"

### Proxy Learning

How the system learns to stand in for the human — not just at approval gates, but in the ongoing dialog between the human and agent teams. Proxy learning is further subdivided:

**Preferential** — the human's general traits: communication style, risk tolerance, values, delegation boundaries. Stable, broadly applicable, always loaded.

**Behavioral** — how the human interacts with the team during work, not just at decision points. When the human questions a team's approach, redirects a line of investigation, asks for more detail on a specific aspect, or pushes back on an assumption, each interaction reveals something about what the human pays attention to and how they think about the work. These patterns are as valuable as gate decisions — an approval tells the system "this was acceptable," but a question during planning tells the system "this is what I scrutinize."

**Task-based** — domain-specific decision patterns: when to consult vs act, triage heuristics, delegation scope by area. Context-specific, retrieved on demand.

Proxy learning is stored in the same file-based format as other learning types: `proxy.md` for preferential (always loaded) and `proxy-tasks/` for task-based (fuzzy-retrieved). The confidence model tracks approval rates, correction history, conversation patterns, and question patterns per CfA state — capturing not just what the human decided but how they reasoned about it, so that behavioral patterns can inform future proxy decisions alongside gate outcomes. See [human-proxies.md](human-proxies.md) for the full proxy model.

### Procedural Learning

The other three learning types capture knowledge as text — facts, norms, preferences. Procedural learning captures knowledge as executable structure. It operates through two mechanisms:

**Skill crystallization.** When multiple plans for the same category of work converge on the same decomposition, the system generalizes the pattern into a Claude Code skill — a parameterized workflow with fixed structure (sequencing, gates, fan-out/fan-in) and variable parameters (topic, audience, depth). This is how cold-start plans become warm-start templates. A single successful plan is an anecdote. Three successful plans with the same shape are a candidate skill. The [strategic planning](strategic-planning.md#warm-start-accumulated-skills) document describes how these skills seed future planning conversations.

**Skill refinement.** When execution under a skill fails at a specific point — a contingency the skill didn't anticipate, a gate that consistently triggers escalation, a decomposition step that produces work requiring rework — the corrective learning targets the skill itself, not just the session. The failure is traced back to the skill's structure: which step produced the failure, what the skill assumed that turned out to be wrong, and what structural change would prevent recurrence. The refined skill replaces the original, carrying forward the correction.

Procedural learning is what closes the loop between planning and execution across sessions. Without it, each session's plan is informed by declarative learnings ("this approach didn't work last time") but not by structural corrections to the workflow itself. With it, the organization's skills evolve: failure points are patched, unnecessary steps are pruned, missing gates are added — not by a human editing a template, but by the system observing where its own plans break and repairing them.

## Scope and Type

Every learning has two coordinates: what scope it belongs to (where in the hierarchy) and what type it is.

```
                 Institutional               Task-Based
                 ────────────────            ────────────────────

Global           Cross-project norms         Cross-project task patterns

Project          Project conventions          Project task patterns

Team             Team norms                   Team task learnings

Human (proxy)    Human preferences            Human task patterns
```

The vertical axis (scope) is handled by the promotion chain — the mechanism that promotes durable learnings upward through team → session → project → global, filtering more aggressively at each level.

The horizontal axis (type) determines storage and retrieval:

| Type | Storage | Retrieval |
|------|---------|-----------|
| Institutional | Prose markdown file | Always loaded at matching scope |
| Task-based | Chunked markdown files (YAML frontmatter) | Fuzzy query against current task context |
| Proxy preferential | Prose file (`proxy.md`) | Always loaded when proxy is active |
| Proxy task-based | Chunked files (`proxy-tasks/`) | Fuzzy query against current decision context |

## Learning Moments

Four moments trigger learning writes, each capturing a different kind of signal:

| Moment | When | Signal |
|--------|------|--------|
| **Prospective** | Before execution | Retrieval of relevant prior learnings; useful retrievals get confidence boost |
| **In-flight** | At milestones | Assumption checkpoints; disconfirmed assumptions amplify corrective signal |
| **Corrective** | At mismatch | Highest confidence — direct evidence of model error with recoverable causal chain |
| **Retrospective** | After completion | Synthesized learnings promoted through the chain |

Corrective learnings are the most valuable because they come with causal chains: what went wrong, why, and what would have prevented it. Corrective learnings receive higher importance weight (0.8) than single-observation learnings (0.5) to reflect this.

## Promotion Chain

The promotion chain moves learnings upward within type — institutional never becomes task-based, proxy never becomes institutional:

```
Team institutional.md  ──promotes──>  Project institutional.md  ──promotes──>  Global institutional.md
Team tasks/            ──promotes──>  Project tasks/            ──promotes──>  Global tasks/
```

Each step filters more aggressively: team → project requires patterns that held across multiple sessions; project → global requires project-agnostic patterns. Proxy learnings do not promote upward (they describe a specific human).

After each completed session, the system orchestrates extraction across multiple scopes: streams (observations, escalation, intent-alignment), rollups (team, session, project, global), and temporal (prospective, in-flight, corrective). Each scope extracts structured entries with YAML frontmatter, filtering for the patterns that are durable enough to warrant promotion.

## Retrieval Architecture

The retrieval architecture is inspired by [OpenClaw](https://github.com/openclaw/openclaw) (Steinberger et al., 2025-2026), the open-source Claude agent that pioneered file-first agentic memory with hybrid retrieval. OpenClaw's core design — Markdown as source of truth, SQLite as derived index, hybrid BM25 + vector search (70% vector / 30% keyword) — provides the retrieval foundation.

TeaParty adapts this architecture in three ways:
1. **Learning type differentiation** replaces OpenClaw's undifferentiated memory files — institutional learnings are always loaded, task-based learnings are fuzzy-retrieved, and the two never compete for the same budget.
2. **Hierarchical scope with promotion** replaces OpenClaw's flat per-agent model — a team-level chunk should score higher than a global chunk at equal similarity, because it was generated closer to the current context.
3. **Four learning moments** replace OpenClaw's single write-on-compaction trigger — learnings are captured at the points where signal is strongest, not just when the context window is about to overflow.

The fuzzy retrieval layer will use memsearch, the OpenClaw memory module extracted by Zilliz as a standalone library, providing chunking, embedding, indexing, and hybrid score fusion. See `projects/agentic-memory/` for the detailed research on OpenClaw's architecture and how it was adapted.

## Relationship to Other Pillars

**[Intent engineering](intent-engineering.md)** is the first consumer of proxy learnings. Warm-start pre-population draws from the proxy model. Corrections to pre-populated intent are high-value write signals.

**[Strategic planning](strategic-planning.md)** is the second consumer. Task-based learnings inform decomposition; institutional learnings inform coordination. Plans that succeed graduate into reusable skills — the highest-value form of procedural learning.

**[Hierarchical teams](hierarchical-teams.md)** create the scoping problem that learning solves. Each team's context is bounded by its role, but the organization's values and conventions must still reach every agent. Learning bridges this gap through scoped retrieval.

**[Human proxies](human-proxies.md)** are the primary consumer of proxy learning. The proxy's escalation model is one of the highest-value things the memory system stores.

## Open Questions

**Retrieval budget.** How to inject fuzzy-retrieved task learnings into agent context without exceeding token budgets or diluting signal. OpenClaw's approach (top-N chunks by hybrid score) is the starting point, but scope weighting (team-level chunks scoring higher than global) needs empirical tuning.

**Confidence and decay.** The design calls for FadeMem-style temporal decay — learnings that are reinforced persist, learnings that are contradicted or unused fade. The right decay rate is unknown: too aggressive and hard-won learnings disappear, too conservative and the store fills with stale observations.

**In-flight learning.** Capturing assumption checkpoints at milestones during execution requires integration into the execution phase — identifying what assumptions the plan rests on and verifying them as work proceeds.
