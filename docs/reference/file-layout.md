# Virtual File Structure

This document describes the virtual tree structure that TeaParty exposes for stored files. All stored data is visible somewhere in this tree -- configurations, agent learnings, engagement artifacts, uploads, and AI-generated content.

For human readability, internal identifiers are replaced with entity names throughout the tree. Names need not be unique since they are keyed by identifiers internally.

See [overview.md](../overview.md) for the conceptual model this tree reflects.

## Full Tree

```
./
+-- config.json                                          # System configuration
|
+-- home/                                                # Per-user home level (Phase 1)
|   +-- home.json                                        # Home agent config, user preferences
|
+-- tools/                                               # Tool registry (read-only)
|   +-- file-ops/
|   |   +-- toolkit.json                                 #   read_file, list_files, add_file, edit_file, ...
|   +-- messaging/
|   |   +-- toolkit.json                                 #   summarize_conversation, suggest_next_step, ...
|   +-- workflow/
|   |   +-- toolkit.json                                 #   list_workflows, advance_workflow, ...
|   +-- task-management/
|   |   +-- toolkit.json                                 #   create_todo, list_todos, update_todo
|   +-- orchestration/
|   |   +-- toolkit.json                                 #   create_job, create_project, list_workgroup_jobs, ...
|   +-- sandbox/
|   |   +-- toolkit.json                                 #   sandbox_exec, git_status, merge_to_main, ...
|   +-- ...
|
+-- .templates/                                          # Composable bootstrapping blueprints
|   +-- workflows/
|   |   +-- <workflow-template>.md
|   +-- agents/
|   |   +-- <agent-template>/
|   |       +-- agent.json
|   +-- workgroups/
|   |   +-- <workgroup-template>/
|   |       +-- workgroup.json                           # References agent + workflow templates by key
|   |       +-- files/...
|   +-- organizations/
|       +-- <org-template>/
|           +-- organization.json                        # References workgroup templates by key
|
+-- organizations/
    +-- <org>/
        +-- organization.json                            # Org config, operations workgroup designation
        |
        +-- tools/                                       # Org custom tools
        |   +-- <tool>/
        |       +-- tool.json
        |
        +-- partnerships/                                # Trust links with other orgs
        |   +-- <partnership>/
        |       +-- partnership.json                     # Direction, status, partner org ID
        |
        +-- engagements/
        |   +-- <engagement>/
        |       +-- engagement.json                      # Status, terms, parties, engagement chain
        |       +-- agreement.md                         # Negotiated scope and terms
        |       +-- workspace/                           # Working files (contract-based visibility)
        |       +-- deliverables/                        # Final work products (visible to source org)
        |
        +-- projects/                                    # Cross-workgroup intra-org work
        |   +-- <project>/
        |       +-- project.json                         # Status, participating workgroups, engagement_id
        |       +-- workspace/                           # Shared project files
        |
        +-- members/
        |   +-- <member>/
        |       +-- member.json                          # Org role, preferences
        |
        +-- workgroups/
            +-- <workgroup>/
                +-- workgroup.json                       # Name, description, workspace config
                |
                +-- agents/
                |   +-- <agent>/
                |       +-- agent.json                   # Model, personality, tool_names, thresholds
                |       +-- learnings/...                # Agent memory and insights
                |
                +-- jobs/
                |   +-- <job>/
                |       +-- job.json                     # Metadata, engagement_id, project_id
                |       +-- _workflow_state.md            # Active workflow progress (if any)
                |       +-- uploads/...
                |       +-- ...                          # Job work files (isolated workspace)
                |
                +-- files/                               # Shared workgroup files
                    +-- workflows/
                    |   +-- <workflow>.md
                    +-- ...
```

## Scopes

Each conversation is scoped to a subtree. Agents and users in that conversation can **read** files within the scope and **write** to it and its subfolders.

| Context                | Scope Path                                                 |
|------------------------|------------------------------------------------------------|
| System administration  | `.`                                                        |
| Home (per-user)        | `./home`                                                   |
| Organization admin     | `./organizations/<org>`                                    |
| Engagement             | `./organizations/<org>/engagements/<engagement>`           |
| Project                | `./organizations/<org>/projects/<project>`                 |
| Workgroup admin        | `./organizations/<org>/workgroups/<workgroup>`             |
| Agent DM (org lead)    | `./organizations/<org>/workgroups/<admin>/agents/<lead>`   |
| Job                    | `./organizations/<org>/workgroups/<workgroup>/jobs/<job>`  |

A scope includes everything below it. A workgroup admin conversation can see all agents, jobs, files, and workflows in that workgroup. A job conversation can only see files within that job's folder. An org admin conversation can see all workgroups, engagements, projects, and members in the org.

**Note**: Humans can DM the org lead (scoped to the org lead's agent folder). Humans cannot DM workgroup leads or workgroup members directly. See [overview.md](../overview.md) for the human interaction model.

## Configuration Files

Each entity has a JSON configuration file at its root:

| Entity       | Path                                                                    | Key Fields |
|--------------|-------------------------------------------------------------------------|------------|
| System       | `./config.json`                                                         | LLM models, API keys, agent behavior limits |
| Organization | `./organizations/<org>/organization.json`                               | Name, description, operations workgroup, service description |
| Partnership  | `./organizations/<org>/partnerships/<partnership>/partnership.json`      | Direction, status, partner org ID, established date |
| Engagement   | `./organizations/<org>/engagements/<engagement>/engagement.json`        | Status, source/target IDs (currently workgroup-scoped, migrating to org-scoped in Phase 1), terms, engagement chain, linked project/job IDs |
| Project      | `./organizations/<org>/projects/<project>/project.json`                 | Status, participating workgroup IDs, engagement_id |
| Workgroup    | `./organizations/<org>/workgroups/<workgroup>/workgroup.json`           | Name, description, workspace config (image, preset, git_remote) |
| Agent        | `./organizations/<org>/workgroups/<workgroup>/agents/<agent>/agent.json` | Model, personality, tool_names, thresholds |
| Member       | `./organizations/<org>/members/<member>/member.json`                    | Org role (owner/admin/member), preferences. Note: the current data model tracks membership at the workgroup level; org-level membership is a Phase 1 target. |
| Job          | `./organizations/<org>/workgroups/<workgroup>/jobs/<job>/job.json`      | Title, scope, status, engagement_id, project_id |

## Tools

Tools are a **registry**, not templates. They are runtime capabilities that can be assigned to any agent.

### System Tools

Builtin tools ship with the system and are organized into **toolkits** -- logical groupings by function:

| Toolkit        | Tools                                                      |
|----------------|------------------------------------------------------------|
| File ops       | `read_file`, `list_files`, `search_files`, `add_file`, `edit_file`, `rename_file`, `delete_file` |
| Messaging      | `summarize_conversation`, `suggest_next_step`, `list_open_followups` |
| Workflow       | `list_workflows`, `get_workflow_state`, `advance_workflow`  |
| Task management| `create_todo`, `list_todos`, `update_todo`                  |
| Orchestration  | `create_job`, `create_project`, `list_workgroup_jobs`, `read_job_status`, `post_to_job`, `complete_engagement` |
| Sandbox        | `sandbox_exec`, `sandbox_shell`, `git_status`, `git_diff`, `git_commit`, `git_log`, `merge_to_main`, `list_repo_files` |
| Server-side    | `web_search`                                                |

These are visible in the tree at `./tools/<toolkit>/toolkit.json` -- read-only, defined in code.

The **orchestration toolkit** provides cross-workgroup capabilities needed by org lead agents. These tools require the agent's workgroup to be the designated operations workgroup -- other workgroups cannot use them.

The **sandbox toolkit** provides code execution and git operations inside isolated Docker containers. Each workgroup has a git repository; each job gets a branch and a sandbox container with Claude Code CLI. See [sandbox-design.md](../conceptual-design/sandbox-design.md) for the full architecture (future phase).

### Organization Custom Tools

Organizations can extend the registry with custom tools. These are defined at the org level and available to any agent in any workgroup within that org:

```
organizations/<org>/tools/<tool>/tool.json
```

Custom tools can be:
- **Prompt tools** -- an LLM executes a prompt template with structured input
- **Webhook tools** -- an HTTP call to an external service
- **Code tools** -- custom Python registered by the organization

Custom tools are registered by the org and appear in the tool catalog alongside builtins. Agents reference all tools the same way -- by name in their `tool_names` list. There is no distinction at the agent level between a builtin and a custom tool.

### Tool Grants

An organization can grant access to its custom tools to other organizations. Grants are tracked as a list of grantee org IDs in the tool's `tool.json`. Agents in the grantee org see the granted tool in their available tool catalog alongside builtins and their own org's custom tools.

## Templates

Templates live under `.templates/` at the system root. They are independent, composable blueprints -- each level references the others by key rather than containing them.

### Structure

```
.templates/
+-- workflows/
|   +-- <workflow-template>.md             # Reusable workflow playbooks
|
+-- agents/
|   +-- <agent-template>/
|       +-- agent.json                     # Model, personality, tool refs, thresholds
|
+-- workgroups/
|   +-- <workgroup-template>/
|       +-- workgroup.json                 # Name, description, agent + workflow refs
|       +-- files/
|           +-- README.md                  # Initial workgroup files
|           +-- docs/...
|
+-- organizations/
    +-- <org-template>/
        +-- organization.json              # Name, description, workgroup refs, operations workgroup
```

Each template level references the others by key:

- **Organization templates** list which workgroup templates to instantiate and which workgroup is the operations workgroup (e.g. `"workgroups": ["administration", "coding"], "operations_workgroup": "administration"`)
- **Workgroup templates** list which agent templates and workflow templates to include (e.g. `"agents": ["implementer", "reviewer"], "workflows": ["code-review", "feature-build"]`)
- **Agent templates** are leaf-level -- they reference tools by name from the registry, not from templates
- **Workflow templates** are standalone markdown files that get copied into a workgroup's `files/workflows/` on instantiation

This means:
- A "Coding" workgroup template can be used in any org template
- A "Reviewer" agent template can be used in any workgroup template
- A "Code Review" workflow template can be used in any workgroup template
- Tools are never templated -- agents just reference them by name

### How Bootstrapping Works

**Creating an organization** from a template:
1. Creates the org (from `organization.json`), including the `operations_workgroup` designation
2. Looks up each referenced workgroup template and instantiates it
3. Each workgroup instantiation looks up its referenced agent templates and creates those agents
4. Referenced workflow templates are copied into the workgroup's `files/workflows/`
5. Initial files from the workgroup template are copied in

Every org template should include an **Administration workgroup** with an org lead agent that has orchestration tools.

**Adding a workgroup** to an existing org picks from the same workgroup template catalog. An org owner selects a workgroup template and gets its agents, workflows, and files. This is independent of which org template was used at creation.

**Adding an agent** to an existing workgroup picks from the agent template catalog. A workgroup can gain new capabilities without needing a new workgroup template.

### Workflows in Workgroups

Workflow definitions are markdown files that live in a workgroup's `files/workflows/` directory. They can come from:
- A workflow template (copied on workgroup creation)
- Manual authoring by a workgroup member or agent
- Editing an existing workflow

Workflows describe multi-step playbooks that agents follow. They are content, not code. Agents discover and execute them through the workflow toolkit tools.

Workflow state is tracked per-job in `_workflow_state.md` within the job's folder. Each job gets its own independent workflow state, so the same workgroup can run different workflows across different jobs simultaneously.

### Editing Templates

Templates are visible and editable through the system admin's file browser (scope: `.`). Navigate to `.templates/workflows/`, `.templates/agents/`, `.templates/workgroups/`, or `.templates/organizations/` to view and modify definitions.

Changes to templates affect future instantiations only -- existing orgs, workgroups, and agents are not retroactively updated.

### Seed Templates

The system ships with seed templates defined in YAML (`seeds/templates/*.yaml`). These are loaded at startup and surfaced through the `.templates/` virtual tree. The system admin can override or extend them by editing the virtual files.

## Repositories and the Virtual Tree

Workspace-enabled workgroups have a git repository on the host filesystem. The virtual file tree and the git repo coexist -- they serve different purposes:

- **Virtual files** (`Workgroup.files` JSON column) -- documents, workflows, configuration, agent learnings. These are what agents read as prompt context. Managed through the file-ops toolkit.
- **Git repository** (bare repo + worktrees on disk) -- source code, build artifacts, anything that benefits from version history and branch isolation. Managed through the sandbox toolkit.

The main branch is synced to `Workgroup.files` so the file browser shows the current codebase state alongside documents. Job worktrees are read directly from the filesystem -- they are not synced to JSON while work is active.

Each job gets a git branch (`job/<job-id>`) and its own worktree. The branch isolates the job's code changes from other concurrent jobs -- this is critical when multiple jobs within a project modify the same files. Completed jobs merge back to main. See [sandbox-design.md](../conceptual-design/sandbox-design.md) for the full design (future phase).

## Agent File Access

Before each agent invocation, virtual files (from the `workgroup.files` JSON column) are materialized to a temporary directory on disk. Agents then work with real files using Claude's built-in file tools -- Read, Write, Edit, Glob, and Grep -- rather than receiving truncated file content embedded in prompts. A `PreToolUse` constrain hook scopes all file operations to the working directory, preventing agents from accessing anything outside it. When the agent finishes, any changes (modified, new, or deleted files) are synced back to the database.

For workspace-enabled workgroups with an active git worktree, the existing worktree path is reused instead of creating a temporary directory. This lets agents operate directly on the checked-out branch.

## File Scoping

Files are stored in the `workgroup.files` JSON column. Each file entry has an optional `topic_id` field that scopes it to a specific conversation context. Every conversation type gets its own workspace:

| Conversation type | `topic_id` value | Visible files |
|---|---|---|
| Admin | *(n/a -- sees everything)* | All files |
| Job | `{conversation.id}` | Shared + own job files |
| Agent DM | `agent:{agent_id}` | Own agent workspace only (isolated) |

Files with no `topic_id` (or empty string) are **shared** -- visible to all conversations (except admin, which sees everything including scoped files).

### Workspace identity

- **Agent DMs** -- the workspace persists across all DM conversations with the same agent, regardless of which user is chatting. The agent ID is extracted from the conversation `topic` field (`dma:{user_id}:{agent_id}`).
- **Jobs** -- each job conversation has its own workspace, identified by the conversation ID. This provides isolation when multiple jobs modify the same files.

### Job Workspace Isolation

When a workgroup has multiple active jobs (especially within a project or engagement), each job works in its own isolated workspace:

- **Virtual files workgroups**: Each job's `topic_id` scoping ensures its files are separate from other jobs.
- **Workspace-enabled workgroups**: Each job gets its own git worktree (branch), preventing concurrent jobs from clobbering each other's changes.

Completed jobs merge their changes back to the shared workspace. The project or engagement conversation serves as the coordination point for sequencing dependent jobs.

### Implementation

All `topic_id` assignment is centralized in `_topic_id_for_conversation()` (`tools.py`). The frontend mirror is `topicIdForConversation()` (`app.js`). Both backend and frontend file filtering use this helper -- no inline scoping logic elsewhere.

## Content Placement

**AI-generated content** goes into the scope folder of the conversation that produced it, or one of its subfolders.

**User uploads** go into `<scope>/uploads/`.

**Agent learnings** are stored as markdown or JSON files under the agent's `learnings/` folder. These accumulate as the agent interacts across jobs and conversations within its workgroup.

## Engagement Visibility

Engagements use contract-based visibility. The target org controls what the source org can see:

- The engagement conversation, `agreement.md`, and `deliverables/` directory are visible to both participating organizations.
- The `workspace/` directory and internal project/job files are only visible to the target org.
- The target org's org lead decides what to place in `deliverables/` when the engagement is completed.

