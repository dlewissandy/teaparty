# Artifacts

The May 2 session left a complete artifact trail on disk: planning documents, architecture, per-chapter research, six chapter drafts plus the load-bearing architecture document, an editorial review, and the proxy's ACT-R memory at session end.

The artifacts below are extracted from the two writing-lead worktrees (`283d258761f4` and `d5c742adab3d`). The two worktrees ran in parallel against a shared base; ch1 through ch4 and `architecture.md` were identical between them, so only one copy is preserved here. Ch5 came from the first writing-lead's tree; ch7 came from the second.

---

## Planning artifacts

The CfA Intent and Plan phases produce on-disk artifacts the human approves before execution begins. The planner also consulted a skill candidate from a prior humor-book attempt during DRAFT — the candidate file is included so the cross-run knowledge reuse is inspectable.

| Artifact | What it is | File |
|---|---|---|
| Original prompt | The four-sentence ask that started the session | [IDEA_v2.md](./artifacts/planning/IDEA_v2.md) |
| Approved intent | The deliverable, audience, success criteria, hard stops | [INTENT_v2.md](./artifacts/planning/INTENT_v2.md) |
| Approved plan | Phase 0 architecture; per-chapter drafting cadence; manuscript-level passes | [PLAN_v2.md](./artifacts/planning/PLAN_v2.md) |
| Consulted skill candidate | The May 1 humor-book attempt's plan, read by May 2's planner during DRAFT | [may01-skill-candidate.md](./artifacts/planning/may01-skill-candidate.md) |

---

## Architecture and per-chapter research

Phase 0 of the plan produced an architecture document — the load-bearing decisions before any chapter drafts. Per-chapter research dossiers backed it.

| Artifact | What it is | File |
|---|---|---|
| Architecture | Thesis arc, era spine, case slate, callback design, voice probe, word budget | [architecture.md](./artifacts/manuscript/architecture.md) |
| Case slate (research source-of-truth) | Per-chapter primary cases plus backups, with sources and boundary-axis tags | [case-slate.md](./artifacts/research/architecture/case-slate.md) |
| Counterexample slate (Ch7 reference) | Divisive-humor and locally-broken cases the chapter commits to engaging | [counterexample-slate.md](./artifacts/research/architecture/counterexample-slate.md) |

| Chapter | Research dossier |
|---|---|
| Ch 1 | [sources.md](./artifacts/research/ch1/sources.md) |
| Ch 2 | [sources.md](./artifacts/research/ch2/sources.md) |
| Ch 3 | [sources.md](./artifacts/research/ch3/sources.md) |
| Ch 4 | [sources.md](./artifacts/research/ch4/sources.md) |
| Ch 5 | [sources.md](./artifacts/research/ch5/sources.md) |
| Ch 7 | [sources.md](./artifacts/research/ch7/sources.md) |

---

## Manuscript chapters

Six chapter drafts. The architecture document also lives at the manuscript root because Phase 0 treated it as the load-bearing document the rest of the manuscript references.

| Chapter | Draft |
|---|---|
| Architecture (Phase 0) | [architecture.md](./artifacts/manuscript/architecture.md) |
| Ch 1 | [ch1.md](./artifacts/manuscript/ch1.md) |
| Ch 2 | [ch2.md](./artifacts/manuscript/ch2.md) |
| Ch 3 | [ch3.md](./artifacts/manuscript/ch3.md) |
| Ch 4 | [ch4.md](./artifacts/manuscript/ch4.md) |
| Ch 5 | [ch5.md](./artifacts/manuscript/ch5.md) |
| Ch 7 | [ch7.md](./artifacts/manuscript/ch7.md) |

---

## Editorial review

| Artifact | What it is | File |
|---|---|---|
| Architecture coherence review | Editorial review of the Phase 0 architecture document — checks that the thesis arc, case slate, and callback design hang together as one argument before the chapters commit | [architecture-coherence-review.md](./artifacts/editorial/architecture-coherence-review.md) |

---

## Proxy & ACT-R memory

The proxy's persistent memory at session end. See [Proxy & ACT-R Memory](proxy-and-memory.md) for the analysis of how this was used during the six escalations.

| Artifact | What it is | File |
|---|---|---|
| Proxy memory bank | ACT-R chunks (procedural / institutional, with importance, reinforcement count, last-reinforced timestamp) accumulated across sessions on this project | [proxy-memory.md](./artifacts/proxy/proxy-memory.md) |
| Consolidation log | 45 consolidation decisions during this session — 38 ADD, 7 SKIP — recording how candidate observations were merged into the memory bank | [proxy-consolidation-log.jsonl](./artifacts/proxy/proxy-consolidation-log.jsonl) |
