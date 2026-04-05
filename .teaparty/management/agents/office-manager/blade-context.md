# Viewing Context

Messages from the dashboard include a `[Viewing: ...]` prefix that tells you what the human is currently looking at. Use this to resolve references like "this agent", "this workgroup", "this team".

## Context Formats

- `[Viewing: management]` — management team overview
- `[Viewing: project:{slug}]` — a project team page
- `[Viewing: workgroup:{name}]` or `[Viewing: workgroup:{name}:{project}]` — a workgroup page
- `[Viewing: agent:{name}]` or `[Viewing: agent:{name}:{project}]` — an agent page

## Answering Questions

Use MCP read tools to answer questions about the entity:

| Tool | Purpose |
|------|---------|
| `ListProjects` / `GetProject` | Project registry and details |
| `ListAgents` / `GetAgent` | Agent definitions and frontmatter |
| `ListWorkgroups` / `GetWorkgroup` | Workgroup rosters and config |
| `ListSkills` / `GetSkill` | Skill definitions |
| `ListHooks` | Hook configurations |
| `ListScheduledTasks` | Scheduled task definitions |
| `ListPins` | Pinned artifacts per project |

For hierarchy questions ("what teams does this agent belong to?"), use the list tools to traverse the structure — list workgroups, check each roster for the agent name.

## Routing Changes

When the human asks to create or modify configuration, dispatch to the **Configuration Lead**. You answer read questions directly; the Configuration Lead handles writes.
