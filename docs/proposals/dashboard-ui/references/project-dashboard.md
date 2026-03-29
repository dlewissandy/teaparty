# Project Dashboard

Shows the state of a single project. Reached by clicking a project on the management dashboard.

## Title Bar

Project name, decider, and description. Clicking the decider name opens a proxy review (if you) or liaison chat (if someone else).

## Stats

Same stats as management, scoped to this project (no Uptime).

## Content Cards

| Card | Content | Action |
|------|---------|--------|
| **Escalations** | Pending escalations for this project | Opens the job's chat |
| **Sessions** | Office manager sessions scoped to this project. "+ New" | Opens session chat with implicit project context |
| **Jobs** | Active jobs with CfA workflow progress. "+ New" | Navigates to job dashboard |
| **Workgroups** | Workgroup list with description, lead, agent count. Shared (org-level) workgroups are distinguished from project-scoped ones. "+ New" to create. "[Add]" opens a modal listing all management-level workgroups; selecting one deep-copies it (agents, skills, tools, commands) into the project as a fully independent copy. Name conflicts prompt an overwrite warning before proceeding. | Navigates to workgroup dashboard |
| **Agents** | Direct team members dispatched by the project lead without workgroup relay. "+ New" | Opens read-only agent config modal |
| **Skills** | Project-scoped skills. "+ New" | Opens skill in editor |
| **Scheduled Tasks** | Project-scoped scheduled tasks. "+ New" | Pause/Resume, Run Now |
| **Hooks** | Project-scoped hooks. "+ New" | Shows handler detail |

Sessions opened from a project dashboard carry implicit project context — the office manager knows the human is talking about this project without being told.

## Navigation

- Clicking a job navigates to the job dashboard
- Clicking a workgroup navigates to the workgroup dashboard
- Clicking a session opens the office manager chat with project context
- Clicking an escalation opens the relevant job's chat
- "+ New" buttons open an office manager chat pre-seeded with project-scoped intent
