# Tool Scoping Guide

## Principles

1. **Give only what the role needs.** An agent with unnecessary tools can accidentally modify things outside its scope.
2. **Read-only roles stay read-only.** If an agent reviews, audits, or reports — no Write or Edit.
3. **Write access implies accountability.** Agents with Write/Edit should have narrow, stated domains.

## Common profiles

**Read-only specialist** (auditor, reviewer, analyst):
```
tools: Read, Glob, Grep, Bash
```

**Config-writing specialist** (configuration team specialists):
```
tools: Read, Glob, Grep, Write, Edit, Bash
```

**Web researcher**:
```
tools: Read, Glob, Grep, WebSearch, WebFetch
```

**Team coordinator** (leads that dispatch to subagents):
```
tools: Read, Glob, Grep, Bash, Send
```

**Full-access developer**:
```
tools: Read, Glob, Grep, Write, Edit, Bash, WebSearch, WebFetch
```

## Model selection guide

**Use opus when:**
- The agent designs prompts or agent definitions (Agent Specialist, Skills Specialist)
- The agent makes high-stakes irreversible decisions
- The task requires deep multi-step reasoning

**Use sonnet when:**
- The agent handles routine coordination (team leads, most specialists)
- The task is structured and well-defined
- Speed and cost matter more than maximum reasoning depth

**Use haiku when:**
- The agent runs frequently (hooks, lightweight checks)
- The task is simple and narrow (extract a field, verify a value)
- Latency is critical

## maxTurns guidance

- 10–15: focused agents with narrow, completable tasks
- 20–25: specialists handling multi-step CRUD operations (default for config team)
- 30–40: coordinators, exploratory agents, agents that may need to ask questions
