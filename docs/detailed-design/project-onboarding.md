# Project Onboarding

Detailed design for what happens when a project is added to TeaParty — the
operations performed, the files created, and the resulting state.

Source files:

- `teaparty/config/config_reader.py` -- Directory scaffolding, project.yaml creation, registry writes
- `teaparty/mcp/tools/config_crud.py` -- MCP handler entry points, project lead scaffolding

---

## Overview

A project is a directory on disk that TeaParty knows about. It has a git
repository, a Claude Code configuration, a `.teaparty/project/` configuration
tree, a Project Lead agent registered in the management catalog, and an initial
commit that puts all of that under version control. The management team's
registry records the project's name, path, and config pointer.

There are two entry points, corresponding to the two MCP tools exposed by the
`teaparty-config` server:

| Entry point | When to use |
|---|---|
| `CreateProject` → `create_project()` | The directory does not yet exist |
| `AddProject` → `add_project()` | The directory already exists |

Both produce identical end state. The difference is only in precondition
checking and the initial `os.makedirs` + `git init` step.

---

## Entry points

### CreateProject

**Preconditions:**
- `name` is non-empty
- `path` does not already exist on disk
- No project named `name` is in the current registry

**Rejects:** directory already exists, duplicate name.

### AddProject

**Preconditions:**
- `name` is non-empty
- `path` exists and is a directory
- No project named `name` is in the current registry

**Rejects:** path does not exist, duplicate name.

---

## Parameters

| Parameter | Required | Notes |
|---|---|---|
| `name` | Yes | Unique project name. Normalized before use (see below). Also determines the lead agent name: `{name}-lead`. |
| `path` | Yes | Absolute path to the project directory. |
| `decider` | Yes | Human decider for this project (typically the org decider). |
| `description` | No | Human-readable project description. Defaults to the sentinel value (see below). |

### Name normalization

The `name` parameter is normalized before it is used anywhere — as a registry
key, a directory name, a lead agent name, or a value written into `project.yaml`.
Normalization: lowercase, whitespace collapsed and replaced with hyphens.

Examples: `"My Project"` → `"my-project"`, `"PyBayes "` → `"pybayes"`.

The normalized name is what the human sees in the dashboard, what agents receive
in config reads, and what forms the lead name (`{name}-lead`). The raw input is
not stored.

The `lead` parameter does not exist. The lead name is always derived as
`{name}-lead` and is always created if it does not already exist.

### Description sentinel

When `description` is not provided, `project.yaml` is written with:

```
⚠ No description — ask the project lead
```

This sentinel appears wherever the description is displayed — the dashboard
project card, the project config pane, and in the project lead's context when
it reads `project.yaml`. It reads as an instruction to both the human and the
agent: the right way to set it is to ask the project lead, who will engage the
project-specialist to capture it through a short dialog and write the result
back to `project.yaml`.

---

## Step-by-step operations

The steps below describe the full sequence for both entry points.
`CreateProject`-only steps are marked; everything else applies to both.

### Step 1 — Create the directory *(CreateProject only)*

```python
os.makedirs(path)
```

### Step 2 — Ensure a git repository

Checks for `.git/`. If missing:

```bash
git init {path}
```

An already-initialized repo is left untouched.

### Step 3 — Ensure a `.claude/` directory

```python
os.makedirs(os.path.join(project_dir, '.claude'), exist_ok=True)
```

`.claude/` is the Claude Code configuration directory. TeaParty creates it
here as a placeholder; it is populated by the dispatch layer at session launch
time (catalog merging writes agent and skill definitions into the worktree's
`.claude/` before launching the agent).

### Step 4 — Ensure `.teaparty/project/` subdirectories

```python
os.makedirs(os.path.join(tp_proj, 'agents'), exist_ok=True)
os.makedirs(os.path.join(tp_proj, 'skills'), exist_ok=True)
os.makedirs(os.path.join(tp_proj, 'workgroups'), exist_ok=True)
```

The layout:

```
{project}/
  .teaparty/
    project/
      project.yaml          ← created in step 5
      agents/               ← project-scoped agent overrides
      skills/               ← project-scoped skill overrides
      workgroups/           ← project-scoped workgroup definitions
    jobs/                   ← populated at runtime (job/session records)
```

### Step 5 — Create `project.yaml`

Writes `.teaparty/project/project.yaml` unless it already exists
(non-destructive). The scaffold:

```yaml
name: {name}
description: {description or sentinel}
lead: {name}-lead
humans:
  decider: {decider}
workgroups:
  - Configuration
members:
  workgroups: []
artifact_pins: []
```

The `workgroups` list includes `Configuration` explicitly so the Configuration
Team is visible in the project's config tree, not just inherited silently
through catalog merging. This makes the team's availability discoverable to
both humans reading the config and agents reading it at dispatch time.

### Step 6 — Write `.gitignore` from template

Writes a `.gitignore` to the project root if one does not exist. If one already
exists, the TeaParty stanza is appended if not already present.

The template covers TeaParty runtime state that must not be committed:

```gitignore
# TeaParty — runtime sessions (ephemeral job records)
.teaparty/jobs/

# TeaParty — SQLite databases (auto-initialize on first use)
*.db
*.db-shm
*.db-wal
*.db-journal
```

The `.teaparty/project/` configuration tree is intentionally **not** ignored —
it is source-controlled project configuration, not runtime state.

### Step 7 — Register in `external-projects.yaml`

Writes the project into the gitignored `external-projects.yaml`:

```
{teaparty_home}/management/external-projects.yaml
```

This file is gitignored because it contains absolute machine-specific paths.
An entry:

```yaml
- name: my-project
  path: /abs/path/to/my-project
  config: .teaparty/project/project.yaml
```

`load_management_team()` merges both `teaparty.yaml` and
`external-projects.yaml` into the unified projects list at read time, so the
distinction is invisible to consumers of the config API.

Projects that are part of the TeaParty repo itself are listed directly in
`teaparty.yaml` with relative paths. All other projects go into
`external-projects.yaml`.

### Step 8 — Scaffold the Project Lead agent

`_scaffold_project_lead()` creates the agent definition in the **management**
catalog at:

```
{teaparty_home}/management/agents/{name}-lead/
  agent.md        ← frontmatter + prompt body
  settings.yaml   ← MCP tool permissions
  pins.yaml       ← which artifacts are pinned in the UI
```

All three files are non-destructive: skipped if they already exist so that
manually customized leads are never clobbered.

#### `agent.md`

Frontmatter:

| Field | Value |
|---|---|
| `name` | `{name}-lead` |
| `description` | `"{name} project lead. Receives work from the Office Manager, breaks it down for workgroup leads, and reports back up. Use for any task scoped to the {name} project."` |
| `tools` | Standard project-lead tool set (see below) |
| `model` | `sonnet` |
| `maxTurns` | `30` |

Standard project-lead tool set:

```
Read, Glob, Grep, Bash,
mcp__teaparty-config__GetAgent, mcp__teaparty-config__GetProject,
mcp__teaparty-config__GetSkill, mcp__teaparty-config__GetWorkgroup,
mcp__teaparty-config__ListAgents, mcp__teaparty-config__ListHooks,
mcp__teaparty-config__ListPins, mcp__teaparty-config__ListProjects,
mcp__teaparty-config__ListScheduledTasks, mcp__teaparty-config__ListSkills,
mcp__teaparty-config__ListTeamMembers, mcp__teaparty-config__ListWorkgroups,
mcp__teaparty-config__PinArtifact, mcp__teaparty-config__ProjectStatus,
mcp__teaparty-config__Send, mcp__teaparty-config__UnpinArtifact,
mcp__teaparty-config__WithdrawSession
```

The prompt body establishes the lead's role in the chain of command, how to
read `project.yaml`, how to dispatch to workgroup leads, and how to use
`ProjectStatus` for status reporting.

#### `settings.yaml`

Grants explicit allow-list permissions for all MCP tools in the tool set.

#### `pins.yaml`

Pins `agent.md` and `settings.yaml` so the UI shows them in the lead's
artifact panel:

```yaml
- path: agent.md
  label: Prompt & Identity
- path: settings.yaml
  label: Tool & File Permissions
```

### Step 9 — Make the initial commit

Stages and commits all files created in the project directory:

```
.gitignore
.teaparty/project/project.yaml
.teaparty/project/agents/
.teaparty/project/skills/
.teaparty/project/workgroups/
```

Commit message: `chore: add TeaParty project configuration`

For `AddProject` on a project with an existing git history, this is a regular
commit on whatever branch is currently checked out. For `CreateProject`, it is
the repository's first commit.

The files in the management catalog (`agent.md`, `settings.yaml`, `pins.yaml`
for the project lead) live in the TeaParty repo, not the project repo — they
are committed separately as part of normal TeaParty configuration management.

### Step 10 — Emit telemetry event

```python
_emit_config_event('config_project_added', project=name, path=path)
# CreateProject also passes: created=True
```

Best-effort — failures are swallowed so config CRUD is never blocked by
telemetry. Unknown event type constants raise `AssertionError` at development
time (no silent fallbacks).

---

## Database initialization

No database initialization is required at project registration time. Every
database in the system — telemetry, agent message stores, proxy memory,
episodic index — auto-initializes on first use via `CREATE TABLE IF NOT EXISTS`
on first connection.

---

## The Configuration Team and project membership

The Configuration Team is a management-level workgroup whose agents
(`project-specialist`, `workgroup-specialist`, `agent-specialist`,
`skills-specialist`, `systems-engineer`) are defined in the management catalog
and available to all projects through catalog merging.

`project.yaml` lists `Configuration` explicitly in its `workgroups` field so
the team's membership is visible in the project's own configuration, not just
inherited silently. When the project lead needs configuration work done —
including setting the project description — it routes through the Office Manager
to the Configuration Lead, which delegates to the appropriate specialist.

---

## Resulting file tree

After a successful `CreateProject` or `AddProject` for a project named
`my-project` with `decider="darrell"`:

```
{teaparty_home}/
  management/
    agents/
      my-project-lead/
        agent.md
        settings.yaml
        pins.yaml
    external-projects.yaml    ← new entry appended

{project}/
  .git/                       ← initialized if missing; initial commit made
  .gitignore                  ← written from template
  .claude/                    ← created if missing
  .teaparty/
    project/
      project.yaml
      agents/
      skills/
      workgroups/
```
