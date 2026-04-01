# Workgroup Model

Supersedes:
- [team-configuration](../team-configuration/proposal.md)
- [configuration-team](../configuration-team/proposal.md)
- Configuration screen sections of [ui-redesign](../ui-redesign/proposal.md)

---

## Core Model

Everything in TeaParty is organized into **workgroups**. A workgroup is a collection of agents with a designated lead. The lead is responsible for the workgroup's work and is the only agent that dispatches to other agents within it — communication flows through leads, not between agents directly.

There are three kinds of workgroup:

- **Management workgroup** — the top-level workgroup. The Office Manager leads it. It knows about all registered projects and dispatches to Project Leads.
- **Project workgroup** — one per project. A Project Lead leads it. It knows about the project's workgroups and dispatches to Workgroup Leads.
- **Regular workgroup** — a team of agents doing a specific kind of work (coding, research, etc.). A Workgroup Lead leads it and dispatches to the agents within it.

**Chain of command:**

```
Management Workgroup (Office Manager)
├── Project Workgroup: TeaParty (Project Lead)
│   ├── Coding Workgroup
│   └── ...
└── Project Workgroup: pybayes (Project Lead)
    └── ...
```

Configuration workgroups exist outside this chain of command. They are available in the catalog but are never dispatched to by the Office Manager or any Project Lead. They are reached exclusively through the config screen's chat blade, described in the [Configuration UX Model](#configuration-ux-model) section.

---

## Human Participation

Humans are participants, not members. Agents are members — they are in the workgroup, can be dispatched to, and have skills whitelisted from the catalog. Humans are people who have a stake in the workgroup's work but are not agents. They are never dispatched to directly.

The `humans:` block declares who participates and in what capacity:

```yaml
humans:
  decider: darrell
  advisors:
    - alice
  inform:
    - xavier
```

Every workgroup has exactly one decider. Advisors and inform recipients are optional.

| Role | Capacity |
|------|----------|
| Decider | Final decision authority; can block or redirect work |
| Advisor | Can be consulted; input is advisory, not binding |
| Inform | Can be contacted by agents; does not participate in decisions |

When an agent needs input from the decider or an advisor, it escalates through a **proxy**. The proxy mediates all contact with that human. See [human-proxies.md](../../conceptual-design/human-proxies.md) for a full description of proxy behavior. The proxy is a runtime concern — one is instantiated automatically for the decider and each advisor based on the `humans:` block.

Humans in the `inform:` list do not have proxies. When an agent decides a participant should be informed, it sends them a message.

---

## Catalog and Active Selection

Every workgroup draws from a **catalog** — a pool of agents, skills, hooks, and scheduled tasks available to it. The catalog is defined at two levels:

**Management level** — implicit, derived from the filesystem:
- Agents: everything in `.claude/agents/`
- Skills: everything in `.claude/skills/`
- Hooks: everything in `.claude/settings.json`
- Scheduled tasks: all tasks defined at management level

**Project level** — a project may define additional agents, skills, hooks, and scheduled tasks in its own `.claude/` directory. These extend the management catalog and are available to workgroups within that project.

Individual workgroups do not define their own catalogs. They are consumers, not owners.

**Active selection** is the subset a workgroup has chosen to use:

- Which agents the lead can dispatch to
- Which hooks are wired up for this workgroup's events

Scheduled tasks are available only at the management and project levels, not for regular workgroups.

Skills are defined at the project or management level and whitelisted per agent — not per workgroup. Each agent has its own list of skills it is permitted to invoke, selected from the catalog on its config screen. See the [Agent Config Screen](#agent-config-screen) section.

The config screen shows the full inherited catalog for each category. Items already active are highlighted. Click an item to activate or deactivate it.

For hooks, see [hooks reference](../team-configuration/references/hooks.md). For scheduled tasks, see [scheduled tasks reference](../team-configuration/references/scheduled-tasks.md).

---

## Configuration Boundaries

Configuration authority is local. Each workgroup is responsible for configuring itself. No workgroup can configure another workgroup at the same level, and no lead can reach across project boundaries to configure a peer project's workgroups.

| Who | Can configure |
|-----|--------------|
| Management Config workgroup | Management workgroup only |
| Project Config workgroup | That project's workgroup and its sub-workgroups |

**Management Config** handles:
- Management workgroup membership — add, remove, edit
- Project registration — register and deregister projects
- Management-level workgroup registration

**Project Config** handles:
- Project workgroup membership — add, remove, edit
- Project properties (name, description) — update only; cannot create or delete a project
- Project-scoped workgroup registration and membership

Regular workgroups do not have their own config sub-workgroup. Their configuration is handled by the project config lead, reached via the chat blade on the workgroup's config screen.

Every configurable entity — each workgroup, each project, each agent, each artifact — has its own persistent chat with the appropriate config lead. Two workgroups in the same project have separate conversations, both with the same project config lead. Two agents in the same workgroup have separate conversations, also with the project config lead. The entity scopes the conversation; the level determines which config lead is on the other end.

---

## Registration and Membership

For projects, knowing about a project and being able to dispatch to it are separate concerns.

**Registration** means the management workgroup knows the project exists — its name, path, and config file location. A project can be registered but inactive (archived, paused, or imported for reference only).

**Membership** means the Office Manager can dispatch to that project's lead. Only registered projects can become members. Membership is declared by name, referencing the registration entry.

```yaml
# Registration — the management workgroup knows these projects exist
projects:
  - name: TeaParty
    path: .
    config: .teaparty/project.yaml
  - name: pybayes
    path: /Users/darrell/git/pybayes
    config: .teaparty/project.yaml

# Membership — the Office Manager can dispatch to these project leads
members:
  projects:
    - TeaParty
    - pybayes
```

The same pattern applies to workgroups within a project: a workgroup can be registered (the project knows it exists) without being a member (the Project Lead dispatches to it).

---

## Workgroup Frontmatter

### Regular Workgroup

```yaml
name: Coding
description: Implements features and fixes bugs.
lead: coding-lead
members:
  agents:
    - auditor
  hooks:
    - pre-commit
humans:
  decider: darrell
  advisors:
    - alice
  inform:
    - xavier
artifacts:
  - path: NORMS.md
  - path: docs/
    label: Docs
```

`lead:` names the agent responsible for the workgroup. `members.agents` lists the other agents the lead can dispatch to. These are distinct fields: the lead coordinates and dispatches; members are the agents it can call on. The lead is not listed under `members.agents`.

`members.hooks` lists the hooks active for this workgroup's events, selected from the inherited catalog.

Skills are not listed here. They are selected per agent on the agent config screen.

`artifacts` lists pinned items — files or directories — that are always accessible from this workgroup's config screen. Any path or directory that exists in the project can be pinned.

Each agent's own definition controls which tools it can use. That detail lives in the agent definition, not in the workgroup.

### Management Workgroup (`teaparty.yaml`)

The management workgroup adds project registration and workgroup registration blocks. `projects:` registers known projects; `members.projects` controls which ones the Office Manager dispatches to. `workgroups:` registers workgroups available at the management level (including the Configuration workgroup).

By default the OM dispatches only to project leads. Individual agents can be added to `members.agents` if the user explicitly wants the OM to dispatch to them directly, but the default is none.

```yaml
name: Management
description: Cross-project coordination and organizational strategy.
lead: office-manager
members:
  projects:
    - TeaParty
    - pybayes
  # agents: []  # optional — empty by default
humans:
  decider: darrell
projects:
  - name: TeaParty
    path: .
    config: .teaparty/project.yaml
  - name: pybayes
    path: /Users/darrell/git/pybayes
    config: .teaparty/project.yaml
workgroups:
  - name: Configuration
    config: .teaparty/workgroups/configuration.yaml
```

### Project Workgroup (`project.yaml`)

The project workgroup adds a workgroup registration block. `workgroups:` registers workgroups belonging to this project; `members.workgroups` controls which ones the Project Lead dispatches to. Projects do not register other projects — that is a management concern.

```yaml
name: TeaParty
description: Research platform for durable, scalable agent coordination.
lead: teaparty-lead
members:
  workgroups:
    - Coding
humans:
  decider: darrell
workgroups:
  - name: Coding
    config: .teaparty/workgroups/coding.yaml
  - name: Configuration
    config: .teaparty/workgroups/configuration.yaml
```

`Configuration` is registered here but not listed under `members.workgroups` — the Project Lead does not dispatch to it. It is reached via the config screen's chat blade.

---

## Norms

Each workgroup may have a `NORMS.md` file — a living document that captures how the workgroup operates. It is automatically pinned as an artifact so it is always accessible from the workgroup's config screen.

Norms are not YAML fields. They are created and updated through a discussion with the config lead via the chat blade. Once created, the workgroup YAML lists `NORMS.md` under `artifacts:`.

See [norms reference](../team-configuration/references/norms.md) for a full description of how norms are interpreted and enforced.

---

## Configuration UX Model

There are two ways to make configuration changes:

**Direct editing** — for structured data with well-defined fields (workgroup membership, agent metadata, hook selections). The config screen renders these as editable fields, pickers, and toggles. No conversation needed.

**Chat in context** — for changes that require judgment, generation, or explanation. The context is determined by the screen you are on — the artifact viewer knows which file is open; the config screen knows which entity is being configured. This includes creating new agents or skills from scratch, editing the prose body of an agent definition, modifying a `NORMS.md`, or discussing a change with the config lead before committing it. The artifact viewer is read-only — it is a launch point for chat, not an editor.

| What you want to change | How |
|------------------------|-----|
| Workgroup membership, hooks, tasks | Direct edit on config screen |
| Agent structured fields (name, description, model, permissions) | Direct edit on agent config screen |
| Creating a new agent, skill, or artifact | Chat via config screen blade |
| Agent prose body | Chat in context from artifact viewer |
| Norms, design docs, other prose artifacts | Chat in context from artifact viewer |
| Images, PDFs | Chat in context from artifact viewer |

**Creating vs adding:** the **+ New** button creates something that does not exist yet — it opens the chat blade to draft a new definition with the config lead. Adding an existing catalog item to a workgroup is a direct action: click the item in the panel to activate it. No conversation needed.

---

## Dashboard: Workgroup Config Screen

For a regular workgroup, the config screen has the following panels:

1. **Lead** — the agent responsible for the workgroup; handles all dispatching within it.
2. **Members** — agents the lead can dispatch to. Shows all agents in the inherited catalog; active agents are highlighted. Click to add or remove.
3. **Hooks** — event hooks wired up for this workgroup. Shows all hooks in the inherited catalog; active hooks are highlighted. Click to add or remove.
4. **Humans** — the people who participate in this workgroup's work. The decider is required (exactly one); advisors and inform recipients are optional. Humans are not members — the decider and advisors are reached via escalation through their proxy; inform recipients are contacted directly.
5. **Artifacts** — files and directories pinned to this workgroup (e.g., `NORMS.md`, `docs/`). Shows available items in the project; pinned items are highlighted. Click to pin or unpin. **+ New** opens the chat blade to draft and save a new artifact with the config lead.

A **chat blade** is present on every screen. The context is determined by the screen you are on; the level determines which lead is on the other end:

| Screen | Chat blade connects to |
|--------|----------------------|
| Main dashboard | Office Manager |
| Management config | Management config lead |
| Project config | Project config lead |
| Workgroup config | Project config lead, scoped to this workgroup |
| Agent config | Project config lead, scoped to this agent |
| Artifact viewer | Appropriate config lead, scoped to the file being viewed |

Management workgroup screens add a panel for project registration. Project workgroup screens add a panel for sub-workgroup registration.

---

## Agent Config Screen

Each agent has a dedicated config screen for its structured metadata. The prose body of the agent's `.md` file — which describes the agent's behavior and approach in depth — is edited via chat in context from the artifact viewer, not directly.

| Field | UI | Purpose |
|-------|----|---------|
| Name | Text field | Identifier used in YAML and dispatch |
| Description | Text field (prominent) | The signal a lead uses to decide whether to call this agent — must be precise |
| Model | Dropdown | Which Claude model this agent runs on |
| Skills | Selection from catalog | Skills this agent is permitted to invoke — shows full project/management catalog; whitelisted skills highlighted; click to add or remove |
| Tools | Selection from available tools | Tools this agent can use (e.g., Bash, Read, Write) |
| Permissions | Toggles | What the agent is allowed to do — file writes, network access, etc. |

A **chat blade** is present on the agent config screen, scoped to this specific agent. Use it to discuss changes to the agent's prose body with the config lead, or to draft a new agent from scratch.

---

## Open Items

- **Project Lead agent** — `project-lead.md` does not exist. `project.yaml` currently sets `lead: office-manager`, which is incorrect — the Office Manager should not be serving as a Project Lead. A Project Lead agent needs to be defined.
- **Workgroup config screen** — the workgroup dashboard is currently non-functional. The config screen described above needs to be built.
- **Agent config screen** — does not exist. Agent metadata is currently only editable by hand-editing the `.md` file.
- **Catalog selection UI** — no browse-and-select surface exists for skills, tools, hooks, or agents. Config screens currently show flat active lists only.
- **Artifact pin selector** — no file browser for selecting artifacts to pin. Paths must be entered manually.
- **Chat in context** — the artifact viewer has no button to open a chat. Users currently must start a new conversation manually and locate the file path themselves.


---

## Dashboard Bugs (existing config screen)

- **"Artifacts" vs "Pins" naming** — the management config screen calls the card "Artifacts"; the project config screen calls the equivalent card "Pins". Unify to "Artifacts". The artifact store sections (session outputs) should be renamed to "Sessions" to avoid the name collision.
- **Proxy hardcoded in Participants** — the project config screen always renders a "Proxy" entry under Participants. Proxy is a runtime concern implied by the `humans:` block and should not be listed explicitly.
- **Catalog vs active conflation** — Skills, Hooks, and Agents panels show active items only. The full inherited catalog with active items highlighted needs to replace these.
