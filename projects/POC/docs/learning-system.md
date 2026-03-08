# Learning System Design

> This document describes the learning system for TeaParty's hierarchical agent teams. It builds on the research foundations in [cognitive-architecture.md](cognitive-architecture.md) and the team structure in [hierarchical-teams.md](hierarchical-teams.md). The POC implementation is in [projects/POC/](../projects/POC/).

---

## 1. The Problem

Claude Code's built-in memory system (MEMORY.md) fails at retrieval and application. The failure has three causes:

**No retrieval discrimination.** The first 200 lines of MEMORY.md are injected verbatim into every session regardless of relevance. As memory grows, signal-to-noise drops — useful learnings are buried in irrelevant ones. There is no embedding, no scoring, no context matching. The word "retrieval" means "the agent reads a file with the Read tool."

**Prose is lossy for procedural knowledge.** "Always review code before running tests" as a sentence in a markdown file is a fact the agent knows, not a rule the agent follows. There is a fundamental gap between declarative knowledge (knowing that) and procedural knowledge (knowing how). The memory system stores everything as the former and hopes it activates the latter.

**No validation loop.** A learning written once and never tested has the same standing as one confirmed fifty times. There is no reinforcement, no decay, no contradiction detection. Stale or wrong memories persist and actively mislead.

The deeper problem: Claude Code's memory treats learning as **storage** when it is actually a **retrieval** problem. Storing things is easy. Getting the right thing at the right moment and having it actually influence behavior — that is the hard part.

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

**Preferential** — the human's general traits:
- Communication style (concise vs verbose, formal vs casual)
- Risk tolerance (general baseline)
- Values and priorities ("conceptual clarity always")
- Trust levels per workgroup, per agent, per domain
- Delegation boundaries (what they approve vs what they trust agents to decide)

**Task-based** — the human's domain-specific decision patterns:
- "For database changes, Darrell wants to be consulted before applying"
- "For UI work, Darrell trusts the design workgroup — don't escalate unless it touches the nav"
- "Darrell's bug triage approach: severity first, then recency"

The preferential/task-based split mirrors the institutional/task-based split at the team level. Preferential learnings are stable and broadly applicable. Task-based learnings are context-specific and retrieved on demand.

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

The horizontal axis (type) determines storage format and retrieval strategy. These are fundamentally different:

| Type | Storage | Retrieval | Budget |
|------|---------|-----------|--------|
| Institutional | Prose markdown file | Always loaded at matching scope | Fixed, small |
| Task-based | Chunked, embedded, FTS-indexed | Fuzzy query against current task context | Variable, top-N chunks |
| Proxy preferential | Prose markdown file | Always loaded when proxy is active | Fixed, small |
| Proxy task-based | Chunked, embedded, FTS-indexed | Fuzzy query against current task context | Variable, top-N chunks |

---

## 4. Separate Files by Type

Mixing learning types in a single MEMORY.md reintroduces the undiscriminated injection problem. If they share a file, you either load everything (noise) or need retrieval to pick through it (defeating the purpose of the always-loaded types).

Each type gets its own file or store at each scope level:

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

### 4.1 `institutional.md` — Always Loaded

Prose. Compact. Curated. Changes through consensus or demonstrated pattern. The promotion chain filters and promotes upward within this type only. This is CLAUDE.md's successor for learned norms — not instructions, but observed patterns of how the team/org/project actually works.

### 4.2 `tasks/` — Fuzzy Retrieved

Chunked, embedded, and FTS-indexed via memsearch (the OpenClaw memory module extracted by Zilliz). At retrieval time, the current task context is the query. Only top-scoring chunks are injected. The promotion chain promotes generalizable task learnings upward (team → project → global), but content stays in the chunk store, not in a prose file.

### 4.3 `proxy.md` — Always Loaded

The human's preferential model. Communication style, risk tolerance, trust boundaries, values. Compact and broadly applicable. Lives at the top level because it describes the human, not a project or team — though project-scoped overrides are possible if the human behaves differently in different contexts.

### 4.4 `proxy-tasks/` — Fuzzy Retrieved

The human's domain-specific decision patterns. Chunked and embedded like `tasks/`. Retrieved when the proxy needs to simulate the human's judgment for a specific type of task. These inform escalation and approval, not execution.

---

## 5. Retrieval Architecture

### 5.1 Always-Loaded Types (Institutional, Proxy Preferential)

No retrieval problem to solve. These are injected at the appropriate scope, like CLAUDE.md. The constraint is keeping them concise and current — they pay their token cost on every session within scope.

### 5.2 Fuzzy-Retrieved Types (Task-Based, Proxy Task-Based)

Retrieval uses the memsearch architecture (sqlite-vec + FTS5 hybrid):

1. **Write time**: when a learning is extracted (at any of the four learning moments), it is chunked (~400 tokens), embedded, and indexed in the appropriate scope's chunk store.

2. **Query time**: the current task context (task description, classification, recent conversation) becomes the query. Cosine similarity + FTS5 scores are fused.

3. **Scope weighting**: each scope level's store is queried independently. Results are merged with a scope multiplier — a team-level chunk at 0.7 similarity beats a global chunk at 0.8 because it is more contextually specific. The promotion chain already ensures that only appropriately general learnings live at higher scopes, so scope is a reliable proxy for specificity.

4. **Injection**: top-N chunks (budget-constrained) are injected into the agent's context alongside the always-loaded institutional and proxy files.

### 5.3 Why Fuzzy, Not Classification-Based Lookup

Task boundaries bleed. A "database migration" learning is relevant during schema redesign, ORM changes, and data backfill — different task types where the learning transfers. Hard classification lookup would miss these cross-type connections. Semantic similarity captures them because the content is related even when the categories are not.

---

## 6. Learning Moments (Write Side)

From the POC's learning-evolution analysis, there are four moments when learning occurs. These are the write triggers into the stores:

### 6.1 Prospective

Before execution begins. Query the stores: what do we already know that applies here? This is retrieval, not writing — but retrieval results that prove useful (confirmed by successful execution) get their confidence boosted.

### 6.2 In-Flight

At each major milestone. Model-update notes capture whether working assumptions are holding. These become new chunks with high recency and moderate confidence. If an assumption is disconfirmed, the corrective learning (6.3) carries more weight.

### 6.3 Corrective

At the moment of mismatch — an escalation, a direction change, a replan. The learning is not what happened but what upstream assumption failed. Corrective learnings carry the highest confidence weight because they are direct evidence of a model error: a falsified prediction with a recoverable causal chain.

### 6.4 Retrospective

After completion. Synthesized learnings promoted through the chain. The least valuable of the four moments — by the time learnings are extracted, the opportunity to act on them has closed — but valuable for cross-session transfer.

---

## 7. Promotion Within Type

The promotion chain promotes learnings **within type**. An institutional learning never becomes a task-based learning through promotion. A proxy learning never becomes an institutional learning.

```
Team institutional.md  ──promotes──>  Project institutional.md  ──promotes──>  Global institutional.md
Team tasks/            ──promotes──>  Project tasks/            ──promotes──>  Global tasks/
```

Each promotion step filters more aggressively:
- **Team → Project**: only patterns that held across multiple team sessions
- **Project → Global**: only patterns that are project-agnostic

Proxy learnings do not promote upward (they describe a specific human), but they can be refined through the same confidence scoring: confirmed observations gain weight, contradicted ones lose it.

---

## 8. Confidence and Decay

Learnings are not permanent. They have confidence scores that change over time:

- **Single observation**: 0.5 initial confidence
- **Confirmed by successful application**: +0.1 (capped at 0.95)
- **Contradicted by observation**: -0.2
- **Explicitly stated by human** ("always do X"): 0.95 initial
- **Time decay**: confidence decreases without reinforcement (FadeMem-inspired)
- **Corrective learnings**: 0.8 initial (direct evidence of model error)

Chunks below a confidence threshold are excluded from retrieval results. Chunks that decay below a lower threshold are archived (not deleted — available for review but not surfaced).

---

## 9. Relationship to Existing Systems

### 9.1 Cognitive Architecture (cognitive-architecture.md)

That document covers the research foundations and proposes a per-agent memory system (episodic, semantic, procedural). This document supersedes the proposed architecture in sections 6-8 of that doc. The research survey (sections 1-5) remains valid and informs this design.

### 9.2 POC Memory Hierarchy (projects/POC/)

The POC's promotion chain (dispatch → team → session → project → global) is the structural foundation. This design adds type differentiation within each scope level and replaces flat MEMORY.md injection with typed stores and fuzzy retrieval for task-based learnings.

### 9.3 Intent Engineering (intent-engineering-spec.md)

The intent engineering system is the first consumer of proxy learnings. Warm-start pre-population draws from `proxy.md` (preferential) and `proxy-tasks/` (task-based). Corrections to pre-populated intent are high-value write signals for both stores.

### 9.4 OpenClaw / memsearch

The fuzzy retrieval layer uses memsearch (sqlite-vec + FTS5) for the task-based stores. This is the OpenClaw memory module extracted by Zilliz as a standalone library. It provides chunking, embedding, indexing, and hybrid score fusion out of the box.

---

## 10. Open Questions

**Embedding model choice.** memsearch uses a local embedding model. The quality of fuzzy retrieval depends on embedding quality. Trade-off: better embeddings cost more; local embeddings are fast but less capable.

**Scope multiplier calibration.** Team-level chunks should score higher than global chunks at equal similarity, but by how much? This needs empirical tuning across real task histories.

**Cross-type retrieval.** Should an institutional learning ever inform task-based retrieval, or vice versa? The current design keeps them strictly separate. There may be cases where institutional norms are relevant to task execution ("our org always does X before Y") that fuzzy retrieval within the task store would miss.

**Proxy model validation.** How do you know the proxy model is accurate? The escalation calibration model (intent-engineering-spec.md) provides one signal (act/ask outcomes), but there is no direct "would the human have made this decision?" validation for low-risk decisions the proxy handles autonomously.

**Cold start.** A new project/team/human has no learnings. The system defaults to escalation (conservative) per the intent engineering spec's cold-start design. But how quickly can the stores accumulate enough signal to be useful? The four learning moments (especially corrective) help, but the rate of useful learning per session is an empirical question.

---

## 11. References

### Retrieval Architecture

- **OpenClaw Memory Architecture.** Steinberger et al., 2025-2026. Hybrid sqlite-vec + FTS5 retrieval over chunked Markdown; selective injection vs. Claude Code's flat injection. [docs.openclaw.ai/concepts/memory](https://docs.openclaw.ai/concepts/memory)
- **memsearch.** Zilliz, 2025. OpenClaw's memory module extracted as a standalone library. Provides chunking, embedding, indexing, and hybrid score fusion. [github.com/zilliztech/memsearch](https://github.com/zilliztech/memsearch)
- **Claude Code Memory System.** Anthropic, 2025-2026. MEMORY.md first 200 lines injected verbatim; topic files read on demand; no semantic retrieval. [code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory)

### Learning Mechanisms

- **CLIN: A Continually Learning Language Agent.** Majumder et al., 2024. Causal abstraction learning ("when X, doing Y leads to Z") that persists across episodes and transfers across tasks. Outperforms Reflexion by 23 points on ScienceWorld. [arxiv.org/abs/2310.10134](https://arxiv.org/abs/2310.10134)
- **ExpeL: LLM Agents Are Experiential Learners.** Zhao et al., AAAI 2024. Contrastive learning from successes vs. failures extracts cross-task insights. [arxiv.org/abs/2308.10144](https://arxiv.org/abs/2308.10144)
- **Reflexion: Language Agents with Verbal Reinforcement Learning.** Shinn et al., NeurIPS 2023. Self-reflection stored as persistent memory enables learning without weight updates. [arxiv.org/abs/2303.11366](https://arxiv.org/abs/2303.11366)
- **Generative Agents: Interactive Simulacra of Human Behavior.** Park et al., UIST 2023. Three-factor retrieval (recency x relevance x importance) and periodic reflection. Reflection was the critical ingredient. [arxiv.org/abs/2304.03442](https://arxiv.org/abs/2304.03442)

### Memory Decay and Forgetting

- **FadeMem.** 2025. Biologically-inspired decay: 82.1% retention of critical facts at 55% storage vs. 78.4% at 100% storage. Selective forgetting improves retention quality. [co-r-e.com/method/agent-memory-forgetting](https://www.co-r-e.com/method/agent-memory-forgetting)

### Frameworks

- **Cognitive Architectures for Language Agents (CoALA).** Sumers, Yao, Narasimhan & Griffiths, TMLR 2024. The unifying taxonomy mapping classical cognitive architecture onto LLM agents across memory types, action space, and learning. [arxiv.org/abs/2309.02427](https://arxiv.org/abs/2309.02427)
- **MemGPT / Letta.** Packer et al., 2023. Agent-managed memory hierarchy via explicit tools — agents decide what to remember, forget, and retrieve. [arxiv.org/abs/2310.08560](https://arxiv.org/abs/2310.08560)

### Internal Documents

- [cognitive-architecture.md](cognitive-architecture.md) — Research foundations, classical and modern cognitive architectures, proposed per-agent memory system (sections 6-8 superseded by this document)
- [hierarchical-teams.md](hierarchical-teams.md) — Team structure: organizations, workgroups, liaisons, job/project/engagement teams
- [projects/POC/docs/POC.md](../projects/POC/docs/POC.md) — POC implementation including the memory promotion chain (dispatch → team → session → project → global)
- [projects/POC/poc-workflow/learning-evolution.md](../projects/POC/poc-workflow/learning-evolution.md) — The four learning moments: prospective, in-flight, corrective, retrospective
- [projects/POC/docs/intent-engineering-spec.md](../projects/POC/docs/intent-engineering-spec.md) — Intent engineering system, least-regret escalation, relationship to institutional memory, and the OpenClaw Memory Architecture Research companion project
- [projects/POC/poc-workflow/human-dynamics.md](../projects/POC/poc-workflow/human-dynamics.md) — Shared mental models, asymmetric trust, calibrated communication from organizational psychology
- [docs/research/INDEX.md](research/INDEX.md) — Full research catalog with 50+ papers informing the cognitive architecture and learning system design
