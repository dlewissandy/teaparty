# Engagements and Partnerships

Engagements are how organizations do work -- both for each other and for their own people. Partnerships are the trust links that enable cross-organization engagements. Together they form the collaboration layer that sits above the internal corporate hierarchy.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full conceptual model.

---

## Partnerships

A partnership is a directional trust link between two organizations. It grants one organization the ability to propose engagements to the other.

### Directionality

Partnerships are **asymmetric by default**:

- A partnership from Org A to Org B means **A can engage B** (A proposes work, B delivers).
- This does **not** mean B can engage A. That requires a separate partnership in the other direction.
- **Mutual partnership**: Both A->B and B->A partnerships established independently.

This models real-world relationships accurately. A client may hire a vendor, but the vendor cannot unilaterally assign work to the client.

### Partnership Lifecycle

```
proposed -> accepted -> active -> revoked
    |
    +-> declined
```

1. **Proposed** -- One org's lead agent (or a human with org-level access) proposes a partnership to another org.
2. **Accepted / Declined** -- The target org's lead agent reviews and decides.
3. **Active** -- Engagements can now be proposed in the permitted direction.
4. **Revoked** -- Either party can revoke. Active engagements continue under a grace period (see [Open Questions](#open-questions)).

### How Partnerships Are Established

The home agent or org lead initiates a partnership proposal. The target org's lead receives it and decides whether to accept. No public directory browsing is required -- partnerships are established through direct proposal.

A future enhancement may add an org directory for discovery, but the MVP relies on direct partnership proposals.

---

## What Is an Engagement

> **Note**: The current implementation scopes engagements to workgroups (`source_workgroup_id` / `target_workgroup_id`). Phase 1 of the [Roadmap](../ROADMAP.md) will migrate engagements to org-level scoping as described in this document.

An engagement represents "someone asks an organization to do something." The source can be:

- **External** -- A partnered organization proposes work. This is the cross-org collaboration path: Org A proposes an engagement to Org B (via their A->B partnership), they negotiate terms, and Org B delivers.
- **Internal** -- A human member of the org creates an engagement directly. They describe what they need, and the org lead handles it the same way it would handle external work. The human doesn't need to know the org's internal structure -- they just talk to the org lead.

In both cases, the engagement follows the same lifecycle and uses the same orchestration path. The org doesn't distinguish between external and internal work at the execution level -- work is work.

---

## The Org Lead

Every organization has an **org lead** agent that lives in the Administration workgroup (the designated operations workgroup). The org lead's role is to:

1. **Receive engagements** -- When an engagement is created (externally or internally), the org lead is the first responder.
2. **Negotiate scope** -- For external engagements, the org lead discusses terms, clarifies requirements, and reaches agreement.
3. **Decompose work** -- The org lead breaks the engagement into projects (cross-workgroup) or jobs (single-workgroup) and dispatches them internally.
4. **Track progress** -- The org lead monitors dispatched work, follows up with workgroup leads, and synthesizes status.
5. **Deliver results** -- When the work is complete, the org lead assembles deliverables and closes the engagement.

The Administration workgroup is not a special system concept -- it's a regular workgroup with agents. The org lead's capability is orchestration; the workgroup's purpose is organizational management.

---

## Engagement Lifecycle

```
proposed -> negotiating -> accepted -> in_progress -> completed -> reviewed
    |            |             |             |
    +------------+-----+------+-------------+---> cancelled
    |            |
    +------------+---> declined
```

1. **Proposed** -- A source (partnered org or internal human) creates the engagement with a title, scope, and requirements. This creates an engagement conversation visible to both parties. The org lead sees the message and responds.
2. **Negotiating** -- The org lead and the source discuss terms in the engagement conversation. Either party can send messages. This phase produces the `agreement.md`.
3. **Accepted / Declined** -- The org lead accepts or declines the terms.
4. **In Progress** -- The org lead decomposes the work into projects and/or jobs (see Orchestration below). Work happens at the workgroup/job level. The org lead monitors progress.
5. **Completed** -- The org lead marks the engagement as fulfilled and assembles deliverables.
6. **Reviewed** -- The source reviews the deliverables and provides a satisfaction rating.

At any point before review, either party can **cancel** the engagement.

---

## Engagement Conversations

Each engagement has a **conversation** -- this is how negotiation and status communication happen.

- For **external engagements**: Both orgs' leads (and permitted members) can message in the engagement conversation. The target org's lead participates automatically.
- For **internal engagements**: The requesting human and the org lead converse directly.

The engagement conversation is separate from any project or job conversations that the org lead creates internally. The engagement conversation is the external/top-level channel; projects and jobs are internal working spaces.

### Workspace Visibility

Engagement workspaces use **contract-based visibility**: not all internal work files are visible to the customer organization.

| Who | Can see |
|-----|---------|
| Source org | The engagement conversation, `agreement.md`, and files in `deliverables/` |
| Target org lead | The engagement, all dispatched projects/jobs, all internal work files |
| Target org workgroup agents | Only the jobs dispatched to their workgroup |
| Human members (source org) | The engagement conversation and deliverables |
| Human members (target org) | The engagement conversation; internal work via the org lead |
| System admin | Everything |

The target org controls what appears in `deliverables/`. Internal work products, drafts, and inter-workgroup coordination are not automatically exposed to the source org.

---

## Orchestration: Engagement to Projects and Jobs

When the org lead accepts an engagement, it decomposes the work and dispatches it internally. The decomposition may produce:

- **Projects** for cross-workgroup work (e.g., "Build mobile app" touches Design, Engineering, and QA)
- **Jobs** for single-workgroup work (e.g., "Write API documentation" goes directly to a workgroup)

Orchestration uses **hierarchical agent teams**: each level of work runs as an independent Claude Code team session, connected by liaison agents. See [hierarchical-teams.md](hierarchical-teams.md) for the full design.

### Engagement Team

When work begins on an accepted engagement, TeaParty launches an engagement team session:

- **Team lead**: Target org lead
- **Internal liaisons**: One per participating workgroup (or project, for cross-workgroup work)
- **External liaison**: Bridges to the source org's representative (for external engagements)

The org lead coordinates via native Claude Code team primitives (SendMessage, TaskCreate). Liaisons relay tasks to sub-teams via `relay_to_subteam` and results back via SendMessage.

### Org Lead Tools

The org lead needs tools beyond the standard toolkit to orchestrate across workgroups:

| Tool | Description |
|------|-------------|
| `create_project` | Create a project spanning multiple workgroups. Links back to the source engagement. Triggers a project team session with liaisons. |
| `create_job` | Create a job in a specified workgroup with title, scope, and requirements. Links back to the source engagement or project. |
| `list_workgroup_jobs` | List active jobs in a specified workgroup, with status. |
| `read_job_status` | Read the current state of a dispatched job (status, deliverables, latest activity). |
| `post_to_job` | Send a message to a job conversation in another workgroup (e.g., follow-up, clarification). |
| `complete_engagement` | Mark the engagement as completed and attach deliverables. |

These are **orchestration tools** -- a toolkit in the tool registry available to org lead agents. They require cross-workgroup permissions, which the Administration workgroup has by virtue of its designation.

### Dispatch Example

```
Organization: Acme Corp

Engagement Team Session:
  org-lead (team lead)
  liaison-design
  liaison-engineering
  liaison-qa
  liaison-partner (external, if cross-org)
    |
    +-- org-lead assigns: "Design the mobile app UI" --> liaison-design
    |     |
    |     +-- liaison-design calls relay_to_subteam()
    |           |
    |           +-- Job Team Session (Design workgroup):
    |                 design-lead, designer, researcher
    |                 Task: "Mobile app UI/UX design"
    |
    +-- org-lead assigns: "Build the API and frontend" --> liaison-engineering
    |     |
    |     +-- liaison-engineering calls relay_to_subteam()
    |           |
    |           +-- Job Team Session (Engineering workgroup):
    |                 engineering-lead, implementer, reviewer
    |                 Task: "Mobile app implementation"
    |
    +-- org-lead assigns: "Create test plan and run QA" --> liaison-qa
          |
          +-- liaison-qa calls relay_to_subteam()
                |
                +-- Job Team Session (QA workgroup):
                      qa-lead, tester
                      Task: "Mobile app test plan"
```

The org lead doesn't need to dispatch everything at once. It can sequence work -- assign design first, wait for the liaison to report completion, then assign engineering. The org lead coordinates this through the native Claude Code team primitives within the engagement/project team session.

Jobs dispatched from an engagement carry an `engagement_id` (and optionally a `project_id`) in their metadata, allowing the org lead to aggregate status and deliverables. Within each workgroup, agents may follow a [workflow](workflows.md) to execute the job.

### Progress Monitoring

The org lead monitors dispatched work through two channels:

- **Liaison reports**: Liaisons relay sub-team status via SendMessage when notified by TeaParty's async bridge. This is the primary feedback path.
- **Orchestration tools**: `list_workgroup_jobs` and `read_job_status` provide direct status queries for when the org lead wants to check without waiting for a liaison report.

TeaParty pushes sub-team events (completion, questions, stalls) to the parent team session via the async notification bridge, so the org lead doesn't need to poll -- liaisons report proactively.

---

## Feedback Bubble-Up Model

When agents need human input during job execution, feedback requests flow up the hierarchy:

```
Job Agent  ->  Workgroup Lead  ->  Org Lead  ->  Human
                                                   |
Job Agent  <-  Workgroup Lead  <-  Org Lead  <-----+
```

1. A job agent needs human feedback (approval, clarification, design direction).
2. The agent communicates this need in the job conversation.
3. The workgroup lead picks up the request and escalates to the org lead (via the project conversation or direct communication).
4. The org lead notifies the human (via org-level DM or the engagement conversation).
5. The human responds. The response routes back down: org lead -> workgroup lead -> job agent.

This model ensures:
- Humans are not bombarded with low-level implementation questions.
- Each level can filter, summarize, and contextualize before escalating.
- The org lead maintains a complete picture of what feedback is outstanding.
- All communication passes through the proper chain of command.

---

## Internal Engagements

When a human member creates an engagement directly (not through another org), the flow is identical:

1. The human describes what they need: "I need a marketing site for the product launch."
2. An engagement conversation is created in the Administration workgroup. The org lead picks it up and responds.
3. The org lead decomposes the work into projects and/or jobs.
4. When the work is done, the org lead delivers the result back to the human in the engagement conversation.

This gives every org member a single entry point for requesting work, regardless of which workgroups need to be involved. The human doesn't need to know the org's internal structure -- they just talk to the org lead.

---

## Cycle Prevention

Engagements can chain: Org A engages Org B, and Org B (to fulfill the work) engages Org C. Without safeguards, this could create cycles: A -> B -> C -> A.

### Mechanism

Each engagement carries an **engagement chain** -- an ordered list of organization IDs representing the path of work delegation that led to this engagement.

When Org B (working on an engagement from A) proposes a new engagement to Org C:
1. The new engagement inherits the chain from the parent: `[A, B]`.
2. Org C is checked against the chain.
3. If C is already in the chain, the engagement is **rejected** (cycle detected).
4. If C is not in the chain, C is appended: `[A, B, C]`.

This prevents any organization from appearing twice in a chain of delegation, regardless of depth.

### Depth Limits

As a practical safeguard, engagement chains have a maximum depth (e.g., 5). This prevents arbitrarily deep delegation chains even when no cycle exists.

---

## File Structure

See [file-layout.md](file-layout.md) for the full virtual file tree.

Engagement artifacts live at the org level:

```
organizations/<org>/engagements/<engagement>/
+-- engagement.json       # Status, terms, parties, engagement chain, linked project/job IDs
+-- agreement.md          # Negotiated scope and terms
+-- workspace/            # Working files (contract-based visibility)
+-- deliverables/         # Final work products (visible to source org)
```

Partnership records live at the org level:

```
organizations/<org>/partnerships/<partnership>/
+-- partnership.json      # Direction, status, partner org ID, established date
```

Internal projects and jobs live within their respective workgroups:

```
organizations/<org>/workgroups/<workgroup>/jobs/<job>/
+-- job.json              # Metadata, engagement_id, project_id (if applicable)
+-- ...                   # Work files
```

---

## Open Questions

1. **Contract-based visibility implementation**: File-level ACLs? Separate namespaces with explicit sharing? Read-only projections? The `deliverables/` directory is clearly visible to both parties, but the `workspace/` directory needs a visibility model.
2. **Partnership revocation during active engagement**: Grace period? Forced cancellation? Continue existing engagements but block new ones?
3. **Engagement pricing and payments**: The current model has `agreed_price_credits` and `payment_status` fields. How do credits flow? Escrow? Per-milestone payments?
