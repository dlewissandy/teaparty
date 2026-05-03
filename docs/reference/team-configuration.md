# Team Configuration

Detailed design for the two-level configuration hierarchy, catalog merging,
path conventions, and MCP CRUD tools.

Source files:

- `teaparty/config/config_reader.py` -- Config loading, path helpers, merge logic
- `teaparty/mcp/server/main.py` -- MCP server with tool registration
- `teaparty/mcp/tools/config_crud.py` -- Handler implementations
- `teaparty/mcp/tools/config_helpers.py` -- Shared path resolution and file I/O

---

## Config reader architecture

`config_reader.py` loads a two-level configuration tree:

- **Level 1 (Management):** `{teaparty_home}/management/teaparty.yaml` produces
  a `ManagementTeam` dataclass.  This is the organization-wide configuration:
  team name, description, lead, humans, projects, member rosters (agents,
  projects, skills, workgroups), workgroup definitions, norms, scheduled tasks,
  hooks, budget, and stats.

- **Level 2 (Project):** `{project_dir}/.teaparty/project/project.yaml` produces
  a `ProjectTeam` dataclass.  This is project-scoped: name, description, lead,
  humans, workgroups, member rosters, norms, scheduled tasks, hooks, budget,
  stats, and artifact pins.

### load_management_team()

Reads `{teaparty_home}/management/teaparty.yaml`.  Merges external projects
from the gitignored `external-projects.yaml` (machine-specific paths) into the
projects list.  Parses humans, projects (resolved relative to repo root),
member rosters, workgroups, norms, scheduled tasks, hooks, budget, and stats.

### load_project_team()

Reads `{project_dir}/.teaparty/project/project.yaml`.  Falls back to the legacy
`.teaparty.local/project.yaml` path for unmigrated projects.  Parses the same
categories as the management team minus the projects list, plus artifact pins
and project-scoped workgroup entries.

### load_workgroup()

Reads a single workgroup YAML file from either the management or project
workgroups directory.  Returns a `Workgroup` dataclass with members, skills,
norms, and delegation rules.

---

## Path conventions

All path construction is centralized in helper functions.  The `.teaparty/`
directory is the configuration source; `.claude/` is a composed artifact that
TeaParty writes into worktrees at dispatch time.

### Management-level paths

| Helper | Path |
|--------|------|
| `management_dir()` | `{teaparty_home}/management/` |
| `management_agents_dir()` | `{teaparty_home}/management/agents/` |
| `management_skills_dir()` | `{teaparty_home}/management/skills/` |
| `management_settings_path()` | `{teaparty_home}/management/settings.yaml` |
| `management_yaml_path()` | `{teaparty_home}/management/teaparty.yaml` |
| `management_workgroups_dir()` | `{teaparty_home}/management/workgroups/` |
| `external_projects_path()` | `{teaparty_home}/management/external-projects.yaml` |

### Project-level paths

| Helper | Path |
|--------|------|
| `project_teaparty_dir()` | `{project_dir}/.teaparty/project/` |
| `project_agents_dir()` | `{project_dir}/.teaparty/project/agents/` |
| `project_skills_dir()` | `{project_dir}/.teaparty/project/skills/` |
| `project_settings_path()` | `{project_dir}/.teaparty/project/settings.yaml` |
| `project_config_path()` | `{project_dir}/.teaparty/project/project.yaml` |
| `project_workgroups_dir()` | `{project_dir}/.teaparty/project/workgroups/` |
| `project_sessions_dir()` | `{project_dir}/.teaparty/jobs/` |

---

## Catalog merging

`merge_catalog(mgmt_base_dir, project_base_dir)` builds a unified view of
agents, skills, and hooks from both configuration levels.

### Merge algorithm

1. Discover management agents, skills, and hooks from `mgmt_base_dir/agents/`,
   `mgmt_base_dir/skills/`, and `mgmt_base_dir/settings.yaml`.
2. If `project_base_dir` is None or does not exist, return management-only catalog.
3. Discover project agents, skills, and hooks from the project directories.
4. **Project-first precedence:** project entries come first in the merged list.
   Management entries are appended only if their identifier is not already
   present in the project set.
5. **Hook precedence key:** `(event, matcher)` tuple.  Two hooks with the same
   event and matcher are the same hook; the project's version wins.

Returns a `MergedCatalog` with fields: `agents`, `skills`, `hooks`,
`project_agents` (set of names defined at project level), and `project_skills`.

### Agent definition resolution

When resolving an agent by name, the system checks the project scope first
(`{project_dir}/.teaparty/project/agents/{name}/`), then falls back to the
management scope (`{teaparty_home}/management/agents/{name}/`).  This allows
projects to override management-level agent definitions without modifying the
shared configuration.

---

## Conversation map and slot tracking

Each agent session maintains a `conversation_map` in `metadata.json`
(managed by `teaparty/runners/launcher.py`).  This tracks active child
sessions dispatched by the agent.

- **Slot limit:** `MAX_CONVERSATIONS_PER_AGENT = 3` -- an agent can have at
  most 3 concurrent child sessions.
- `record_child_session(session, request_id, child_session_id)` adds an entry.
- `remove_child_session(session, request_id)` frees a slot.
- `check_slot_available(session)` returns True when
  `len(conversation_map) < MAX_CONVERSATIONS_PER_AGENT`.

The conversation map is persisted atomically (temp file + `os.replace`) on
every change.

---

## MCP CRUD tools

The `teaparty-config` MCP server exposes 42 tools total.  Of these, 19 are
config CRUD tools in `teaparty/mcp/tools/config_crud.py` covering six entity
types with full create/read/list/edit/delete operations:

### Project tools
- `AddProject` -- register an existing directory as a project
- `CreateProject` -- create a new project with full scaffolding
- `RemoveProject` -- unregister a project (directory untouched)
- `ScaffoldProjectYaml` -- generate project.yaml from discovery
- `ListProjects` -- list all registered projects
- `GetProject` -- get a single project's configuration
- `ProjectStatus` -- git log summary for a project (last N days)

### Agent tools
- `CreateAgent` -- create agent definition (frontmatter + body)
- `EditAgent` -- modify agent tools, model, maxTurns, skills, or body
- `RemoveAgent` -- delete agent definition directory
- `ListAgents` -- list agents at a scope (management or project)
- `GetAgent` -- read a single agent definition

### Skill tools
- `CreateSkill` -- create skill directory with SKILL.md
- `EditSkill` -- modify skill content
- `RemoveSkill` -- delete skill directory
- `ListSkills` -- list skills at a scope
- `GetSkill` -- read a single skill definition

### Workgroup tools
- `CreateWorkgroup` -- create workgroup YAML with roster and norms
- `EditWorkgroup` -- modify workgroup definition
- `RemoveWorkgroup` -- delete workgroup YAML
- `ListWorkgroups` -- list all workgroups
- `GetWorkgroup` -- read a single workgroup

### Hook tools
- `CreateHook` -- add hook to settings.yaml
- `EditHook` -- modify hook event/matcher/handler
- `RemoveHook` -- delete hook entry
- `ListHooks` -- list all hooks

### Scheduled task tools
- `CreateScheduledTask` -- add scheduled task entry
- `EditScheduledTask` -- modify schedule/arguments/enabled state
- `RemoveScheduledTask` -- delete task entry
- `ListScheduledTasks` -- list all scheduled tasks

### Pin tools
- `PinArtifact` -- pin a file path as a project artifact
- `UnpinArtifact` -- remove an artifact pin
- `ListPins` -- list pinned artifacts for a project

### Other MCP tools (non-CRUD)
- `ListTeamMembers` -- enumerate team membership
- `AskQuestion` -- proxy question to human
- `Send` -- agent-to-agent messaging (the recipient's turn-end output is the reply; there is no agent-facing `Reply` tool)
- `CloseConversation` -- close an agent conversation
- `WithdrawSession` -- cancel a running session
- `PauseDispatch` / `ResumeDispatch` -- dispatch flow control
- `ReprioritizeDispatch` -- change dispatch priority

All tools delegate to handler functions in `config_crud.py` and use shared
helpers from `config_helpers.py` for path resolution (`_resolve_scope`,
`_scoped_agents_dir`, etc.) and YAML I/O.
