# Hierarchical Agent Teams

Hierarchical agent teams are TeaParty's structural solution to context rot — the degradation of earlier instructions in long multi-step tasks, where the model begins optimizing for recent context at the expense of the original intent. This is the third pillar of TeaParty's four-pillar framework: where intent engineering establishes what to do and the learning system preserves what was learned, hierarchical teams ensure each agent works within a context bounded by what is relevant to its role.

## Why This Exists

A single flat team trying to plan a project and write every file will eventually lose coherence. The twentieth revision of a plan buries the original intent. Cross-workgroup coordination details crowd out the task at hand. File contents from one workstream dilute the context needed for another. This is not a prompting failure — it is a structural one. No instruction can prevent a context window from filling up, and once it does, the model's attention shifts toward whatever is most recent, not whatever is most important.

The standard mitigations — summarization, truncation, retrieval — trade one problem for another. Summarization loses detail that may be critical. Truncation discards history that may be needed. Retrieval introduces noise from irrelevant matches. All three treat the symptom (too much context) rather than the cause (too much responsibility in a single agent).

The structural fix is to scope each agent's responsibility so that its context window contains only what is relevant to its work. This requires a hard boundary — not a prompt instruction that can be overridden or forgotten, but a process boundary that physically separates one team's context from another's.

## The Structural Insight

Each level of the work hierarchy runs as an independent process with its own context window. Levels are bridged by **liaison agents** — lightweight teammates in the upper team whose sole function is to communicate with a separate lower team, relaying tasks downward and results upward.

A process boundary is a hard guarantee; a prompt instruction is not. No agent can see the internal reasoning of any other team, because no agent shares a process with any other team. Context isolation is achieved structurally, not by filtering or instruction.

```
Engagement Team
  org lead + liaison(s)
    |
    +-- Project Team
    |     org lead + workgroup liaison(s)
    |       |
    |       +-- Job Team (workgroup agents)
    |       +-- Job Team (workgroup agents)
    |
    +-- Job Team (direct dispatch)
```

Not every engagement spawns projects. Simple work can be dispatched directly as jobs. Similarly, not every project comes from an engagement — the org lead can create projects from internal requests.

## Context Compression at Boundaries

The liaison's job is communication relay — it does not write code, make architectural decisions, or produce deliverables. This narrowness is the point. Each liaison compresses context at the boundary between levels:

**Downward**, the liaison translates the upper team's high-level task into a scoped task description. The sub-team receives only what it needs — no project-level planning discussions, no other workgroups' details, no engagement negotiation history.

**Upward**, the liaison summarizes the sub-team's output. The upper team sees the result, not the sub-team's internal deliberation.

Each hop compresses. The engagement team sees project-level status summaries, not job-level agent discussions. The project team sees job results, not workgroup internal file changes. The job team sees its task description, not cross-workgroup coordination. This is **hierarchical compaction**: each level compacts independently, and the compression cascades upward through liaison summaries.

| Level | Context contains | Context does NOT contain |
|-------|-----------------|------------------------|
| Engagement team | Engagement scope, partner communication, project-level status summaries | Internal project deliberations, job-level details, workgroup internal discussions |
| Project team | Project scope, cross-workgroup coordination, job result summaries | Job-level agent discussions, workgroup internal file changes, engagement negotiation history |
| Job team | Job task description, workgroup files, workgroup workflows | Project-level coordination, other workgroups' work, engagement details |

## The Scoping-Blindness Tradeoff

Context isolation solves context rot but creates a new problem: **context blindness**. A scoped agent cannot see the organizational knowledge — values, conventions, working agreements — that should inform its work. The engineering team doesn't see the design team's style guide. The job team doesn't see the project's coordination norms. Each agent works in a clean context that is also an uninformed one.

This is the gap the [learning system](learning-system.md) exists to bridge. Institutional learnings — the organization's norms and conventions — are injected into each agent's context at the appropriate scope level. Task learnings from prior work are fuzzy-retrieved based on the current task. The scoping boundary keeps irrelevant context out; the learning system gets relevant context back in. Neither mechanism works without the other: scoping without retrieval creates drift, retrieval without scoping creates rot.

## Workspace Isolation

Each job gets an isolated workspace — a git worktree branched from the workgroup's main branch or virtual files materialized to a temporary directory. Multiple jobs within a project can modify the same files without clobbering each other. Completed jobs merge their changes back.

The project team has access to shared coordination artifacts (plans, status, cross-workgroup documents) but not to job workspaces — results flow up through liaisons. For engagement teams, visibility is contract-based: deliverables are visible to both parties; internal workspaces are restricted to the target organization.

Files move upward through explicit actions (merge, copy, relay), never through shared access.

## When Hierarchical Structure Is Warranted

This architecture is justified when:
- The work decomposes into two or more semi-independent workstreams.
- Each workstream is complex enough to benefit from its own multi-agent team.
- The total expected work would cause context rot in a single flat team.

For simpler work, the hierarchy flattens naturally. A single workgroup handling a single job needs no project team and no liaisons. Multiple sequential jobs from one workgroup need only the org lead dispatching them one at a time. Cross-workgroup work that is simple enough to fit in a single context window can use a lightweight project team where each job team may be a single agent rather than a full team.

The overhead of the liaison layer is justified by the context isolation it provides. For work that fits in a single context window, skip it.

## Relationship to Other Pillars

**[Intent engineering](intent-engineering.md)** produces the governing document that flows down through the hierarchy. The intent is established at the top level; each liaison carries a scoped version of it to its sub-team. The further down the hierarchy, the more specific and narrow the intent becomes — but it must remain traceable to the original.

**[Strategic planning](strategic-planning.md)** determines the shape of the hierarchy for each engagement. The decomposition into workstreams, the decision authority mapping, and the parallelization strategy directly determine how many teams are needed, what each team's scope is, and what coordination the liaison layer must handle.

**[Learning system](learning-system.md)** bridges the gap that scoping creates. Without learning, scoped agents lose access to organizational knowledge. Institutional learnings are always loaded at matching scope; task learnings are fuzzy-retrieved. The promotion chain moves validated learnings upward through the same hierarchy that teams operate in.

**[Human proxies](human-proxies.md)** operate at each level of the hierarchy. The proxy's confidence model tracks state-task pairs per scope — the human may grant full autonomy for job-level plan approvals while retaining oversight for project-level strategic decisions.

## Open Questions

**Liaison intelligence.** The current design treats liaisons as pure communication relays. But the compression they perform — scoping a high-level task into a job description, summarizing a sub-team's output into a project-level result — requires judgment. How much intelligence should liaisons have? Too little and the compression is lossy in the wrong places. Too much and the liaison becomes a decision-maker that the upper team cannot see into.

**Dynamic team assembly.** The hierarchy is currently assembled at planning time and fixed for the duration of execution. Work that discovers new workstreams mid-execution — a common pattern — must either stretch an existing team's scope or backtrack to replanning. Dynamic team assembly would allow the hierarchy to grow as the work reveals its true structure, but adds complexity to coordination and context management.

**Cross-team learning.** When two job teams working on related tasks independently discover the same insight, neither knows the other exists. The learning system captures these insights retrospectively through promotion, but in-flight cross-pollination — routing a learning from one active team to another — is not addressed.

**Intra-team communication topology.** The current design assumes hub-and-spoke communication within a team: the team lead coordinates, and all meaningful communication flows through them. The alternative — star topology, where any agent can communicate directly with any other teammate — reduces coordination bottleneck but risks context fragmentation, as side conversations between agents produce context that the lead (and therefore the liaison above) never sees. The right topology likely varies by team size and task type: small teams doing tightly coupled work benefit from star; larger teams doing decomposed work benefit from hub-and-spoke. How to choose, and whether to allow dynamic switching mid-task, is unresolved.
