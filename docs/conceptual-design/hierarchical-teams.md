# Hierarchical Agent Teams

Hierarchical agent teams are TeaParty's structural solution to context rot — the degradation of earlier instructions in long multi-step tasks, where the model begins optimizing for recent context at the expense of the original intent. This is the third pillar of TeaParty's four-pillar framework: where intent engineering establishes what to do and the learning system preserves what was learned, hierarchical teams ensure each agent works within a context bounded by what is relevant to its role.

## Why This Exists

A single flat team trying to plan a project and write every file will eventually lose coherence. The twentieth revision of a plan buries the original intent. Cross-workgroup coordination details crowd out the task at hand. File contents from one workstream dilute the context needed for another. This is not a prompting failure — it is a structural one. No instruction can prevent a context window from filling up, and once it does, the model's attention shifts toward whatever is most recent, not whatever is most important.

The standard mitigations — summarization, truncation, retrieval — trade one problem for another. Summarization loses detail that may be critical. Truncation discards history that may be needed. Retrieval introduces noise from irrelevant matches. All three treat the symptom (too much context) rather than the cause (too much responsibility in a single agent).

The structural fix is to scope each agent's responsibility so that its context window contains only what is relevant to its work. This requires a hard boundary — not a prompt instruction that can be overridden or forgotten, but a process boundary that physically separates one agent's context from another's.

## The Structural Insight

Each level of the work hierarchy runs as an independent process with its own context window. Levels are bridged by the [message bus](messaging.md) — agents communicate via Send/Reply, composing the message content at each boundary to control exactly what context flows between levels.

A process boundary is a hard guarantee; a prompt instruction is not. No agent can see the internal reasoning of any agent at another level, because each agent runs as an independent `claude -p` process. Context isolation is achieved structurally, not by filtering or instruction.

```
Office Manager
  |
  +-- Project Manager (one per project)
  |     |
  |     +-- Project Lead
  |     |     +-- Workgroup agents (via Send)
  |     |     +-- Workgroup agents
  |     |
  |     +-- Configuration Lead (project)
  |
  +-- Configuration Lead (management)
  |
  +-- Proxy
```

Not every task requires the full hierarchy. Simple work dispatched by the OM to a PM may go directly to a single agent. The hierarchy flattens naturally when the work is simple.

## Context Compression at Boundaries

When an agent Sends a message to another agent, the sender composes the message content. This is where context compression happens — the sender decides what information the recipient needs, stripping away internal deliberation, coordination history, and irrelevant detail.

**Downward**, a lead agent translates high-level coordination into a scoped task description. The recipient receives only what it needs — no project-level planning discussions, no other workgroups' details, no management-level coordination history.

**Upward**, the result flows back via Reply. The reply contains the outcome, not the recipient's internal reasoning.

Each hop compresses. The OM sees project-level status summaries, not job-level agent discussions. The PM sees project lead results, not workgroup internal file changes. The workgroup agent sees its task description, not cross-workgroup coordination. This is **hierarchical compaction**: each level compacts independently, and the compression cascades through Send/Reply messages.

| Level | Context contains | Context does NOT contain |
|-------|-----------------|------------------------|
| Office Manager | Cross-project coordination, human preferences, steering | Internal project work, workgroup details |
| Project Manager | Project scope, lead coordination | Workgroup internal discussions, other projects |
| Project Lead | Project tasks, workgroup dispatch | Management coordination, other projects |
| Workgroup agent | Task description, workgroup files | Project-level coordination, other workgroups' work |

## The Scoping-Blindness Tradeoff

Context isolation solves context rot but creates a new problem: **context blindness**. A scoped agent cannot see the organizational knowledge — values, conventions, working agreements — that should inform its work. The engineering team doesn't see the design team's style guide. The workgroup agent doesn't see the project's coordination norms. Each agent works in a clean context that is also an uninformed one.

This is the gap the [learning system](learning-system.md) exists to bridge. Institutional learnings — the organization's norms and conventions — are injected into each agent's context at the appropriate scope level. Task learnings from prior work are fuzzy-retrieved based on the current task. The scoping boundary keeps irrelevant context out; the learning system gets relevant context back in. Neither mechanism works without the other: scoping without retrieval creates drift, retrieval without scoping creates rot.

## Workspace Isolation

Each session gets its own isolated workspace — a git worktree with a 1:1:1 correspondence between sessions, worktrees, and Claude session IDs. Cold start creates both; `--resume` reuses both; CloseConversation cleans up both.

Jobs and tasks use a hierarchical worktree layout under `{project}/.teaparty/jobs/`. Task branches fork from the job branch; the lead merges them back sequentially, resolving conflicts with context. Multiple tasks within a job can modify the same files without clobbering each other.

Files move upward through explicit actions (merge, Reply), never through shared access. See [Folder Structure](../reference/folder-structure.md) for the complete directory layout.

## When Hierarchical Structure Is Warranted

This architecture is justified when:
- The work decomposes into two or more semi-independent workstreams.
- Each workstream is complex enough to benefit from its own agent.
- The total expected work would cause context rot in a single flat session.

For simpler work, the hierarchy flattens naturally. A single agent handling a single task needs no project lead or PM. Multiple sequential tasks from one workgroup need only the project lead dispatching them one at a time. Cross-workgroup work that is simple enough to fit in a single context window can use a lightweight project team where each task may be a single agent rather than a full team.

The overhead of the hierarchical dispatch is justified by the context isolation it provides. For work that fits in a single context window, skip it.

## Relationship to Other Pillars

**[Intent engineering](intent-engineering.md)** produces the governing document that flows down through the hierarchy. The intent is established at the top level; each Send carries a scoped version of it to the recipient. The further down the hierarchy, the more specific and narrow the intent becomes — but it must remain traceable to the original.

**[Strategic planning](strategic-planning.md)** determines the shape of the hierarchy for each piece of work. The decomposition into workstreams, the decision authority mapping, and the parallelization strategy directly determine how many levels are needed, what each agent's scope is, and what coordination the dispatch must handle.

**[Learning system](learning-system.md)** bridges the gap that scoping creates. Without learning, scoped agents lose access to organizational knowledge. Institutional learnings are always loaded at matching scope; task learnings are fuzzy-retrieved. The promotion chain moves validated learnings upward through the same hierarchy that teams operate in.

**[Human proxies](human-proxies.md)** operate at each level of the hierarchy, differentiated by D-A-I role. Each team has a **Decider** (exactly one, authoritative), optional **Advisors** (advisory input), and optional **Informed** participants (status recipients). The proxy stands in for the decider at each level — and the decider at the project level may be a different human than the decider at the workgroup level. The proxy's confidence model tracks state-task pairs per scope, so the human may grant full autonomy for job-level plan approvals while retaining oversight for project-level strategic decisions. See [team-configuration.md](team-configuration.md) for how D-A-I roles are assigned.

## Open Questions

**Dynamic team assembly.** The hierarchy is currently assembled at planning time and fixed for the duration of execution. Work that discovers new workstreams mid-execution — a common pattern — must either stretch an existing agent's scope or backtrack to replanning. Dynamic team assembly would allow the hierarchy to grow as the work reveals its true structure, but adds complexity to coordination and context management.

**Cross-team learning.** When two agents working on related tasks independently discover the same insight, neither knows the other exists. The learning system captures these insights retrospectively through promotion, but in-flight cross-pollination — routing a learning from one active agent to another — is not addressed.

**Compression quality.** Context compression happens at the Send boundary — the sender decides what to include. Too little and the recipient lacks critical information. Too much and the context isolation benefit is lost. The right compression depends on the task type and the recipient's needs. How to guide agents toward good compression without prescriptive rules is unresolved.
