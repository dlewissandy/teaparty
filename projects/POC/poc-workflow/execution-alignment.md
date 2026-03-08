# Execution Alignment: Staying True While Moving Fast

## The Letter vs. Spirit Problem

An agent can technically complete every task in the plan and still deliver something the user does not want. This is not a failure of effort or competence — it is a failure of alignment, and it is the most dangerous kind because it is invisible until the end.

The plan is a decomposition of intent, not a substitute for it. When intent is translated into a task list, something is always lost in compression. The task list captures what was anticipated, not everything that was meant. Executing faithfully against the task list while losing touch with the original intent is how you produce work that is technically complete and practically useless.

Consider code that passes every test in the suite but misses the actual use case. The tests were written to verify the specification; the specification was written to capture the intent; the intent was what the user actually needed. Each translation introduced loss. The agent delivered code that satisfies the formal contract while violating the real one. No test fails. Nothing is obviously wrong. The user receives the output, tries to use it, and discovers the problem — at which point significant work is already sunk.

Documentation presents the same failure in a different form. A document can be complete by every formal measure — correct headings, accurate content, appropriate length — while answering questions the reader was not asking. The author verified the content against the specification; the specification did not capture which questions the reader actually needed answered. The document exists. It is accurate. It is useless to the person who needs to act on it.

Reports are the clearest case. A report that fulfills all stated requirements — the right data, the right format, the right sections — can still miss the key insight entirely. The human who requested the report had a purpose behind the request. That purpose generated a set of implicit questions. The report answers the explicit questions and never touches the implicit ones. This only becomes apparent after the human reads it, by which point the work is done and the cost of redirection is high.

What makes this failure mode particularly resistant to correction is the phrase "we did everything we were asked." When the deliverable fails because something was not attempted, the path forward is clear. When the deliverable fails because everything was attempted and completed while missing the point, that failure is structurally protected. The agent has evidence of compliance. The work product exists. The argument that something went wrong requires overcoming the appearance of success.

## Intent Anchors

At each execution milestone, re-read the INTENT.md success criteria and ask a single question: does this output serve the original purpose? The anchor question is not "did I do what the plan says?" It is "would a user who articulated this intent be satisfied with this output?" These are genuinely different questions, and confusing them is how drift becomes invisible.

A milestone is any output handed off to another agent, surfaced to the user, or used as input for the next major step. The category matters because these are the moments where misalignment compounds. An output that drifts slightly becomes input for the next stage, which drifts slightly further, until the final delivery is substantially disconnected from the original intent — with each individual step having been locally reasonable.

In the POC, every relay.sh result returning to the uber lead is an intent anchor moment. The uber lead receiving that result has an obligation that goes beyond checking whether the task completed: it must verify that the output serves the stated intent before routing it forward or treating it as input for the next stage. This is not overhead. Anchors are cheap. Delivering an output that requires rework is not.

The practical implementation is simple: keep INTENT.md accessible throughout execution, not just at the start. Reviewing success criteria at a milestone takes seconds. Discovering at the end that the work satisfied the plan but not the intent costs substantially more than that.

## The Reasonable User Test

Before submitting any deliverable, apply one test: would a reasonable user, having made this request, be satisfied with this output? This is a formal pre-delivery gate for Tier 2 and Tier 3 tasks, not a suggestion. It catches failure modes that internal quality checks miss because internal checks verify the work against the specification, not against the actual need.

The first failure mode this catches is technically correct but practically useless output. The deliverable satisfies every formal criterion and cannot be used. The agent verified correctness; no one verified utility.

The second failure mode is over-engineering — adding what was interesting rather than what was wanted. An agent encountering an under-specified problem has latitude to interpret. That latitude, used without discipline, produces deliverables that are technically impressive and operationally mismatched. The user asked for something direct; they received something elaborate. The additional work was not requested and does not serve the intent; it serves the agent's assessment of what would be better.

The third failure mode is under-contextualization: correct output the reader cannot use. The answer is right. The recipient lacks the context to act on it. This is particularly common when an agent optimizes for accuracy over usability — the output is defensible in isolation but fails in the context of the person who must use it.

"Reasonable user" is not an abstract average person or a generic stakeholder. It is the specific human who made this specific request in this specific context. Applying the test requires holding that person's actual situation in mind — what they know, what they are trying to accomplish, what they will do with the output. A test applied to a generic recipient is not the reasonable user test; it is a weaker version that misses precisely the cases where alignment matters most.

## Partial Delivery as Intent Probing

For tasks of any significant length, intermediate outputs are not just progress indicators — they are opportunities to verify that the approach is working before the full investment is sunk. The discipline here is not to wait for 100% completion before surfacing anything.

The framing that works is: "I've completed X; this is approximately Y% of the work; does this direction look right?" This is not anxious status-checking. It is structured intent verification at a point where the cost of a course correction is still low. The human who receives this is not being asked to do the agent's job — they are being given a low-cost opportunity to redirect before the work is done rather than after.

The effect of this practice is to shift the human from overseer to occasional calibrator. Oversight requires sustained attention; calibration requires periodic attention at specific moments. A human who must monitor continuously to catch drift has high involvement and limited effectiveness. A human who is surfaced with "here is 30% of the work, does this look right?" has lower involvement and higher effectiveness — they engage at decision points rather than throughout execution.

In the POC, the uber lead can request intermediate relay results from liaisons rather than waiting for full completion. This is not micromanagement; it is an explicit mechanism for catching trajectory problems before they become delivery problems. The cost of the request is low. The cost of a fully completed deliverable that must be redone is not.

## Drift Detection Patterns

Three distinct drift patterns appear in execution, each with a different cause and a different signature.

**Scope creep** is doing more than was intended. The agent encountered something interesting in the course of execution, assessed it as relevant, and incorporated it. The individual judgment was often reasonable; the aggregate effect is an output that exceeds the scope of the request in ways the user did not ask for and may not want. The signal of scope creep is not that extra work is present — it is that the agent is optimizing its own judgment about what would be valuable over the user's stated request. The appropriate response to finding something interesting in the course of execution is to note it and deliver what was asked, not to expand the scope unilaterally.

**Gold-plating** is adding quality or features beyond what was requested. The core deliverable is correct; additional work has been layered on top of it in ways that make the overall output over-engineered for the purpose. This is distinct from scope creep because the base request is satisfied — the extra work is genuinely extra. Gold-plating often reflects an agent's preference for thoroughness over fit. Thoroughness is a virtue when the request calls for it; applied beyond the request, it produces outputs that are harder to use and take longer to deliver.

**Interpretation drift** is the hardest pattern to detect because it is the most locally reasonable. Each step in execution makes a judgment call about how to interpret the current task; each individual call is defensible; the cumulative effect is that the work is solving a slightly different problem than the one that was stated. Interpretation drift is only visible when you step back and compare the current trajectory to the original intent — from inside the execution, every step looks correct. This is why intent anchors are not optional: drift of this kind cannot be detected without periodic comparison to the origin.

## When to Escalate vs. Improvise

The decision to escalate versus proceed is not a matter of preference or caution — it is a function of reversibility and cost.

High-cost decisions not anticipated in INTENT.md require escalation without exception. "High-cost" means low reversibility, significant resource investment, or organizational impact beyond the current task. When an execution path leads to a decision of this kind, the agent's obligation is to surface it to the appropriate level before proceeding. This is not a threshold calibrated to domain or agent confidence — it applies universally to irreversible actions.

Low-cost, reversible improvisation that serves intent is different. When an unanticipated situation arises and the resolution is clearly reversible and clearly aligned with intent, proceeding and notifying is the right posture. The notification is not optional — "proceed and note" means both elements are required — but the note is asynchronous; it does not require approval before action.

The default posture is "proceed and note," not "stop and ask," for low-stakes decisions. An agent that over-escalates imposes real costs: it consumes the human's attention on decisions that did not require it, introduces latency into execution, and transfers decision-making to a level that has less context than the executing agent. Anxious over-escalation is not a safe behavior — it is a cost that compounds across every task in every session.

The bright line is irreversibility. Any action that cannot be undone requires explicit approval regardless of how confident the agent is in the alignment of the decision. Reversible decisions with clear intent alignment do not.
