[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Configuration Team

When the human wants to create a new agent, skill, hook, or workgroup, they describe what they need in conversation. The Configuration Team — a specialized workgroup on the management team — handles the mechanics: designing the artifact, writing the files, and validating the result.

---

## Why a Team, Not a Skill

Creating a well-designed skill or agent is a multi-step process that benefits from specialization:

1. **Understanding the request** — what does the human actually need? A skill that runs a specific workflow? An agent with particular tool restrictions? A hook that validates output?
2. **Designing the artifact** — choosing the right structure, decomposing into files, selecting frontmatter options, writing prompts
3. **Optimizing for context** — progressive disclosure, scoped tools, minimal prompt footprint
4. **Validating the result** — does the skill invoke correctly? Does the agent have the right tools? Does the hook fire on the right events?

A single skill invocation can't do all of this well. A team of specialists can discuss tradeoffs, review each other's work, and iterate.

---

## Team Structure

The Configuration Team is a workgroup on the management team, with the same structure as any other workgroup.

```
Management Team
├── Office Manager (team lead)
├── Human (decider)
├── Configuration Team (workgroup)
│   ├── Configuration Lead (team lead)
│   ├── Skill Architect (specialist)
│   ├── Agent Designer (specialist)
│   └── Systems Engineer (specialist)
│
├── Project Team: POC (liaison)
└── ...
```

### Configuration Lead

Routes requests from the office manager to the right specialist. Understands the full configuration surface and can assess what artifacts are needed for a request. Coordinates multi-artifact requests (e.g., "create a new workgroup" requires agent definitions, skill assignments, possibly hooks and MCP configs).

**Model:** sonnet
**Tools:** Read, Glob, Grep, Bash, AskTeam

### Skill Architect

Creates and optimizes skills. Understands progressive disclosure, `!`command`` injection, supporting file decomposition, and frontmatter fields.

**Model:** opus (skill design requires careful prompt engineering)
**Tools:** Read, Glob, Grep, Write, Edit, Bash

### Agent Designer

Creates agent definitions. Understands tool scoping, model selection, permission modes, MCP server assignment, and prompt design for agent roles.

**Model:** opus
**Tools:** Read, Glob, Grep, Write, Edit, Bash

### Systems Engineer

Creates and modifies hooks, MCP server configurations, scheduled tasks, and settings. Understands the hook event model, matcher syntax, handler types, and settings file hierarchy.

**Model:** sonnet
**Tools:** Read, Glob, Grep, Write, Edit, Bash

---

## What the Team Creates

### Agents

**Location:** `.claude/agents/{name}.md` (project-scoped) or per-team agent JSON files

See [agent-definition.yaml](examples/agent-definition.yaml) for a complete example.

**Design decisions the Agent Designer makes:**
- Model selection (opus for complex reasoning, sonnet for routine work, haiku for simple checks)
- Tool scoping (read-only agents should not have Write/Edit)
- Permission mode (plan mode for high-stakes agents, acceptEdits for trusted ones)
- Max turns (tight limits for focused agents, generous for exploratory ones)
- MCP server assignment (which external tools does this agent need?)
- Prompt design (role, constraints, context, what the agent should and shouldn't do)

### Skills

**Location:** `.claude/skills/{name}/SKILL.md` + supporting files

**Structure designed for progressive disclosure:**

See [skill-structure.md](examples/skill-structure.md) for the directory layout and SKILL.md structure example.

**Design decisions the Skill Architect makes:**
- Decomposition: what belongs in SKILL.md vs. supporting files
- Progressive disclosure: what loads upfront vs. on demand
- Dynamic context: where to use `!`command`` for live data injection
- Argument design: what parameters the skill accepts
- Tool scoping: what tools the skill needs when active
- Invocation mode: user-invocable, model-invocable, or both
- Context mode: fork (isolated subagent) vs. inline

### Optimizing Existing Skills for Progressive Disclosure

This is a specific capability the Skill Architect provides. Given a monolithic skill (single large SKILL.md), the architect:

1. **Analyzes the skill's structure** — identifies logical sections, decision points, and reference material
2. **Identifies what's needed upfront vs. on demand** — the invocation instructions and high-level flow belong in SKILL.md; templates, reference data, examples, and branch-specific procedures belong in supporting files
3. **Decomposes into files** — extracts supporting content into named files with clear purposes
4. **Updates SKILL.md references** — replaces inline content with "Read `filename.md` for..." directives
5. **Adds dynamic context** — replaces static data with `!`command`` injection where appropriate (e.g., `!`gh issue view $ARGUMENTS`` to inject live issue data)
6. **Validates the description** — ensures the frontmatter description is specific enough for Claude to know when to auto-invoke, without loading the full skill

**Example optimization:** The `audit` skill currently has 9 role files (role-architect.md, role-specialist.md, etc.) that are loaded by subagents on demand — this is already well-structured. A monolithic audit skill would have all role definitions inline in SKILL.md, burning context on every invocation even when only 2-3 roles are needed.

### Hooks

**Location:** `.claude/settings.json` under the `hooks` key, or `.claude/settings.local.json` for non-shared hooks

See [hook-definition.json](examples/hook-definition.json) for a complete example.

**Design decisions the Systems Engineer makes:**
- Event selection (which lifecycle point to hook into)
- Matcher specificity (broad patterns vs. narrow tool-name matches)
- Handler type (command for scripts, agent for judgment calls, prompt for quick checks, http for external services)
- Blocking vs. non-blocking (exit code 2 blocks, exit code 0 proceeds)
- Scope (user-global, project, local, or per-agent/skill)

### MCP Servers

**Location:** `.mcp.json` (project-scoped, shareable) or `.mcp.local.json` (local)

See [mcp-server.json](examples/mcp-server.json) for a complete example.

### Scheduled Tasks

**Mechanism:** Claude Code's `/schedule` feature for persistent scheduled triggers.

A scheduled task **must** reference a skill. No raw prompts. The skill is the contract for what the task does. If the skill doesn't exist, the Skill Architect creates it first.

See [scheduled-task.yaml](examples/scheduled-task.yaml) for a complete example.

**The workflow for "create a new scheduled task":**
1. Does the skill exist? If not → Skill Architect creates it
2. Systems Engineer adds the `scheduled` entry to the appropriate YAML
3. Systems Engineer creates the `/schedule` trigger pointing to the skill

**Design decisions the Systems Engineer makes:**
- Schedule (cron expression)
- Which level the task belongs to (management or project)
- Notification preferences (when to alert on success/failure)

---

## How Requests Flow

See [request-flows.md](references/request-flows.md) for five detailed scenarios:

1. "I would like to create a new skill"
2. "I would like to create a new workgroup"
3. "Optimize the audit skill for progressive disclosure"
4. "Add a pre-commit hook that runs tests"
5. "Run the test sweep every night at 2am"

Each scenario describes how the Configuration Team coordinates to handle the request.

---

## Progressive Disclosure Applied to the Team Itself

The Configuration Team's own skills use progressive disclosure. Each specialist has skills that guide its work:

- **Skill Architect** has a `create-skill` skill that provides the SKILL.md template, frontmatter reference, and progressive disclosure guidelines — loaded on demand, not burned into the agent's system prompt
- **Agent Designer** has a `create-agent` skill with the agent frontmatter reference and tool scoping guidelines
- **Systems Engineer** has a `create-hook` skill with the event catalog, matcher syntax reference, and handler type comparison

These reference materials are in supporting files, not in the agents' prompts. The agents read them when they need them.

---

## What This Replaces

Currently, creating a new skill or agent requires the human to:
1. Know the file format
2. Know where files go
3. Write the frontmatter correctly
4. Design the prompt
5. Test the result

With the Configuration Team, the human says what they want in conversation. The team handles the mechanics. The human reviews the result in the dashboard (agent config modal, skill Finder/VS Code chooser) and iterates through further conversation if needed.

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) — the "+ New" buttons on dashboard cards pre-seed office manager conversations that trigger this team
- [dashboard-ui](../dashboard-ui/proposal.md) — agent, skill, hook, and cron cards display what this team creates
- [office-manager](../office-manager/proposal.md) — the office manager dispatches to this team via AskTeam

