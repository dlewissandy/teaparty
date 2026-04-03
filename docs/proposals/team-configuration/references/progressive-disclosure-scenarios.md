# Progressive Disclosure in Practice

Three concrete scenarios showing how agents and humans navigate the configuration tree progressively, loading only what they need.

## Office Manager Checking Status

1. Reads `~/.teaparty/teaparty.yaml` — management overview including `teams:` with project paths (60 lines)
2. If the human asks about a specific project: reads `{project}/.teaparty/project.yaml` (50 lines)
3. If they drill into a workgroup: reads `{project}/.teaparty/workgroups/coding.yaml` (40 lines)

Total for a deep drill-down: ~150 lines across 3 files. Without progressive disclosure, this would be 500+ lines loaded upfront.

## Configuration Team Creating a Workgroup

1. Configuration Lead reads `{project}/.teaparty/project.yaml` to see current workgroups
2. Agent Designer creates agent definitions in `{project}/.teaparty/project/agents/` and the team JSON
3. Skill Architect assigns skills
4. Configuration Lead writes `{project}/.teaparty/workgroups/{name}.yaml`
5. Configuration Lead adds the workgroup entry to `{project}/.teaparty/project.yaml`

## Project Lead Spawning a Workgroup

1. Reads `{project}/.teaparty/workgroups/coding.yaml` — lightweight bootstrap (40 lines)
2. Reads `team_file` — full agent definitions for spawning team members (heavy, only now)
