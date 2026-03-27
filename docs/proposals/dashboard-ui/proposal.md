[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Dashboard UI

The human's primary interface to TeaParty is a hierarchical dashboard. Each level of the team hierarchy has its own dashboard view. Navigation is drill-down: click a project to see its dashboard, click a workgroup to see its dashboard, click a job to see its dashboard, click a task to see its dashboard. Breadcrumbs navigate back up.

Interactive mockup (informative): [mockup/management.html](mockup/management.html). The mockup illustrates one possible visual rendering. The normative content is the navigation flow, information available at each level, and the actions the human can take.

---

## Navigation Flow

```
Management Dashboard
  └── Project Dashboard
        └── Workgroup Dashboard
              └── Job Dashboard
                    └── Task Dashboard
```

Every dashboard has: a title bar (name + description), summary stats, and content cards. The cards vary by level but the pattern is consistent. The human always knows where they are (breadcrumbs) and can navigate to any level in one or two clicks.

### Dashboard Levels

- **[Management Dashboard](references/management-dashboard.md)** — Home screen. Cards: escalations, office manager sessions, projects, org-level workgroups, humans, agents, skills, scheduled tasks, hooks.
- **[Project Dashboard](references/project-dashboard.md)** — Single project. Cards: escalations, sessions (project-scoped), jobs, workgroups, agents (direct team members), skills, scheduled tasks, hooks.
- **[Workgroup Dashboard](references/workgroup-dashboard.md)** — Single workgroup. Cards: escalations, sessions (workgroup-scoped), active tasks, agents, skills. No jobs or scheduled tasks.
- **[Job Dashboard](references/job-dashboard.md)** — Single CfA job. Workflow progress, escalations, CfA artifacts, task list. Actions: Chat, Withdraw.
- **[Task Dashboard](references/task-dashboard.md)** — Single task. Assignee, progress, escalations, artifacts, todo list. Actions: Chat, Withdraw.

---

## Key Behaviors

- **[Chat Windows](references/chat-windows.md)** — One chat per unit of work. Escalations, interventions, and status all flow through the same conversation. Stream content is filterable by type.
- **[Heartbeats and Badges](references/heartbeats-and-badges.md)** — Process liveness indicators (alive/stale/dead). Escalation badges bubble up through the hierarchy.
- **[Creating Things](references/creating-things.md)** — "+ New" buttons open office manager chats pre-seeded with intent. Creation flows through conversation, not forms.
- **[Agent Configuration View](examples/agent-config-view.md)** — Read-only modal showing full agent config. Modifications go through the office manager chat.

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) — interaction model: office manager conversations, job/task chats, escalation-in-chat, intervention-in-chat, WITHDRAW
- [messaging](../messaging/proposal.md) — message bus carrying chat content between agents and UI
- [office-manager](../office-manager/proposal.md) — the office manager agent
- [Milestone 3](../milestone-3.md) — milestone overview: human participation model
- [configuration-team](../configuration-team/proposal.md) — the Configuration Team that handles agent modifications
