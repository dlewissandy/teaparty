# Project Creation Validation Checklist

Run these checks before reporting a project registration complete.

## Structural

- [ ] `project.yaml` parses as valid YAML
- [ ] `name` field is present and non-empty
- [ ] `description` field is present
- [ ] `lead` field references an agent definition that exists: `.claude/agents/{lead}.md`
- [ ] `decider` names a human listed in the `humans:` block
- [ ] All agents listed in `agents:` have definitions in `.claude/agents/`
- [ ] All workgroup `ref:` entries point to files that exist in `~/.teaparty/workgroups/`
- [ ] All project-scoped workgroup `config:` paths exist

## Registry

- [ ] `~/.teaparty/teaparty.yaml` has a `teams:` entry for this project
- [ ] The `path:` in the registry entry resolves to the project directory

## Report

State which files were created or modified and confirm the structural checks passed.
