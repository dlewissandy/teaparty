# Engagements

Engagements are how organizations interact — both with the outside world and with their own people. An engagement is a scoped piece of work with a lifecycle, managed at the organization level and fulfilled by the org's internal teams.

## What Is an Engagement

An engagement represents "someone asks the organization to do something." The source can be:

- **External** — another organization engages this org through the directory. This is the commerce path: Org A discovers Org B's capabilities, proposes an engagement, negotiates terms, and Org B delivers.
- **Internal** — a human member of the org creates an engagement directly. They describe what they need, and the org's coordinator handles it the same way it would handle external work. In this case the source and target are the same org — the human is both the requester and a member.

In both cases, the engagement follows the same lifecycle and uses the same orchestration path. The org doesn't distinguish between external and internal work at the execution level — work is work.

## The Operations Team

Every organization has a designated operations team (the "front desk"). The org's `organization.json` declares which team serves this role via an `operations_team` field. This team has a coordinator agent whose role is to:

1. **Receive engagements** — when an engagement is created (externally or internally), the coordinator is the first responder.
2. **Negotiate scope** — for external engagements, the coordinator discusses terms, clarifies requirements, and reaches agreement.
3. **Decompose work** — the coordinator breaks the engagement down into jobs and dispatches them to the appropriate internal teams.
4. **Track progress** — the coordinator monitors the jobs it dispatched, follows up with teams, and synthesizes status.
5. **Deliver results** — when the constituent jobs are complete, the coordinator assembles the deliverables and closes the engagement.

The operations team is not a special system concept — it's a regular team with a coordinator agent. This keeps the model uniform: teams have agents, agents have capabilities, the coordinator's capability is orchestration.

## Org Discovery

Organizations that want to receive external engagements publish a presence in the **org directory**. The directory is visible to all authenticated users and exposes:

- Organization name
- Service description (what the org does, what kinds of work it accepts)
- Status (accepting engagements or not)

These are fields in `organization.json`. The directory is how Org A finds Org B. Browsing the directory and proposing an engagement requires no pre-existing relationship — the engagement negotiation phase is where trust is established.

## Engagement Lifecycle

```
proposed → negotiating → accepted → in_progress → completed → reviewed
    │           │            │            │
    └───────────┴────────────┴────────────┴──→ cancelled
                             │
                          declined
```

1. **Proposed** — a source (external org or internal human) creates the engagement with a title, scope, and requirements. This creates an engagement conversation in the target org's operations team and posts an initial message. The coordinator agent is notified through normal message-response mechanics — it sees the message and responds.
2. **Negotiating** — the coordinator agent and the source discuss terms in the engagement conversation. Either party can send messages. This phase produces the `agreement.md`.
3. **Accepted/Declined** — the coordinator accepts or declines the terms.
4. **In Progress** — the coordinator dispatches jobs to internal teams (see Orchestration below). Work happens at the team/job level. The coordinator monitors progress.
5. **Completed** — the coordinator marks the engagement as fulfilled and assembles deliverables.
6. **Reviewed** — the source reviews the deliverables and provides a satisfaction rating.

At any point before review, either party can **cancel** the engagement.

## Engagement Conversations

Each engagement has a **conversation** — this is how negotiation and status communication happen. The conversation is scoped to `organizations/<org>/engagements/<engagement>/` and is visible to both participating orgs.

- For **external engagements**: both orgs' members can message in the engagement conversation. The target org's coordinator agent participates automatically.
- For **internal engagements**: the requesting human and the coordinator agent converse directly.

The engagement conversation is separate from any job conversations that the coordinator creates in internal teams. The engagement conversation is the external/top-level channel; job conversations are internal working spaces.

## Orchestration: Engagement to Jobs

When the coordinator accepts an engagement, it decomposes the work and creates jobs in the org's internal teams.

### Coordinator Tools

The coordinator agent needs tools beyond the standard toolkit to orchestrate across teams:

| Tool                  | Description                                                    |
|-----------------------|----------------------------------------------------------------|
| `create_job`          | Create a job in a specified team with title, scope, and requirements. Links the job back to the source engagement. |
| `list_team_jobs`      | List active jobs in a specified team, with status.              |
| `read_job_status`     | Read the current state of a dispatched job (status, deliverables, latest activity). |
| `post_to_job`         | Send a message to a job conversation in another team (e.g. follow-up, clarification). |
| `complete_engagement` | Mark the engagement as completed and attach deliverables.       |

These are **orchestration tools** — a toolkit in the tool registry available to coordinator agents. They require cross-team permissions, which the operations team has by virtue of its designation.

### Dispatch Example

```
Organization: Acme Corp
│
├── Engagement: "Build mobile app for client"
│   └── coordinator decomposes into:
│
├── Team: Design
│   └── Job: "Mobile app UI/UX design"          ← engagement_id links back
│
├── Team: Engineering
│   └── Job: "Mobile app implementation"         ← engagement_id links back
│
└── Team: QA
    └── Job: "Mobile app test plan"              ← engagement_id links back
```

The coordinator doesn't need to dispatch everything at once. It can sequence work — start with design, then kick off engineering when design delivers, then QA. The coordinator tracks these dependencies by reading job status and posting follow-ups.

Jobs dispatched from an engagement carry an `engagement_id` field in their `job.json`, allowing the coordinator to aggregate status and deliverables. Jobs not linked to an engagement have this field empty. Within each team, agents may follow a [workflow](workflows.md) to execute the job.

### Progress Monitoring

The coordinator monitors dispatched jobs through its orchestration tools:
- **Polling**: periodically calls `list_team_jobs` and `read_job_status` on dispatched jobs
- **Follow-ups**: the coordinator's follow-up mechanism (same as any agent) triggers it to check on stale jobs
- **Messages**: team agents can post updates to the job, which the coordinator can read

There is no push notification from jobs to the coordinator. The coordinator is an agent — it acts on its own follow-up schedule and when prompted by messages in the engagement conversation.

## Internal Engagements

When a human member creates an engagement directly (not through another org), the flow is identical:

1. The human describes what they need — "I need a marketing site for the product launch."
2. An engagement conversation is created in the operations team. The coordinator picks it up and responds.
3. The coordinator dispatches jobs to the relevant teams.
4. When the work is done, the coordinator delivers the result back to the human in the engagement conversation.

This gives every org member a single entry point for requesting work, regardless of which teams need to be involved. The human doesn't need to know the org's internal structure — they just talk to the front desk.

## File Structure

See [file-layout.md](file-layout.md) for the full virtual file tree.

Engagement artifacts live at the org level:

```
organizations/<org>/engagements/<engagement>/
├── engagement.json       # Status, terms, parties, engagement_id, linked job IDs
├── agreement.md          # Negotiated scope and terms
└── deliverables/         # Final work products
    └── ...
```

Both participating orgs can see the engagement. The internal jobs that fulfill it live within their respective teams:

```
organizations/<org>/teams/<team>/jobs/<job>/
├── job.json              # Metadata, engagement_id (if dispatched from engagement)
└── ...                   # Work files
```

## Visibility

| Who                        | Can see                                                  |
|----------------------------|----------------------------------------------------------|
| Source org members         | The engagement conversation and its deliverables         |
| Target org coordinator     | The engagement, all dispatched jobs, all team job files   |
| Target org team members    | Only the jobs dispatched to their team                    |
| System admin               | Everything                                                |
