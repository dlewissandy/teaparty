# Management Dashboard

The human's home screen. Shows the state of the entire organization.

## Title Bar

Management Team name and description.

## Stats

| Stat | What it measures |
|------|-----------------|
| Jobs Done | Total completed jobs across all projects |
| Tasks Done | Total completed tasks across all projects |
| Active | Currently running jobs |
| One-shots | Jobs that completed without backtracking |
| Backtracks | Total backtracks across all projects |
| Withdrawals | Total withdrawals across all projects |
| Escalations | Total proxy escalations |
| Interventions | Total human interventions |
| Proxy Acc. | Proxy prediction accuracy percentage |
| Tokens | Total tokens consumed |
| Skills Learned | Proxy memory chunks accumulated |
| Uptime | Time since system start |

## Content Cards

| Card | Content | Action |
|------|---------|--------|
| **Escalations** | Pending escalations across all projects | Opens the job's chat |
| **Sessions** | Office manager chat sessions with liveness indicator. "+ New" | Opens session chat / creates new session |
| **Projects** | Project list with description, status, job/escalation counts. "+ New" | Navigates to project dashboard |
| **Workgroups** | Org-level shared workgroups with description, lead, agent count. "+ New" to create. "[Add]" opens a modal listing workgroups from any project; selecting one deep-copies it (agents, skills, tools, commands) into the management layer as a fully independent copy. Name conflicts prompt an overwrite warning before proceeding. | Navigates to workgroup dashboard |
| **Humans** | Team members with role (decider, advisor). From `humans:` in YAML. | Opens proxy review (self) or liaison chat (others). See [proxy-review](../../proxy-review/proposal.md) |
| **Agents** | Management team agents. "+ New" | Opens read-only agent config modal |
| **Skills** | Management-level skills. "+ New" | Opens skill in editor |
| **Scheduled Tasks** | Skill invocations on a timer, with schedule and last-run time. "+ New" | Pause/Resume, Run Now |
| **Hooks** | Hook definitions: event, matcher, handler type. "+ New" | Shows handler detail |

## Navigation

- Clicking a project navigates to the project dashboard
- Clicking a workgroup navigates to the workgroup dashboard
- Clicking a session opens its chat
- Clicking yourself in Humans opens a proxy review session
- Clicking another human in Humans opens a liaison chat with their proxy
- Clicking an escalation opens the relevant job's chat
- "+ New" on any card opens an office manager chat pre-seeded with intent
