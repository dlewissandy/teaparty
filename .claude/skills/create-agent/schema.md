# Agent Definition Schema

## Frontmatter fields

```yaml
---
name: agent-name                    # kebab-case, matches filename
description: One-line description.  # used by dispatcher to choose this agent
tools: Read, Glob, Grep, Bash       # comma-separated list
model: claude-sonnet-4-5            # see model options below
maxTurns: 20                        # max conversation turns (10–40 typical)
permissionMode: default             # default | acceptEdits | plan
skills:                             # skills this agent may auto-invoke (allowlist)
  - skill-name                      # omit field entirely if no skills
---
```

## Valid model values

| Model | Use for |
|---|---|
| `claude-opus-4-5` | Complex reasoning, prompt engineering, high-stakes judgment |
| `claude-sonnet-4-5` | Routine coordination, structured work, most specialists |
| `claude-haiku-4-5` | Simple checks, lightweight operations, high-frequency agents |

## Valid tools

Read, Glob, Grep, Bash, Write, Edit, WebSearch, WebFetch, Send, Reply, TodoRead, TodoWrite, NotebookRead, NotebookEdit

## Permission modes

| Mode | When to use |
|---|---|
| `default` | Standard approval flow (most agents) |
| `acceptEdits` | Trusted agents that write files without per-edit approval |
| `plan` | High-stakes agents that must show a plan before acting |

## skills: allowlist

Lists skills this agent is authorized to invoke via the skills mechanism. Omitting the field means no auto-invocable skills — correct for agents that are invoked BY skills (specialists) rather than agents that invoke skills.

## Body structure

The body (after the closing `---`) should contain:
- **Your Role** — what this agent does in one paragraph
- **Your Domain** — what files/systems it touches
- **How You Work** — key behaviors and decision criteria
- **Key References** — docs or config files to read first
