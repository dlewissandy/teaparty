# Learning System Design

The learning system is TeaParty's second pillar: where hierarchical teams enforce context boundaries, the learning system bridges them — getting the right organizational knowledge to the right agent at the right moment, so scoped agents don't drift from the values and conventions they can no longer see.

> This document describes the full platform design for TeaParty's learning system. The 10-scope taxonomy, three learning types, and promotion chain described here are the target design for `teaparty_app/`. The POC (`projects/POC/`) implements a working subset — see [poc-architecture.md](poc-architecture.md) for what is currently running. Research foundations are in [cognitive-architecture.md](cognitive-architecture.md).

---

## 1. The Problem

Agent memory systems that treat all learning as undifferentiated prose in flat files face three structural failures:

**No retrieval discrimination.** All stored knowledge is injected regardless of relevance. As the store grows, signal-to-noise drops — useful learnings are buried in irrelevant ones. Without embedding, scoring, or context matching, retrieval is indiscriminate.

**Declarative-procedural gap.** "Always review code before running tests" as a sentence in a file is a fact the agent knows, not a rule the agent follows. There is a fundamental gap between declarative knowledge (knowing that) and procedural knowledge (knowing how). Flat memory stores everything as the former and hopes it activates the latter.

**No validation loop.** A learning written once and never tested has the same standing as one confirmed fifty times. There is no reinforcement, no decay, no contradiction detection. Stale or wrong memories persist and actively mislead.

The deeper problem: flat memory treats learning as **storage** when it is actually a **retrieval** problem. Storing things is easy. Getting the right thing at the right moment and having it actually influence behavior — that is the hard part.

More fundamentally, learning requires differentiation by purpose. Not all knowledge serves the same function:

- **Organizational learning** — learn the organization's values. Institutional norms, conventions, and working agreements that govern all work within scope.
- **Task learning** — learn the most effective way to perform tasks. Procedural knowledge — rules, procedures, skills, and causal abstractions — that improves with each task outcome.
- **Proxy learning** — solve the autonomy/oversight dilemma. Learn the human's preferences, risk tolerance, and decision patterns so the system can act as an accurate stand-in.

---

## 2. Three Learning Types

Learnings are not undifferentiated prose. They differ in purpose, scope, storage format, retrieval mechanism, and rate of change. The system distinguishes three types:

### 2.1 Institutional Learning

How organizations and workgroups get better at working together and performing tasks over time.

**Examples:**
- "Our code review process: reviewer runs tests first, then reads diff, then comments on style"
- "When Design delivers mockups, Engineering prototypes within 48 hours"
- "Inter-org communication goes through the liaison, never direct"

**Characteristics:**
- Scope: organization or workgroup level
- Changes slowly, through consensus or demonstrated pattern
- Broadly applicable within scope
- Curated, not automatically generated

### 2.2 Task-Based Learning

How teams get better at specific types of tasks, with generalization across similar tasks.

**Examples:**
- Rules: "Always backup before migrating a database"
- Procedures: "For API endpoints, follow this sequence: schema, route, tests, docs"
- Skills: executable procedures (Claude Code skills, workflow templates)
- Causal abstractions: "When X, doing Y leads to Z" (CLIN-style)

**Characteristics:**
- Scope: task category, potentially cross-cutting
- Changes with each task outcome — empirical and fast
- Narrowly relevant — only useful when doing a matching task type
- Task boundaries are fuzzy — a "database migration" learning may apply to schema redesigns, ORM changes, and data backfills

### 2.3 Proxy Learning

How the human proxy captures the human's behavior so it can act as an accurate stand-in for low-risk decisions. Proxy learning is further subdivided:

**Preferential** — the human's general traits: communication style, risk tolerance, values, trust levels, delegation boundaries. Stable, broadly applicable, always loaded.

**Task-based** — the human's domain-specific decision patterns: when to consult vs act, triage heuristics, delegation scope by area. Context-specific, retrieved on demand.

The preferential/task-based split mirrors the institutional/task-based split at the team level. See [human-proxies.md](human-proxies.md) for the full proxy model.

---

## 3. The Taxonomy: Scope x Type

Every learning has two coordinates: what scope it belongs to (where in the hierarchy) and what type it is (institutional, task-based, or proxy).

```
                 Institutional               Task-Based
                 (how we/they are)           (how we/they do X)
                 ────────────────            ────────────────────

Global           Cross-project norms         Cross-project task patterns
                 (how we work across         (rules/procedures that apply
                 all projects)               regardless of project)

Project          Project conventions          Project task patterns
                 (how this project works)     (what works for this project's
                                              task types)

Team             Team norms                   Team task learnings
                 (how this team coordinates)  (tool preferences, procedures
                                              for this team's work)

Human            Human preferences            Human task patterns
(proxy)          (communication style,        (domain-specific decisions,
                 risk tolerance, values)       approval patterns per task type)
```

The vertical axis (scope) is handled by the promotion chain — the existing mechanism from the POC that promotes durable learnings upward through dispatch → team → session → project → global, filtering more aggressively at each level.

The horizontal axis (type) determines storage format and retrieval strategy:

| Type | Storage | Retrieval | Budget |
|------|---------|-----------|--------|
| Institutional | Prose markdown file | Always loaded at matching scope | Fixed, small |
| Task-based | Chunked, embedded, FTS-indexed | Fuzzy query against current task context | Variable, top-N chunks |
| Proxy preferential | Prose markdown file | Always loaded when proxy is active | Fixed, small |
| Proxy task-based | Chunked, embedded, FTS-indexed | Fuzzy query against current task context | Variable, top-N chunks |

---

## 4. File Layout by Type

Mixing learning types in a single file reintroduces the undiscriminated injection problem. Each type gets its own file or store at each scope level:

```
projects/
  institutional.md          # global org norms (always loaded)
  tasks/                    # global task-based chunks (memsearch store)
  proxy.md                  # human preferential (always loaded)
  proxy-tasks/              # human task-based chunks (memsearch store)

  my-project/
    institutional.md        # project-level conventions (always loaded)
    tasks/                  # project task-based chunks (memsearch store)

    .sessions/<ts>/
      <team>/
        institutional.md    # team coordination norms (always loaded)
        tasks/              # team task-based chunks (memsearch store)
```

Always-loaded types (institutional, proxy preferential) are compact prose files — no retrieval problem to solve, injected at the appropriate scope like CLAUDE.md. Fuzzy-retrieved types (task-based, proxy task-based) are chunked, embedded, and FTS-indexed via memsearch (sqlite-vec + FTS5 hybrid). At retrieval time, the current task context is the query; top-N chunks (budget-constrained) are injected. Task boundaries bleed — semantic similarity captures cross-type connections that hard classification lookup would miss.

---

## 5. Learning Moments and Promotion

From the POC's learning-evolution analysis, four moments trigger writes to the stores:

| Moment | When | Signal |
|--------|------|--------|
| **Prospective** | Before execution | Retrieval only — useful retrievals get confidence boost |
| **In-flight** | At milestones | Assumption checkpoints; disconfirmed assumptions amplify corrective signal |
| **Corrective** | At mismatch (escalation, replan) | Highest confidence — direct evidence of model error with recoverable causal chain |
| **Retrospective** | After completion | Synthesized learnings promoted through the chain; lowest immediacy but enables cross-session transfer |

The promotion chain moves learnings **within type** — institutional never becomes task-based, proxy never becomes institutional:

```
Team institutional.md  ──promotes──>  Project institutional.md  ──promotes──>  Global institutional.md
Team tasks/            ──promotes──>  Project tasks/            ──promotes──>  Global tasks/
```

Each step filters more aggressively: team → project requires patterns that held across multiple sessions; project → global requires project-agnostic patterns. Proxy learnings do not promote upward (they describe a specific human).

---

## 7. Relationship to Existing Systems

**[cognitive-architecture.md](cognitive-architecture.md)** — Research foundations; proposes a per-agent memory system (episodic, semantic, procedural). This document supersedes sections 6-8 of that doc; the research survey (sections 1-5) remains valid.

**[poc-architecture.md](poc-architecture.md)** — The POC's promotion chain (dispatch → team → session → project → global) is the structural foundation. This design adds type differentiation within each scope level and replaces flat injection with typed stores and fuzzy retrieval for task-based learnings.

**[intent-engineering.md](intent-engineering.md)** — The first consumer of proxy learnings. Warm-start pre-population draws from `proxy.md` and `proxy-tasks/`. Corrections to pre-populated intent are high-value write signals.

**memsearch** — The fuzzy retrieval layer uses memsearch (sqlite-vec + FTS5), the OpenClaw memory module extracted by Zilliz as a standalone library. Provides chunking, embedding, indexing, and hybrid score fusion.

---

## 8. Open Questions

Open research questions for this area are collected in [Research Directions](research-directions.md).

---

## 9. References

- [cognitive-architecture.md](cognitive-architecture.md) — Research foundations; proposed per-agent memory system (sections 6-8 superseded by this document); full external citation list (CLIN, ExpeL, Reflexion, Generative Agents, FadeMem, CoALA, MemGPT, OpenClaw)
- [hierarchical-teams.md](hierarchical-teams.md) — Team structure: organizations, workgroups, liaisons, job/project/engagement teams
- [poc-architecture.md](poc-architecture.md) — POC implementation including the memory promotion chain (dispatch → team → session → project → global)
- [intent-engineering.md](intent-engineering.md) — Intent engineering system, least-regret escalation, relationship to institutional memory
- [Research Index](research/INDEX.md) — Full research catalog with 50+ papers informing the cognitive architecture and learning system design
