[Recursive Bus Dispatch](../proposal.md) >

# Roster Derivation

Roster derivation produces the `--agents` JSON object for each spawned agent. The roster defines exactly who the agent can communicate with via `Send`. An agent cannot `Send` to anyone not in its roster.

---

## Derivation by Level

The same pattern applies at each level of the hierarchy: read the config source, build one roster entry per member, and map agent names to scoped agent IDs. The levels differ only in which config file is the source and how agent IDs are scoped.

### Office Manager

Source: `teaparty.yaml`

The OM's roster has one entry per project in `members.projects` (keyed by the project lead's agent definition name from `project.yaml`'s `lead:` field) and one entry per agent in `members.agents`. The examples below show the design target configuration, not current state. The current `teaparty.yaml` has `members.agents: []` (empty) and `members.projects: [TeaParty]` (one project).

```yaml
# Design target — not current config
members:
  projects:
    - TeaParty
    - pybayes
  agents:
    - auditor
    - researcher
    - strategist
```

Example roster (design target):
```json
{
  "teaparty-lead": {
    "description": "Research platform for durable, scalable agent coordination."
  },
  "pybayes-lead": {
    "description": "Bayesian inference library."
  },
  "auditor": {
    "description": "Code audits and quality assessment."
  }
}
```

Agent ID mapping: `teaparty-lead` becomes `teaparty/lead`, `pybayes-lead` becomes `pybayes/lead`, and management-level agents are scoped under `om/` (e.g., `auditor` becomes `om/auditor`).

### Project Lead

Source: `project.yaml`

The project lead's roster has one entry per workgroup in `members.workgroups`, keyed by the workgroup lead's agent definition name from the workgroup YAML's `lead:` field.

```yaml
lead: teaparty-lead
members:
  workgroups:
    - Coding
```

Example roster:
```json
{
  "coding-lead": {
    "description": "Implements features and fixes bugs."
  }
}
```

Agent ID mapping: `coding-lead` becomes `teaparty/coding/lead`.

### Workgroup Lead

Source: workgroup YAML (e.g., `coding.yaml`)

The workgroup lead's roster has one entry per agent in `members.agents`.

```yaml
lead: coding-lead
members:
  agents:
    - developer
    - reviewer
    - architect
```

Example roster:
```json
{
  "developer": {
    "description": "Writes implementation code."
  },
  "reviewer": {
    "description": "Reviews code for quality and correctness."
  },
  "architect": {
    "description": "Design analysis and architectural decisions."
  }
}
```

Agent ID mapping: `developer` becomes `teaparty/coding/developer`, `reviewer` becomes `teaparty/coding/reviewer`, `architect` becomes `teaparty/coding/architect`.

---

## Requestor Injection

When a child agent with a listener is spawned via `Send`, the spawner adds the caller to the child's roster so the child can Send questions back to the caller or close the thread via Reply.

```json
{
  "coding-lead": {
    "description": "The agent that requested this task. Send questions or ask for clarification. Use Reply when your work is complete."
  }
}
```

Requestor injection applies only to agents that have their own `BusEventListener` (leads with sub-rosters). These agents have a `SEND_SOCKET` and can use Send. Leaf workers without a listener cannot Send; they communicate with their caller exclusively through Reply. For leaf workers, the caller identity is conveyed through the Task/Context envelope, not through a roster entry.

This is the same requestor injection pattern described in the [invocation model](../../agent-dispatch/references/invocation-model.md#entry-construction-by-member-type). When a child Sends to its requestor (parent), the child's listener uses resume semantics (the parent already has a session), not spawn semantics. The requestor entry in the roster is marked with a `"type": "requestor"` field so the listener can distinguish this case.

---

## Sub-Roster Detection

The spawner must determine whether a recipient agent has its own sub-roster and therefore needs a `BusEventListener`. This is a structural check based on the recipient's position in the config tree, not on naming conventions or role labels.

The check walks the config tree:
1. Is the recipient a project lead? Check `project.yaml` for `members.workgroups`. If non-empty, the recipient gets a listener.
2. Is the recipient a workgroup lead? Check the workgroup YAML for `members.agents`. If non-empty, the recipient gets a listener.
3. Otherwise, the recipient is a leaf worker and gets no listener.

Management-level agents in the OM's roster (auditor, researcher, strategist) are treated as leaf workers by this algorithm because they do not appear as a `lead:` in any workgroup or project config. If a future configuration gives an agent its own team (e.g., the auditor becomes a workgroup lead with sub-agents), the algorithm detects it automatically because the auditor would appear in a workgroup's `lead:` field with a non-empty `members.agents`.

---

## Implementation Location

Roster derivation is a new module: `orchestrator/roster.py`. It depends on `config_reader.py` for loading YAML and on `bus_dispatcher.py` for the `RoutingTable` agent ID format.

Key functions:
- `derive_om_roster(teaparty_home) -> dict` -- OM's `--agents` JSON
- `derive_project_roster(project_dir, teaparty_home) -> dict` -- project lead's `--agents` JSON
- `derive_workgroup_roster(workgroup_path, project_name) -> dict` -- workgroup lead's `--agents` JSON
- `has_sub_roster(agent_name, config_tree) -> bool` -- whether the agent needs a listener
- `agent_id_map(roster, level, project_name, workgroup_name) -> dict[str, str]` -- name to agent_id mapping for the session-scoped roster map
