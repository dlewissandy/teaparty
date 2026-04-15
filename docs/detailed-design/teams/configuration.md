# configuration

Dispatch here when the task involves defining or modifying how agents, workgroups, or skills are structured in the system. The team produces configuration artifacts — agent definitions, workgroup specs, skill templates — not application code or content. *(Already in management catalog.)*

---

## configuration-lead

The configuration-lead scopes the configuration work, dispatches to appropriate specialists, reviews outputs for correctness and internal consistency, and delivers configuration artifacts. It requests clarification when the intended agent behavior, tool scope, or skill design is underspecified — configuration errors propagate silently and are hard to trace after the fact. It declares completion when the configuration is consistent, correct, and the affected agents or workgroups behave as intended.

**Tools:** Read, Write, Glob, Grep, AskQuestion
**Skills:** digest

---

## skill-architect

Dispatch when a new skill needs to be designed or an existing one restructured. Defines the skill's purpose, interface, steps, and expected outputs. Not for writing the skill's agent-facing prose content (agent-designer) or for infrastructure concerns (systems-engineer).

**Tools:** Read, Write, Glob, Grep
**Skills:** digest

---

## agent-designer

Dispatch when an agent definition needs to be created or revised — role description, tool allowlist, skill allowlist, maxTurns, or behavioral boundaries. Works from a role brief and produces an agent.md. Not for skill structure (skill-architect) or infrastructure (systems-engineer).

**Tools:** Read, Write, Glob, Grep
**Skills:** digest

---

## systems-engineer

Dispatch when configuration work has infrastructure implications — tool permissions, MCP server setup, environment variables, hook configuration, or integration with external systems. Not for agent role design or skill structure.

**Tools:** Read, Write, Glob, Grep, Bash
**Skills:** digest
