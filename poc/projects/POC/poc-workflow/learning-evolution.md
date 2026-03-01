# Learning Evolution: Beyond Retrospective Extraction

## The Four Moments of Learning

Every session the workflow completes produces a retrospective extraction: what happened, what worked, what to carry forward. This is treated as the learning moment. It is, in fact, the least valuable of four distinct moments when learning can occur — and the only one the system currently captures.

The four moments are these. Prospective learning happens before execution begins: what do we already know that applies here? In-flight learning happens at each major milestone: what is the work telling us about our assumptions? Corrective learning happens at the moment a mismatch is discovered: not what happened, but what upstream assumption failed to predict it? Retrospective learning happens after completion: what should we carry into future sessions?

The retrospective is structurally impoverished because it is retrospective. By the time learnings are extracted, the opportunity to act on them within the session has closed. The most expensive failures — the ones where the approach was wrong, the scope was misread, the user's intent was misunderstood from the start — are failures that could have been prevented or corrected mid-stream. Extracting a learning from them after the fact creates knowledge that might prevent the same failure next time, but does nothing for the session in which it was discovered. The other three moments are not supplements to retrospective learning; they are the mechanisms by which learning becomes immediately actionable.

---

## Prospective Learning in Practice

The spec already includes warm-start memory retrieval as part of intent capture, and this is correctly understood as prospective learning. But the scope is too narrow. Currently, warm-start retrieval surfaces user preferences — communication style, formatting norms, granularity expectations. These are real and worth loading. They are also the least structurally significant category of prior knowledge to bring to a new session.

What is missing is project-level pattern retrieval, domain-level constraint retrieval, and known failure mode retrieval. Before beginning a session involving architectural changes to the workflow, the system should surface not just how the user likes to receive information but what the last three architectural changes revealed about coupling risks, what domain constraints have proven sticky, and what category of failure has recurred. The question before starting is not only "how should I communicate?" but "what do I already know that makes this task easier or safer?"

The pre-mortem is the canonical mechanism for prospective learning and it belongs in the workflow. Before execution begins, name the two or three most likely ways this task fails. This is not speculative pessimism — it is a disciplined application of prior knowledge. A pre-mortem takes five minutes and forces the system to surface relevant failure modes before they can manifest. The objection that pre-mortems slow planning inverts the cost structure: a five-minute pre-mortem that prevents a mid-session direction change saves hours. The spec's 0.7 confidence threshold for pre-populating elements is the right mechanism for this. The threshold should gate not just preference retrieval but failure-mode retrieval, and the scope of what counts as a retrievable learning needs to expand accordingly.

---

## In-flight Learning

A session is not a monolithic unit of work. It proceeds through milestones, and each milestone is an observation point. If step one took three times longer than the estimate implied, the estimates for the remaining steps need revision — not at retrospective extraction, but now, before committing to the same planning assumptions for what follows.

The more consequential in-flight signal is an approach assumption that has not proven out by midpoint. If the session began assuming a certain decomposition was tractable and two steps in the evidence contradicts that assumption, the correct moment to flag it is before the third step, not after delivery. In-flight corrections are cheaper than post-delivery corrections by an order of magnitude. This is not a novel observation about software development — it is the foundational argument for iterative process design — but the workflow has no mechanism to implement it. Sessions execute, milestones complete, and the model that was constructed at the start of the session persists unchanged regardless of what the work reveals.

The proposed fix is simple: milestone completion events include a brief model-update note. This note is not a full retrospective; it is a one or two sentence update on whether the working assumptions are holding. Does the actual complexity match the estimated complexity? Has an assumption been confirmed or disconfirmed? This note flows into the session log and becomes available both for mid-session recalibration and for retrospective extraction. The cost is negligible. The value is that in-flight learning stops being invisible to the system.

---

## Corrective Learning

When a mismatch occurs — an escalation, a direction change, a significant replan — the current system records what happened. This is insufficient. The learning that matters is not the surface description of the mismatch but the upstream assumption that caused it.

The escalation calibration model already applies -0.10 adjustments for negative signals. This mechanism should be extended to intent misalignments, with an explicit causal structure: "we misread the user's intent on X because we assumed Y; Y should now carry lower confidence in contexts resembling this one." The delta between prediction and reality is the learning, not the reality itself. A system that records "the user wanted a shorter deliverable" has less to work with than a system that records "we assumed the user was in detailed-design mode; the actual mode was quick-review; confidence in detailed-design assumption should be lower when the session was explicitly marked as a review."

Corrective learnings should carry the highest weight in the memory schema, above both prospective pattern retrieval and retrospective learnings. This is because they are direct evidence of a model error — not inference from patterns, not extrapolation from past sessions, but a falsified prediction in the current one. The moment of correction is also when memory is most writable: the gap between what was predicted and what was actually required is maximally salient, and the causal chain leading to the error is still recoverable. An hour later it begins to fade. At retrospective extraction, it may be rationalized into a softer form that loses the specific assumption that failed.

---

## Confidence-Weighted Memory

The spec specifies retrieval thresholds of 0.7 and 0.4, which implies that confidence is a static property of a stored learning. It is not. Confidence should decay without reinforcement and renew with repeated confirmation.

There is a real difference between "we learned X six months ago and have not encountered a context that either confirmed or contradicted it since" and "we observed X confirmed in four of the last five relevant sessions." Both might sit at the same stored confidence value; they should not. Temporal decay is a necessary property of any memory system that claims to be calibrated rather than merely archival. A learning about a user's preference for a particular document structure, confirmed last week, should be surfaced at higher confidence than the same learning confirmed only once a year ago.

Equally important is conditional applicability. Learnings should carry context about the conditions under which they apply. "User prefers concise prose" is less useful than "user prefers concise prose in review-mode sessions; in design sessions they want full analytical development." A learning stripped of its applicability context will be misapplied to sessions where it does not hold, producing the opposite of the intended effect. The schema needs a condition field, and retrieval logic needs to match stored conditions against the current session context before surfacing a learning.

---

## The Calibration Problem

There is a question the system cannot currently answer: are we getting better at estimating? Retrospective learnings are qualitative observations about what worked and what did not. They do not produce a feedback loop on estimation quality.

Every session involves predictions — about complexity, duration, turn count, number of escalations. Every session produces actuals. The gap between prediction and actual is the signal that, accumulated across sessions, calibrates planning heuristics. Currently, this signal is not captured. Each session begins with the same estimation priors regardless of whether the last twenty sessions showed systematic underestimation of a particular task type.

The fix requires a calibration record type in the memory schema. After each session, `summarize_session.py` should extract predicted versus actual pairs alongside qualitative learnings: estimated complexity versus actual complexity per work stream, estimated turn count versus actual, number of anticipated escalations versus actual. These records are not useful in isolation. Across ten or more sessions they reveal systematic biases — the kind of bias that, once identified, can be corrected with a simple prior adjustment rather than continued reliance on intuition that has consistently misfired.

---

## Implications for the Workflow

The argument above maps cleanly onto specific changes to four points in the workflow.

Prospective learning changes `intent.sh` and the entry behavior of `plan-execute.sh`. Before intent capture completes, the system loads and surfaces relevant memory: not just user preferences but project patterns, domain constraints, and known failure modes above the 0.7 confidence threshold. A pre-mortem prompt is added to the planning phase.

In-flight learning changes execution milestone handling in `plan-execute.sh`. Each checkpoint event generates a brief model-update note — assumption status, complexity delta — that is appended to the session log and flagged for retrospective extraction.

Corrective learning changes escalation handling. Escalation events trigger a root-cause extraction step: what assumption failed, not just what occurred. The output is a structured corrective learning record with causal attribution, weighted above standard retrospective learnings in the memory schema.

Calibration changes `summarize_session.py`. Alongside qualitative learning extraction, the script extracts prediction-versus-actual pairs for complexity, duration, and escalation count, writing them to a calibration record that accumulates across sessions.

Each of these changes is targeted and bounded. None requires a redesign of the workflow — they are additions to existing event boundaries. The cost of implementation is low; the cost of continued absence is the system perpetually leaving the three most actionable learning moments uncaptured.
