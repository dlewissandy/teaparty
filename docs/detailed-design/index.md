# Detailed Design

This section maps the conceptual design to the actual implementation. It describes what exists in code today, how the components integrate, and where the implementation diverges from or has not yet reached the conceptual design. Gaps are called out honestly with references to the GitHub issues that track them.

The conceptual design is spread across the documents in the parent folder — [overview.md](../overview.md), [conceptual-design/human-proxies.md](../conceptual-design/human-proxies.md), [conceptual-design/learning-system.md](../conceptual-design/learning-system.md), [conceptual-design/cfa-state-machine.md](../conceptual-design/cfa-state-machine.md), [conceptual-design/intent-engineering.md](../conceptual-design/intent-engineering.md), [conceptual-design/strategic-planning.md](../conceptual-design/strategic-planning.md), [conceptual-design/hierarchical-teams.md](../conceptual-design/hierarchical-teams.md), and [reference/folder-structure.md](../reference/folder-structure.md). These detailed design documents do not repeat the conceptual rationale. They specify how the concepts are (or are not) realized in the codebase.

---

## Scope

These documents describe the **orchestrator layer** — the runtime that drives the CfA state machine and coordinates agent teams. The orchestrator is implemented at `projects/POC/orchestrator/`. They do not describe the engagement orchestration layer (org lead negotiation, decomposition into projects, feedback bubble-up), which is upstream and addressed in the conceptual design documents. See [conceptual-design/hierarchical-teams.md](../conceptual-design/hierarchical-teams.md) for the full conceptual model.

---

## Documents

- [Agent Runtime](agent-runtime.md) — CLI invocation design, orchestrator architecture, hierarchical dispatch
- [CfA State Machine](cfa-state-machine.md) — State representation, transition table, design choices
- [Approval Gate](approval-gate.md) — Proxy decision model, confidence computation, design choices
- [Learning System](learning-system.md) — Memory hierarchy, extraction pipeline, design choices

---

## Gap Summary

### Pillar Status

The conceptual design rests on four pillars. Here is an honest assessment of each, organized by maturity level:

#### Conversation for Action (CfA)

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Fully implemented | State machine is fully implemented in `cfa_state.py` with correct states, transitions, and validation. Three-phase protocol (Intent → Planning → Execution) with backtrack transitions works in practice. |
| **Integrated** | Yes | Integrated with the orchestrator — `engine.py` takes `CfaState` as a core parameter and manages transitions, and `actors.py` routes actions based on CfA state. |
| **Full Design** | Not yet | [#92](https://github.com/dlewissandy/teaparty/issues/92) tracks replacing bespoke state management with `python-statemachine` library for formal guard conditions and visualization. |

#### Hierarchical Teams

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Two-level hierarchy works | Upper team coordinates; subteams execute in isolated subprocess worktrees. Process boundaries provide context isolation. Dispatch includes child CfA state creation, worktree isolation, and squash-merge on completion. |
| **Integrated** | Partially | Dispatch works; engagement orchestration (org lead negotiation, decomposition, feedback bubble-up) is not yet agent-driven end-to-end. |
| **Full Design** | Not yet | Full three-level work hierarchy (Engagement → Project → Job) is modeled but not operationalized. See [hierarchical-teams.md](../conceptual-design/hierarchical-teams.md) for the conceptual vision. |

#### Learning System

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | Post-session learning extraction (`learnings.py`), memory indexing, session summarization, reinforcement tracking, and memory compaction are all wired. Promotion chain (`promotion.py`) implements session → project → global gates with recurrence detection and proxy exclusion ([#217](https://github.com/dlewissandy/teaparty/issues/217)). Continuous skill refinement detects execution friction, refines skill templates via LLM, and suppresses degraded skills ([#229](https://github.com/dlewissandy/teaparty/issues/229)). Temporal decay with 90-day half-life and decay floor ([#218](https://github.com/dlewissandy/teaparty/issues/218)). No online learning during execution. |
| **Integrated** | Yes | Reinforcement tracking wired ([#91](https://github.com/dlewissandy/teaparty/issues/91)). Scope multipliers integrated into retrieval. Type-aware budget allocation implemented ([#197](https://github.com/dlewissandy/teaparty/issues/197)). Proxy learning integration complete — bidirectional feedback between proxy corrections and agent learnings ([#198](https://github.com/dlewissandy/teaparty/issues/198)). Memory context injection works. |
| **Full Design** | Not yet | In-flight and prospective extraction are design targets. Skill crystallization (automatic generalization of repeated plans) is not yet implemented. |

#### Human Proxy

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | Three-tier proxy path: flat patterns, interaction history, and ACT-R memory retrieval with two-pass prediction (prior/posterior). Cold-start gating via ACT-R memory depth ([#220](https://github.com/dlewissandy/teaparty/issues/220)). EMA decoupled from confidence — monitoring only. Contradiction detection and resolution in proxy memory with LLM-as-judge classification ([#228](https://github.com/dlewissandy/teaparty/issues/228)). Per-context prediction accuracy tracking per (state, task_type) pair ([#226](https://github.com/dlewissandy/teaparty/issues/226)). Asymmetric confidence decay following Hindsight (arXiv:2512.12818). Post-session proxy memory consolidation wired. |
| **Integrated** | Yes | Proxy learning integrated with main learning system — bidirectional feedback ([#198](https://github.com/dlewissandy/teaparty/issues/198)). ACT-R memory retrieval feeds into proxy context. Salience index separated from chunk embeddings ([#227](https://github.com/dlewissandy/teaparty/issues/227)). Embedding wired into pattern compaction ([#214](https://github.com/dlewissandy/teaparty/issues/214)). ACT-R Phase 1 ablation harness operational: multi-dim vs single embedding ([#222](https://github.com/dlewissandy/teaparty/issues/222)), activation decay vs recency ([#223](https://github.com/dlewissandy/teaparty/issues/223)), composite vs component scoring ([#225](https://github.com/dlewissandy/teaparty/issues/225)). |
| **Full Design** | Not yet | Intake dialog Phases 2–3, text derivative learning, behavioral rituals, and gap-detection questioning are design targets. Actual proxy accuracy on real escalations is unmeasured. |

### Key Dependencies and Preconditions

**Learning as foundation.** The human proxy's retrieval-backed prediction depends on the learning system's scoped retrieval. The intake dialog depends on having proxy learnings to predict from. The planning warm start depends on procedural learning (skills). These dependencies mean the learning system is a prerequisite for the other three pillars to reach their full conceptual design. With promotion chain, type-aware retrieval, proxy-learning integration, and continuous skill refinement now operational, the remaining gaps are in-flight/prospective extraction and automatic skill crystallization.

---

## Remaining Gaps

**Engagement orchestration.** The conceptual design describes a full engagement lifecycle (proposed → accepted → in_progress → completed → reviewed) with partnerships (directional trust, cycle prevention) and org lead orchestration (negotiation, decomposition into projects/jobs, feedback bubble-up). The POC implements two-level dispatch but not the full engagement orchestration loop.

**Dispatch completeness.** The subprocess dispatch path works. Most gaps against the original shell scripts have been resolved — merge conflict retry, commit handling, JSON result fields, and worktree isolation are implemented. Remaining open items are tracked in the issues backlog.

---

## Experimental Results

Ablative experiments designed to validate each pillar's architectural claims are documented in [Experimental Results →](../experimental-results/index.md).
