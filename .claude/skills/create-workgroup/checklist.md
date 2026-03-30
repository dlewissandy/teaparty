# Workgroup Creation Validation Checklist

## Structural

- [ ] YAML parses without error
- [ ] `name` and `description` are present
- [ ] `lead` agent exists in `.claude/agents/`
- [ ] Each agent in `agents:` has name, role, model fields
- [ ] Model names are valid (`claude-sonnet-4-5`, `claude-opus-4-5`, etc.)
- [ ] Skills in catalog exist in `.claude/skills/`

## Registration

- [ ] A `workgroups:` entry points to this file in `teaparty.yaml` or `project.yaml`
- [ ] The `config:` path in the entry resolves to the new YAML file

## Report

State the file path, roster summary (lead + specialists), and skills catalog count.
