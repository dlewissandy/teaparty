# Participation Model

## Human Seats at Every Level

Humans occupy a position at each level of the team hierarchy. At some levels they participate directly. At others, the proxy stands in for them. The human can move between levels at will.

```
Office Manager Team
├── Human (direct participant)
├── Office Manager (team lead)
│
├── Project: POC
│   ├── Human (direct participant OR proxy)
│   ├── Project Lead
│   │
│   ├── Subteam: Coding
│   │   ├── Proxy (stands in for human)
│   │   └── Coding agents
│   │
│   └── Subteam: Writing
│       ├── Proxy (stands in for human)
│       └── Writing agents
│
└── Project: Joke-book
    ├── Proxy (stands in for human)
    ├── Project Lead
    └── ...
```

The proxy is a single logical entity per human. It has one memory, one interaction counter, one personality model. The multiple seats in the diagram are roles, not instances. When a coding subteam gate and a writing subteam gate arrive at the same time, the proxy processes them sequentially through a FIFO queue. It is instantiated per-level as needed, but all instantiations share the same memory database.

**At the office manager level**, the human always participates directly. This is their coordination layer, where they steer priorities, ask cross-cutting questions, and decide what gets worked on.

**At the project level**, the human chooses. They can sit in on a project session and participate directly (reviewing artifacts, answering questions, providing corrections), or they can let the proxy handle it. When the human shows up, they take their own seat. When they leave, the proxy resumes.

**At the subteam level**, the proxy almost always stands in. The human can't attend every subteam meeting. But they can drop in if they want to.

## How the Proxy and Human Interact

The proxy always handles gates. There is no "presence detection" or "stepping aside." The flow is:

1. **Proxy generates a prediction** — a two-pass assessment (prior without artifact, posterior with artifact) producing a prediction, confidence score, and salient percepts.
2. **If confident** — the proxy acts autonomously. No escalation.
3. **If not confident** — the proxy escalates to the human via the job or task chat. The escalation sits in the chat until the human responds. The dashboard shows an escalation badge.
4. **Human responds** — the proxy records the interaction immediately: EMA outcome (approve/correct/reject), ACT-R memory chunk with prior prediction, posterior prediction, human response, prediction delta, and 5D embeddings. Learning is synchronous, not retrospective.
5. **Human intervenes unsolicited** — the human types in the chat at any time (INTERVENE). The lead reassesses. The proxy records this as a learning signal.

The human doesn't need to be "present" in any special sense. They respond to escalations when they're available. If they're away, the escalation waits. This is the same model whether the human is actively watching or checking in hours later.

## What the Human Experiences

From the human's perspective, the system remembers what they care about regardless of which level they said it at.

The human tells the office manager they're concerned about security. A week later, at a project gate, the proxy asks pointed questions about the security implications of the plan. The human didn't repeat their concern — the steering chunk surfaced in retrieval because the semantic match was strong. Or: the human corrects three plans for missing tests. The next time they check in with the office manager, it mentions that test coverage has been a recurring theme. Nobody programmed that report. The correction chunks accumulated and the office manager's retrieval picked them up.

The human talks to whoever is in front of them, and the system propagates what it learned. This works because the shared memory pool uses activation-based retrieval, not explicit routing.

## Cold Start

On first use, there is no memory at any level. The proxy has no chunks and escalates everything to the human. The office manager has no chunks and starts every conversation from scratch.

The human's first interactions seed the memory. A few steering directives to the office manager, a few gate corrections at the project level, and the system has enough to start connecting dots. By the end of the first session, the proxy has a rough picture. By the third, it's anticipating concerns.
