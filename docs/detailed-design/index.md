# Detailed Design

This section maps the conceptual design to the actual implementation. It describes what exists in code today, how the components integrate, and where the implementation diverges from or has not yet reached the conceptual design. Gaps are called out honestly with references to the GitHub issues that track them.

The conceptual design is spread across the documents in the parent folder — [ARCHITECTURE.md](../ARCHITECTURE.md), [human-proxies.md](../human-proxies.md), [learning-system.md](../learning-system.md), [cfa-state-machine.md](../cfa-state-machine.md), [intent-engineering.md](../intent-engineering.md), [strategic-planning.md](../strategic-planning.md), [hierarchical-teams.md](../hierarchical-teams.md), and [folder-structure.md](../folder-structure.md). These detailed design documents do not repeat the conceptual rationale. They specify how the concepts are (or are not) realized in the codebase.

---

## Documents

- [Agent Runtime](agent-runtime.md) — CLI invocation design, orchestrator architecture, hierarchical dispatch
- [CfA State Machine](cfa-state-machine.md) — State representation, transition table, design choices
- [Approval Gate](approval-gate.md) — Proxy decision model, confidence computation, design choices
- [Learning System](learning-system.md) — Memory hierarchy, extraction pipeline, design choices

---

## Gap Summary

### Pillar Status

The conceptual design rests on four pillars. Here is an honest assessment of each:

**Conversation for Action (CfA).** The state machine is fully implemented (`cfa_state.py`) with correct states, transitions, and validation. It is integrated with the orchestrator — `engine.py` takes `CfaState` as a core parameter and manages transitions, and `actors.py` routes actions based on CfA state. The three-phase protocol (Intent → Planning → Execution) with backtrack transitions is operational.

**Hierarchical Teams.** Two-level hierarchy is operational: an upper team coordinates while subteams execute, each in its own process. Liaisons invoke `dispatch_cli.py` via Bash to create child orchestrators in isolated subprocess worktrees — process boundaries provide context isolation by design. Dispatch includes child CfA state creation, worktree isolation, and squash-merge on completion. The conceptual design's three-level work hierarchy (Engagement → Project → Job) exists in the data model but the full engagement orchestration (org lead negotiation, decomposition, feedback bubble-up) is not yet agent-driven end-to-end.

**Learning System.** Post-session learning extraction exists (`learnings.py`, called from `session.py`). Helper modules exist for memory indexing, session summarization, reinforcement tracking, and memory compaction. These run post-session — no online learning during execution. Reinforcement tracking is now wired in: `extract_learnings()` calls `reinforce_entries()` at session end to strengthen entries that were retrieved and used ([#91](https://github.com/dlewissandy/teaparty/issues/91), resolved). The full learning system — four types, scoped retrieval, promotion chain, four learning moments — is designed but not fully implemented. This remains the largest gap between conceptual design and implementation.

**Human Proxy.** The approval gate is integrated with the orchestrator — `ApprovalGate` in `actors.py` wraps `approval_gate.py` and is invoked by `engine.py` at ASSERT and ESCALATE states. It implements the confidence model, asymmetric regret (REGRET_WEIGHT=3), cold start guard, staleness guard, exploration rate, content checks, and basic generative prediction. Phase 1 of the intake dialog is implemented ([#125](https://github.com/dlewissandy/teaparty/issues/125)): cold-start detection, agent prompt enrichment for exploration-first behavior, and engagement-framed escalation bridge text. Retrieval-backed prediction, text derivative learning, behavioral rituals, and gap-detection questioning remain design targets.

### Remaining Gaps

**Learning as foundation.** The human proxy's retrieval-backed prediction depends on the learning system's scoped retrieval. The intake dialog depends on having proxy learnings to predict from. The planning warm start depends on procedural learning (skills). These dependencies mean the learning system is a prerequisite for the other three pillars to reach their full conceptual design — and the learning system has the largest implementation gap.

---

## Experimental Results

Ablative experiments designed to validate each pillar's architectural claims are documented in [Experimental Results →](../experimental-results/index.md).

**Engagement orchestration.** The conceptual design describes a full engagement lifecycle (proposed → accepted → in_progress → completed → reviewed) with partnerships (directional trust, cycle prevention) and org lead orchestration (negotiation, decomposition into projects/jobs, feedback bubble-up). The POC implements two-level dispatch but not the full engagement orchestration loop.

**Dispatch completeness.** The subprocess dispatch path works. Most gaps against the original shell scripts have been resolved — merge conflict retry, commit handling, JSON result fields, and worktree isolation are implemented. Remaining open items are tracked in the issues backlog.
