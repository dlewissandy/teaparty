# Project Configuration Schema

## project.yaml fields

```yaml
name: My Project                    # human-readable display name
description: One-line description   # what this project does
lead: project-lead                  # agent name → .claude/agents/project-lead.md
decider: primus                    # human whose approval matters at gates

agents:                             # agents on this project team
  - project-lead                    # team lead (implicit, also listed explicitly)
  - qa-reviewer                     # any specialist agents

humans:
  - name: primus
    role: decider                   # final call at gates
  - name: alice
    role: advisor                   # can interject; advice not directive
  - name: bob
    role: informed                  # can see dashboard; no input

workgroups:
  - ref: coding                     # shared workgroup from ~/.teaparty/workgroups/
    status: active
  - name: Infra                     # project-scoped workgroup
    config: .teaparty/workgroups/infra.yaml
    status: active
```

## teaparty.yaml teams: entry

```yaml
teams:
  - name: My Project
    path: ~/git/my-project          # absolute or ~ path to the project directory
```

## Required fields

- `name` — must be unique across the registry
- `description` — one line
- `lead` — must reference an existing `.claude/agents/` definition
- `decider` — must be a human name

## Human roles

| Role | Meaning |
|---|---|
| decider | Final approval authority; proxy models this human |
| advisor | Can interject in chats; input is advice, not directive |
| informed | Read-only access to dashboard and chats |
