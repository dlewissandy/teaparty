# Project Edit Reference

Read `../create-project/schema.md` for the full field definitions.

## Common edits

**Add a team member:**
```yaml
agents:
  - existing-agent
  - new-agent          # add here; ensure .claude/agents/new-agent.md exists
```

**Change the lead:**
```yaml
lead: new-lead         # must have .claude/agents/new-lead.md
```

**Add a workgroup:**
```yaml
workgroups:
  - ref: coding        # shared workgroup
    status: active
```

**Update the decider:**
```yaml
decider: new-decider   # must be listed in humans: with role: decider
```

## What not to change without coordination

- `name` — changing the project name requires updating the registry entry in `teaparty.yaml`
- `lead` — verify the new lead agent definition exists before saving
- Removing agents — check that no workgroup or skill references them
