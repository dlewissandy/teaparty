# Learnings & Assessment

The session produced three learning artifacts that show the system observing itself, and it exercised all four pillars of the TeaParty architecture. This page examines both: what the system learned, and what the session demonstrates about the platform.

---

## Learning Artifacts

### Alignment observations ([tasks](../e2e-raw-files/tasks))

The learning system generated seven "alignment observations" — each comparing what the intent or plan *said* would happen against what *actually* happened, categorized by type. Three examples:

**Boundary deviation — phase overlap.** The plan specified strict sequential phases, but when the prologue brief kept failing to persist, the system started Phase 2 spec work on Ch1–7 while retrying the prologue. The learning system flagged this as a deviation and surfaced the implicit design question: *"Should Phase N+1 begin before Phase N is complete if Phase N is partially stalled?"* This was the right adaptation — but it was improvised. The learning converts it into an explicit choice for next time.

**Intent gap — rate limits.** Six of eight research tracks hit provider rate limits on the first dispatch wave. The learning system noted: *"The infrastructure ceiling wasn't anticipated in the intent. Re-dispatch required human intervention to wait for limit reset."* It proposed three strategies for future intents: automatic retry with backoff, sequential dispatch to stay under limits, or a monitoring loop from the start. This session used option (c), but late and reactively.

**Success criteria missed — no quality gate.** The intent stated research briefs would be verified before Phase 2, but no verification checkpoint was implemented. Phase 2 launched the moment briefs hit disk. The learning: *"on disk = ready to proceed"* was the implicit assumption; *"on disk AND meets quality bar"* is what the intent meant. Future intents need explicit completion definitions.

The observations were synthesized into five questions to ask during the next session's intent-gathering phase — so the next plan is smarter than the last execution.

### Proxy confidence model ([proxy-confidence.json](../e2e-raw-files/proxy-confidence.json))

This file tracks the proxy's decision history across every CfA state, building a statistical model of how the proxy performed at each gate type. The data tells a clear story:

- **INTENT_ASSERT and PLAN_ASSERT:** Clean approvals, `ema_approval_rate` of 0.65. The proxy read the intent and plan, found them sound, and approved. No corrections needed.
- **DRAFT (planning dialog):** Four interactions, all classified as "clarify" — the proxy was relaying human questions to the planning agent. It recorded `predicted_response` fields for two of them, showing the proxy reasoning about what the human would say. For the visuals question, the proxy predicted: *"Straight prose. Write it so vividly that the reader can picture the comedy wildlife shots without needing to see them."* The human said essentially the same thing. The proxy was modeling the human's preferences correctly even when the human hadn't spoken yet.
- **TASK_ASSERT:** Seven interactions, of which six were classified "correct" (meaning the proxy provided revision feedback rather than a clean approve). The `ema_approval_rate` dropped to 0.30 — the lowest of any gate type. The confidence model captured 15 `question_patterns`, almost all tagged as "sequencing" concerns. This is the proxy struggling through the deflection loop: it kept re-checking the same Camus and *Abol Tabol* changes across multiple gate passes because it couldn't interpret empty input.

The confidence data is the system's self-assessment: it knows the TASK_ASSERT gate was where it performed worst, and the low EMA rate will inform how aggressively the proxy acts at that gate type in future sessions.

### Proxy behavioral patterns ([proxy-patterns.md](../e2e-raw-files/proxy-patterns.md))

This file is the most revealing artifact. It records the raw dialog between the executing agent (AGENT) and the human proxy (HUMAN) at the TASK_ASSERT gates — and it shows something unexpected.

The executing agent hit timeouts during the gate interactions. When it recovered, it sent empty messages (null input). The proxy, unable to interpret empty input, responded with *"I'm not sure I can answer that right now. Could you rephrase, or let me know your decision?"* — over and over. But the proxy *also* tried to make sense of the pattern. In the third gate interaction, the proxy wrote:

> *"The human has entered three empty/null messages and gotten non-answers each time. The human is likely frustrated at this point and would want the gate to just work."*

The proxy interpreted the timeouts as human annoyance. It read the silence as frustration — *"likely just hitting enter to proceed"* — and tried to model the emotional state of a person who wasn't there. It then attempted to compensate by providing increasingly thorough reviews, reasoning that a frustrated human would want the gate to "just work" by having the proxy handle everything autonomously.

This is both a failure and a success. The failure: the proxy couldn't handle null input and fell into a deflection loop. The success: the proxy's *theory of mind* about the absent human was actually reasonable — if a real person had been hitting enter repeatedly, they probably *would* have been frustrated, and they probably *would* have wanted the proxy to just review the work and approve it. The proxy's instinct to "do the review myself and approve" was correct. Its inability to act on that instinct without first receiving explicit text input was the bug.

The pattern file also shows the proxy recovering: by the fifth and sixth gate interactions, the proxy produced genuinely substantive reviews — checking specific line numbers, comparing `ch7_revised.md` against `ch7_final.md`, confirming the Camus expansion and Hijibijbij addition, evaluating the Ch4 Gottfried rewrite. The quality of the reviews, once the proxy got past the deflection loop, was high. The dialog just shows too many wasted turns getting there.

---

## What This Demonstrates

### CfA Protocol

The state machine guided the session through intent → plan → execution without prescriptive prompts. The agents chose their own transitions: the intent agent decided when it had enough information to write the intent, the planning agent decided how to decompose open questions, the uber team decided how to phase and parallelize execution. The protocol provided *structure* (you must have an approved intent before you plan, you must have an approved plan before you execute) without providing *scripts* (what to ask, what to write, how to organize the work).

### Hierarchical Teams

Eight parallel research teams worked independently in worktrees, coordinated by the uber team, with context compression at hierarchy boundaries. Each sub-team received a scoped brief — not the full session context — and ran its own CfA cycle within that scope. The uber team monitored completion and advanced phases. The same pattern repeated for specification, production, editorial, and verification. The hierarchy scaled to 8+ concurrent dispatches without the uber team becoming a bottleneck.

### Human Proxy

The proxy handled all sub-team assert gates autonomously (`never_escalate=True`), while the top-level gates involved the human. At the intent-assert and plan-assert gates, the proxy approved cleanly. At the task-assert gate — where the editorial and verification findings surfaced real issues — the proxy produced substantive, specific revision notes (own the Camus substitution, add an *Abol Tabol* example, fix the Gottfried overlap).

The proxy's dialog handling at the task-assert gates was the session's most visible failure — but this was a cold start with no prior interaction history. The proxy was already improving within the session, and the learning infrastructure (confidence model, behavioral patterns, interaction history) is in place to support improvement across sessions.

### Learning System

The learning system extracted seven procedural observations, built a per-gate-type confidence model, and recorded behavioral patterns — all automatically, as part of session execution. The observations identified real gaps (missing quality gates, implicit phase-boundary semantics, rate-limit blindness) and converted them into explicit questions for the next session's intent-gathering phase. The system is designed to get smarter with each session; this session is the baseline.

---

## Opportunities for Improvement

**Proxy dialog at approval gates.** The repeated deflections at task-assert gates need attention. The proxy should handle null/empty input gracefully. That said, this was a cold start — the [proxy-confidence.json](../e2e-raw-files/proxy-confidence.json) data shows the proxy building a model over the course of the session. Whether this improves with accumulated experience remains to be seen. The learning infrastructure is in place; this session is the baseline, not necessarily the ceiling.

**Phase boundary semantics.** The plan defined strict sequential phases but reality required overlapping them. The orchestrator should support explicit flexibility semantics: "all-but-one complete" as a valid phase transition trigger.

**Rate-limit-aware scheduling.** Dispatching eight research tracks simultaneously into a rate-limited provider was predictable and avoidable. The dispatch layer should support staggered launch or automatic retry with backoff.

**Cross-chapter consistency.** The editorial reports identified redundancies (Gottfried in Ch4+5, Davila Ross in Ch1+2) that are natural consequences of parallel chapter drafting. A cross-chapter consistency pass would catch these earlier than the editorial phase.

**Word count targets vs. editorial cuts.** Ch2 and Ch4 were already below the 7,000-word floor before editorial cuts were applied. Targets should either flex explicitly or account for expected cuts.

---

## Assessment

The session demonstrated that the TeaParty orchestrator can take a short natural-language prompt and produce a complex, multi-phase creative artifact with genuine intellectual substance — not a summary, not a skeleton, but a manuscript that editorial reviewers engaged with as a manuscript. The CfA protocol maintained coherence from a four-sentence prompt through five execution phases without losing the thread. The hierarchical dispatch model scaled to eight parallel tracks. The revision loop from editorial finding to gate feedback to targeted revision to verification worked end to end.

The weaknesses are real but tractable: proxy dialog handling at gates, phase-boundary flexibility, rate-limit-aware scheduling, and cross-chapter consistency enforcement. None of these are architectural — they are refinements to a pipeline that functionally worked.

The manuscript itself is not a published book. It is a first draft that two independent editorial passes rated as ready for final edits, with specific, actionable revision notes. For a system that started with four sentences and no human involvement beyond six brief dialog turns and a handful of gate approvals, that is a meaningful result.

The places where it stumbled — the proxy deflection loops, the restart friction, the rate-limit collisions — are the places where the design meets the real world. Those are the next things to fix.
