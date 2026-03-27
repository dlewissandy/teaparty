# Participation Model

## Human Seats at Every Level

Humans occupy a position at each level of the team hierarchy. At some levels they participate directly. At others, the proxy stands in for them. The human can move between levels at will.

```
Office Manager Team
+-- Human (direct participant)
+-- Office Manager (team lead)
|
+-- Project: POC
|   +-- Human (direct participant OR proxy)
|   +-- Project Lead
|   |
|   +-- Subteam: Coding
|   |   +-- Proxy (stands in for human)
|   |   +-- Coding agents
|   |
|   +-- Subteam: Writing
|       +-- Proxy (stands in for human)
|       +-- Writing agents
|
+-- Project: Joke-book
    +-- Proxy (stands in for human)
    +-- Project Lead
    +-- ...
```

The proxy is a single logical entity per human. It has one memory, one interaction counter, one personality model. The multiple seats in the diagram are roles, not instances. It is instantiated per-level as needed, but all instantiations share the same memory database.

The orchestrator serializes proxy invocations through a FIFO queue. When a coding subteam gate and a writing subteam gate arrive at the same time, the orchestrator invokes the proxy for one gate, waits for completion, then invokes for the next. This serialization means only one proxy instance writes at a time, which makes WAL's single-writer serialization sufficient for the shared memory database.

**At the office manager level**, the human always participates directly. This is their coordination layer, where they steer priorities, ask cross-cutting questions, and decide what gets worked on.

**At the project level**, the human chooses. They can sit in on a project session and participate directly (reviewing artifacts, answering questions, providing corrections), or they can let the proxy handle it. When the human shows up, they take their own seat. When they leave, the proxy resumes.

**At the subteam level**, the proxy almost always stands in. The human cannot attend every subteam meeting. But they can drop in if they want to.

## How the Proxy and Human Interact

The proxy always handles gate mechanics: prediction, confidence scoring, escalation decisions, learning signal recording. This is true regardless of whether the human is present. Even when a human responds to a proxy escalation, that is the proxy handling the gate with human input, not the human bypassing the proxy. The proxy records every human response as a learning signal.

The flow:

1. **Proxy generates a prediction** via a two-pass assessment (prior without artifact, posterior with artifact), producing a prediction, confidence score, and salient percepts.
2. **If confident**, the proxy acts autonomously. No escalation.
3. **If not confident**, the proxy escalates to the human via the job or task chat. The escalation sits in the chat until the human responds. The dashboard shows an escalation badge.
4. **Human responds** and the proxy records the interaction immediately: EMA outcome (approve/correct/reject), ACT-R memory chunk with prior prediction, posterior prediction, human response, prediction delta, and 5D embeddings. Learning is synchronous, not retrospective.
5. **Human intervenes unsolicited** by typing in the chat at any time (INTERVENE). The lead reassesses. The proxy records this as a learning signal.

The human does not need to be "present" in any special sense. They respond to escalations when available. If they are away, the escalation waits.

The proxy's confidence threshold serves a dual purpose: it controls proxy accuracy (higher threshold means fewer mistakes) and human cognitive load (higher threshold means fewer escalations). These are the same dial. If the proxy is escalating too frequently, either the threshold is too low or the proxy has genuinely low confidence and the human needs to provide more input during the learning phase.

## What the Human Experiences

The human talks to whoever is in front of them -- office manager or project gate -- and learning propagates across channels through the shared memory pool. Steering given to the office manager surfaces in proxy gate decisions; corrections at gates surface in office manager status reports. For worked examples of this cross-pollination, see [office-manager: Relationship to the Proxy](../office-manager/proposal.md#relationship-to-the-proxy).

## Cold Start

On first use, there is no memory at any level. The proxy has no chunks and escalates everything to the human. The office manager has no chunks and starts every conversation from scratch.

The human's first interactions seed the memory. A few steering directives to the office manager, a few gate corrections at the project level, and the system has enough to start connecting dots. By the end of the first session, the proxy has a rough picture. By the third, it is anticipating concerns.

## Evaluation Criteria

| Metric | What it measures |
|--------|-----------------|
| Proxy prediction accuracy | Fraction of autonomous gate decisions the human would have agreed with |
| Escalation rate over time | Whether escalation frequency decreases as the proxy learns |
| Cross-channel retrieval rate | Whether steering chunks from the office manager surface in proxy gate retrievals |
| Cold start convergence | How many interactions before the proxy reaches a target accuracy threshold |
