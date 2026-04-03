[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Team Configuration

Team configuration allows the human to organize their work into teams and projects, define agents with specialized roles, and give teams the skills, tools, and hooks they need to work effectively. Teams can be shared across projects, and each team knows who its decider is.

---

## The Configuration Tree

See [examples/teaparty-home-tree.md](examples/teaparty-home-tree.md) for the full directory layout.

```
~/.teaparty/
├── teaparty.yaml                              ← management team (includes teams: with paths)
└── workgroups/                                ← org-level shared workgroups

{project}/.teaparty/
├── project.yaml                               ← project team
└── workgroups/                                ← project-scoped (override org-level)
```

Each YAML file is under 200 lines. An agent reads a chain of small files: `teaparty.yaml` → `{project}/.teaparty/project.yaml` → `{project}/.teaparty/workgroups/coding.yaml`.

---

## Team Member Types

| Member type | What it is | Can have subteams? |
|-------------|-----------|-------------------|
| **Agent** | A Claude agent dispatched directly by the team lead | No |
| **Human** | A human participant (decider, advisor, informed) | No |
| **Workgroup** | A leaf team of agents that does work | No — terminal |
| **Team** | A composite team containing agents, humans, workgroups, and other teams | Yes |

Workgroups are terminal. Teams are composite. See [references/liaisons-and-instances.md](references/liaisons-and-instances.md) for how teams scale through lightweight representatives and spawned execution.

---

## Common Fields

Every team and workgroup has a `description` field — the one-line summary that tells a parent team lead when to dispatch to it.

### Human Roles: Decider-Advisor-Informed

| Role | Can speak in chats | Can decide at gates | Proxy models them |
|------|-------------------|--------------------|--------------------|
| **Decider** | Yes | Yes — final call | Yes — prediction target |
| **Advisor** | Yes — can interject | No — input is advice | No — context source |
| **Informed** | No — watch only | No | No |

Every team has exactly one decider. The decider is shown in the dashboard title bar. Changing the decider is done through the office manager chat.

---

## Configuration Levels

**Level 1: Management Team** — see [examples/teaparty.yaml](examples/teaparty.yaml). The root entry point: agents, humans, teams (with paths), workgroups, skills, scheduled tasks.

**Level 2: Project** — see [examples/project.yaml](examples/project.yaml). All four member types. Agents are dispatched directly (no relay overhead). Workgroups can be shared (`ref:`) or project-scoped.

**Level 3: Workgroup** — see [examples/workgroup-coding.yaml](examples/workgroup-coding.yaml) and [examples/workgroup-configuration.yaml](examples/workgroup-configuration.yaml). Lightweight summary pointing to `team_file` for full agent definitions.

---

## Key Concepts

- **[Matrixed Workgroups](references/matrixed-workgroups.md)** — shared across projects, with norm precedence (project trumps org) and cross-project learning.
- **[Norms](references/norms.md)** — advisory natural-language statements at org, workgroup, and project levels. Cost budgets are separate; see [cost-budget](../context-budget/references/cost-budget.md).
- **[Scheduled Tasks](references/scheduled-tasks.md)** — skill invocations on a timer, plus session-scoped loops.
- **[Hooks](references/hooks.md)** — shorthand references in YAML; authoritative source is `.teaparty/management/settings.yaml`.
- **[Progressive Disclosure Scenarios](references/progressive-disclosure-scenarios.md)** — concrete examples of navigating the tree.
- **[Commit Policy](references/commit-policy.md)** — what gets committed and what must never be committed (proxy memory, stats, sessions).

---

## Team Discovery

Projects can live anywhere on disk. They are listed under `teams:` in `teaparty.yaml` with a `path:`.

**Add existing project:** OM navigates the filesystem to locate the directory, performs agentic discovery (reads `pyproject.toml`, `README`, existing `.teaparty.local/project.yaml`), dialogs with the user to confirm frontmatter, then calls `POST /api/projects/add` with complete frontmatter. The backend registers the path and creates `.teaparty.local/project.yaml`. `.git/` and `.teaparty/` are not required at registration time — the OM bootstraps them before or after as needed.
**Create new project:** OM collects name, description, and other frontmatter through dialog, then calls `POST /api/projects/create`. The backend creates the directory, runs `git init`, creates `.teaparty/`, writes `.teaparty.local/project.yaml`, and adds to `teams:`.
**Remove project:** Remove from `teams:`. Project itself is untouched.

For discovery purposes (`discover_projects()`), a directory is considered a valid TeaParty project if it contains `.git/` and `.teaparty/`. Projects registered without these markers appear with `valid: false` until the OM bootstraps them.

---

## Skill Discovery and Precedence

Skills are resolved from the filesystem, not from YAML declarations alone.

**Org-level skills** are discovered from `{teaparty_home}/management/skills/`. A directory is a skill if it contains `SKILL.md`. The org catalog is filesystem-only — no YAML registration step is required. The `skills:` list in `teaparty.yaml` is an agent allowlist controlling which skills agents are permitted to invoke; it does not affect catalog display.

**Project-level skills** come from two sources, merged with local taking precedence:
1. **Local skills** — discovered from `{project_dir}/.teaparty/project/skills/`. Displayed as `local`.
2. **Registered org skills** — listed in `project.yaml skills:`, resolved against the org catalog. Displayed as `shared` if found in the catalog, `missing` if not installed.

If a local skill and a registered org skill share the same name, the local version is shown (source `local`) and the org version is suppressed.

A skill in `project.yaml skills:` that cannot be found in `{teaparty_home}/management/skills/` is flagged with source `missing` — it is not silently omitted.

The workgroup-level `skills:` field is a catalog/dispatch declaration (not an access control list) and is loaded from YAML unchanged. It is not affected by filesystem discovery.

---

## Relationship to Other Proposals

- [configuration-team](../configuration-team/proposal.md) — the team that creates and modifies these files
- [dashboard-ui](../dashboard-ui/proposal.md) — the dashboard reads these files to populate cards
- [office-manager](../office-manager/proposal.md) — reads `teaparty.yaml` as its primary source of organizational knowledge
- [context-budget](../context-budget/proposal.md) — orchestrator writes stats files referenced in YAML
