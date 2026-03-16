# Learnings

The session produced three learning artifacts that show the system observing itself and extracting procedural knowledge for future sessions.

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

