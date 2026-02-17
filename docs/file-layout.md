# Virtual File Structure

This document describes the virtual tree structure that TeaParty exposes for stored files. All stored data is visible somewhere in this tree — configurations, agent learnings, engagement artifacts, uploads, and AI-generated content.

For human readability, internal identifiers are replaced with entity names throughout the tree. Names need not be unique since they are keyed by identifiers internally.

## Full Tree

```
./
├── config.json                                          # System configuration
│
├── tools/                                               # Tool registry (read-only)
│   ├── file-ops/
│   │   └── toolkit.json                                 #   read_file, list_files, add_file, edit_file, ...
│   ├── messaging/
│   │   └── toolkit.json                                 #   summarize_conversation, suggest_next_step, ...
│   ├── workflow/
│   │   └── toolkit.json                                 #   list_workflows, advance_workflow, ...
│   ├── task-management/
│   │   └── toolkit.json                                 #   create_todo, list_todos, update_todo
│   ├── orchestration/
│   │   └── toolkit.json                                 #   create_job, list_team_jobs, read_job_status, ...
│   ├── sandbox/
│   │   └── toolkit.json                                 #   sandbox_exec, git_status, merge_to_main, ...
│   └── ...
│
├── .templates/                                          # Composable bootstrapping blueprints
│   ├── workflows/
│   │   └── <workflow-template>.md
│   ├── agents/
│   │   └── <agent-template>/
│   │       └── agent.json
│   ├── teams/
│   │   └── <team-template>/
│   │       ├── team.json                                # References agent + workflow templates by key
│   │       └── files/...
│   └── organizations/
│       └── <org-template>/
│           └── organization.json                        # References team templates by key
│
└── organizations/
    └── <org>/
        ├── organization.json                            # Org config, operations_team designation
        │
        ├── tools/                                       # Org custom tools
        │   └── <tool>/
        │       └── tool.json
        │
        ├── engagements/
        │   └── <engagement>/
        │       ├── engagement.json                      # Status, terms, parties, linked job IDs
        │       ├── agreement.md
        │       └── deliverables/...
        │
        ├── members/
        │   └── <member>/
        │       └── member.json                          # Org role, preferences
        │
        └── teams/
            └── <team>/
                ├── team.json
                │
                ├── agents/
                │   └── <agent>/
                │       ├── agent.json
                │       └── learnings/...
                │
                ├── jobs/
                │   └── <job>/
                │       ├── job.json                     # Metadata, optional engagement_id
                │       ├── _workflow_state.md            # Active workflow progress (if any)
                │       ├── uploads/...
                │       └── ...
                │
                └── files/
                    ├── workflows/
                    │   └── <workflow>.md
                    └── ...
```

## Scopes

Each conversation is scoped to a subtree. Agents and users in that conversation can **read** files within the scope and **write** to it and its subfolders.

| Context                | Scope Path                                              |
|------------------------|---------------------------------------------------------|
| System administration  | `.`                                                     |
| Organization admin     | `./organizations/<org>`                                 |
| Engagement             | `./organizations/<org>/engagements/<engagement>`        |
| Team administration    | `./organizations/<org>/teams/<team>`                    |
| Agent direct message   | `./organizations/<org>/teams/<team>/agents/<agent>`     |
| Human direct message   | `./organizations/<org>/members/<member>`                |
| Job                    | `./organizations/<org>/teams/<team>/jobs/<job>`          |

A scope includes everything below it. A team admin conversation can see all agents, jobs, files, and workflows in that team. A job conversation can only see files within that job's folder. An org admin conversation can see all teams, engagements, and members in the org.

## Configuration Files

Each entity has a JSON configuration file at its root:

| Entity       | Path                                                            | Key Fields |
|--------------|-----------------------------------------------------------------|------------|
| System       | `./config.json`                                                 | LLM models, API keys, agent behavior limits |
| Organization | `./organizations/<org>/organization.json`                       | Name, description, `operations_team`, service description, directory visibility |
| Engagement   | `./organizations/<org>/engagements/<engagement>/engagement.json` | Status, source/target org IDs, terms, linked job IDs |
| Team         | `./organizations/<org>/teams/<team>/team.json`                   | Name, description, sandbox config (image, preset, git_remote) |
| Agent        | `./organizations/<org>/teams/<team>/agents/<agent>/agent.json`   | Model, personality, tool_names, thresholds |
| Member       | `./organizations/<org>/members/<member>/member.json`             | Org role (owner/admin/member), preferences |
| Job          | `./organizations/<org>/teams/<team>/jobs/<job>/job.json`         | Title, scope, status, optional `engagement_id` |

## Tools

Tools are a **registry**, not templates. They are runtime capabilities that can be assigned to any agent.

### System Tools

Builtin tools ship with the system and are organized into **toolkits** — logical groupings by function:

| Toolkit        | Tools                                                      |
|----------------|------------------------------------------------------------|
| File ops       | `read_file`, `list_files`, `search_files`, `add_file`, `edit_file`, `rename_file`, `delete_file` |
| Messaging      | `summarize_conversation`, `suggest_next_step`, `list_open_followups` |
| Workflow       | `list_workflows`, `get_workflow_state`, `advance_workflow`  |
| Task management| `create_todo`, `list_todos`, `update_todo`                  |
| Orchestration  | `create_job`, `list_team_jobs`, `read_job_status`, `post_to_job`, `complete_engagement` |
| Sandbox        | `sandbox_exec`, `sandbox_shell`, `git_status`, `git_diff`, `git_commit`, `git_log`, `merge_to_main`, `list_repo_files` |
| Server-side    | `web_search`                                                |

These are visible in the tree at `./tools/<toolkit>/toolkit.json` — read-only, defined in code.

The **orchestration toolkit** provides cross-team capabilities needed by coordinator agents. These tools require the agent's team to be the designated operations team — other teams cannot use them.

The **sandbox toolkit** provides code execution and git operations inside isolated Docker containers. Each team has a git repository; each job gets a branch and a sandbox container with Claude Code CLI. See [sandbox-design.md](sandbox-design.md) for the full architecture.

### Organization Custom Tools

Organizations can extend the registry with custom tools. These are defined at the org level and available to any agent in any team within that org:

```
organizations/<org>/tools/<tool>/tool.json
```

Custom tools can be:
- **Prompt tools** — an LLM executes a prompt template with structured input
- **Webhook tools** — an HTTP call to an external service
- **Code tools** — custom Python registered by the organization

Custom tools are registered by the org and appear in the tool catalog alongside builtins. Agents reference all tools the same way — by name in their `tool_names` list. There is no distinction at the agent level between a builtin and a custom tool.

### Tool Grants

An organization can grant access to its custom tools to other organizations. Grants are tracked as a list of grantee org IDs in the tool's `tool.json`. Agents in the grantee org see the granted tool in their available tool catalog alongside builtins and their own org's custom tools.

## Templates

Templates live under `.templates/` at the system root. They are independent, composable blueprints — each level references the others by key rather than containing them.

### Structure

```
.templates/
├── workflows/
│   └── <workflow-template>.md             # Reusable workflow playbooks
│
├── agents/
│   └── <agent-template>/
│       └── agent.json                     # Model, personality, tool refs, thresholds
│
├── teams/
│   └── <team-template>/
│       ├── team.json                      # Name, description, agent + workflow refs
│       └── files/
│           ├── README.md                  # Initial team files
│           ├── docs/...
│           └── ...
│
└── organizations/
    └── <org-template>/
        └── organization.json              # Name, description, team refs, operations_team
```

Each template level references the others by key:

- **Organization templates** list which team templates to instantiate and which team is the operations team (e.g. `"teams": ["operations", "coding"], "operations_team": "operations"`)
- **Team templates** list which agent templates and workflow templates to include (e.g. `"agents": ["implementer", "reviewer"], "workflows": ["code-review", "feature-build"]`)
- **Agent templates** are leaf-level — they reference tools by name from the registry, not from templates
- **Workflow templates** are standalone markdown files that get copied into a team's `files/workflows/` on instantiation

This means:
- A "Coding" team template can be used in any org template
- A "Reviewer" agent template can be used in any team template
- A "Code Review" workflow template can be used in any team template
- Tools are never templated — agents just reference them by name

### How Bootstrapping Works

**Creating an organization** from a template:
1. Creates the org (from `organization.json`), including the `operations_team` designation
2. Looks up each referenced team template and instantiates it
3. Each team instantiation looks up its referenced agent templates and creates those agents
4. Referenced workflow templates are copied into the team's `files/workflows/`
5. Initial files from the team template are copied in

Every org template should include an **operations team** with a coordinator agent that has orchestration tools. See [engagements.md](engagements.md).

**Adding a team** to an existing org picks from the same team template catalog. An org owner selects a team template and gets its agents, workflows, and files. This is independent of which org template was used at creation.

**Adding an agent** to an existing team picks from the agent template catalog. A team can gain new capabilities without needing a new team template.

### Workflows in Teams

Workflow definitions are markdown files that live in a team's `files/workflows/` directory. They can come from:
- A workflow template (copied on team creation)
- Manual authoring by a team member or agent
- Editing an existing workflow

Workflows describe multi-step playbooks that agents follow — see [workflows.md](workflows.md) for the full specification. They are content, not code. Agents discover and execute them through the workflow toolkit tools.

Workflow state is tracked per-job in `_workflow_state.md` within the job's folder. Each job gets its own independent workflow state, so the same team can run different workflows across different jobs simultaneously.

### Editing Templates

Templates are visible and editable through the system admin's file browser (scope: `.`). Navigate to `.templates/workflows/`, `.templates/agents/`, `.templates/teams/`, or `.templates/organizations/` to view and modify definitions.

Changes to templates affect future instantiations only — existing orgs, teams, and agents are not retroactively updated.

### Seed Templates

The system ships with seed templates defined in YAML (`seeds/templates/*.yaml`). These are loaded at startup and surfaced through the `.templates/` virtual tree. The system admin can override or extend them by editing the virtual files.

## Repositories and the Virtual Tree

Every team has a git repository on the host filesystem. The virtual file tree and the git repo coexist — they serve different purposes:

- **Virtual files** (`Team.files` JSON column) — documents, workflows, configuration, agent learnings. These are what agents read as prompt context. Managed through the file-ops toolkit.
- **Git repository** (bare repo + worktrees on disk) — source code, build artifacts, anything that benefits from version history and branch isolation. Managed through the sandbox toolkit.

The main branch is synced to `Team.files` so the file browser shows the current codebase state alongside documents. Job worktrees are read directly from the filesystem — they are not synced to JSON while work is active.

Each job gets a git branch (`job/<job-id>`) and a sandbox container. The branch isolates the job's code changes; the container provides the execution environment (builds, tests, Claude Code CLI). Completed jobs merge back to main. See [sandbox-design.md](sandbox-design.md) for the full design.

## Agent File Access

Before each agent invocation, virtual files (from the `workgroup.files` JSON column) are materialized to a temporary directory on disk. Agents then work with real files using Claude's built-in file tools — Read, Write, Edit, Glob, and Grep — rather than receiving truncated file content embedded in prompts. A `PreToolUse` constrain hook scopes all file operations to the working directory, preventing agents from accessing anything outside it. When the agent finishes, any changes (modified, new, or deleted files) are synced back to the database.

For workspace-enabled workgroups with an active git worktree, the existing worktree path is reused instead of creating a temporary directory. This lets agents operate directly on the checked-out branch.

## Content Placement

**AI-generated content** goes into the scope folder of the conversation that produced it, or one of its subfolders.

**User uploads** go into `<scope>/uploads/`.

**Agent learnings** are stored as markdown or JSON files under the agent's `learnings/` folder. These accumulate as the agent interacts across jobs and conversations within its team.

## Engagement Visibility

Engagements are visible to both participating organizations. Each org sees the engagement under its own `organizations/<org>/engagements/<engagement>/` path. The engagement files (agreement, deliverables) are shared — both orgs read and write to the same logical engagement space. See [engagements.md](engagements.md) for the full engagement lifecycle and orchestration model.
