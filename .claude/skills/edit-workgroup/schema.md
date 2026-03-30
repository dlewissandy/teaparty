# Workgroup Edit Reference

Read `../create-workgroup/schema.md` for the full field definitions.

## Common edits

**Add a specialist:**
```yaml
agents:
  - name: Existing Lead
    role: team-lead
    model: claude-sonnet-4-5
  - name: New Specialist          # add here
    role: specialist
    model: claude-sonnet-4-5
```

**Add a skill to the catalog:**
```yaml
skills:
  - fix-issue
  - new-skill                     # ensure .claude/skills/new-skill/SKILL.md exists
```

**Update a norm:**
```yaml
norms:
  delegation:
    - Updated delegation rule
```

## Skills catalog vs. agent allowlist

The workgroup-level `skills:` is a catalog for dispatch routing — it lists what the workgroup can handle. It is NOT an access control list. Per-agent skill access is set in each agent definition's `skills:` allowlist field. Editing the workgroup catalog does not change what individual agents can invoke.
