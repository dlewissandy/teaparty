[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Configuration Team

When the human wants to create a new agent, skill, hook, or workgroup, they describe what they need in conversation. The Configuration Team, a specialized workgroup on the management team, handles the mechanics: designing the artifact, writing the files, and validating the result.

---

## Why a Team, Not a Skill

The four specialists use different models and different tool sets. The Skill Architect and Agent Designer use opus for prompt engineering and have Write access. The Configuration Lead uses sonnet and has AskTeam for routing but not Write. The Systems Engineer uses sonnet with Write for hooks and settings. A single agent cannot simultaneously be an opus agent with Write tools for prompt engineering and a sonnet agent with AskTeam for routing. The team structure maps to genuinely different capability profiles, not just sequential steps.

Whether the coordination overhead is worth it at the current POC scale is a prioritization decision. The design is sound; the question is when to build it.

---

## Team Structure

The Configuration Team is a workgroup on the management team, with the same structure as any other workgroup.

```
Management Team
+-- Office Manager (team lead)
+-- Human (decider)
+-- Configuration Team (workgroup)
|   +-- Configuration Lead (team lead)
|   +-- Skill Architect (specialist)
|   +-- Agent Designer (specialist)
|   +-- Systems Engineer (specialist)
|
+-- Project Team: POC (liaison)
+-- ...
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
- Prompt design (role, constraints, context, what the agent should and should not do)

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

Given a monolithic skill (single large SKILL.md), the Skill Architect analyzes its structure, identifies what is needed upfront versus on demand, extracts supporting content into named files, updates SKILL.md references, adds dynamic context where appropriate, and validates the description for auto-invocation.

**Example optimization:** The `audit` skill currently has 9 role files (role-architect.md, role-specialist.md, etc.) that are loaded by subagents on demand. This is already well-structured. A monolithic audit skill would have all role definitions inline, burning context on every invocation even when only 2-3 roles are needed.

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

A scheduled task **must** reference a skill. No raw prompts. The skill is the contract for what the task does. If the skill does not exist, the Skill Architect creates it first.

See [scheduled-task.yaml](examples/scheduled-task.yaml) for a complete example.

**The workflow for "create a new scheduled task":**
1. Does the skill exist? If not, Skill Architect creates it
2. Systems Engineer adds the `scheduled` entry to the appropriate YAML
3. Systems Engineer creates the `/schedule` trigger pointing to the skill

---

## How Requests Flow

See [request-flows.md](references/request-flows.md) for five detailed scenarios:

1. "I would like to create a new skill"
2. "I would like to create a new workgroup"
3. "Optimize the audit skill for progressive disclosure"
4. "Add a pre-commit hook that runs tests"
5. "Run the test sweep every night at 2am"

---

## Progressive Disclosure Applied to the Team Itself

Each specialist has skills that guide its work, loaded on demand rather than burned into the agent's system prompt:

- **Skill Architect** has a `create-skill` skill with the SKILL.md template, frontmatter reference, and progressive disclosure guidelines
- **Agent Designer** has a `create-agent` skill with the agent frontmatter reference and tool scoping guidelines
- **Systems Engineer** has a `create-hook` skill with the event catalog, matcher syntax reference, and handler type comparison

---

## What This Replaces

Currently, creating a new skill or agent requires the human to know the file format, know where files go, write the frontmatter correctly, design the prompt, and test the result. With the Configuration Team, the human says what they want in conversation. The team handles the mechanics. The human reviews the result in the dashboard and iterates through further conversation if needed.

---

## Validation

Configuration artifacts can be structurally valid but semantically wrong — an agent with the wrong tools for its role, a skill whose progressive disclosure defers the wrong content, a hook whose matcher is too broad. Validation has three levels, each catching a different class of defect.

### Structural

Does the artifact parse? Do its references resolve? Are named values legal?

- **Agents:** frontmatter fields present and typed correctly, model name is valid, listed tools exist, permission mode is recognized, MCP server names resolve to entries in `.mcp.json`
- **Skills:** SKILL.md has required frontmatter, supporting files referenced in the body exist, `!`command`` injections are syntactically valid, invocation mode is recognized
- **Hooks:** event name is a valid lifecycle event, matcher syntax parses, handler type is one of command/agent/prompt/http, referenced scripts or agents exist
- **MCP servers:** server entry has required fields (command or url), environment variables referenced in args are defined
- **Scheduled tasks:** cron expression parses, referenced skill exists

Structural checks are fully automatable. The Systems Engineer or relevant specialist runs them as part of artifact creation. A structural failure is a bug in the Configuration Team, not in the human's request.

### Behavioral

Does the artifact do something reasonable when exercised?

- **Agents:** spawn the agent with a representative prompt for its role; verify it uses the expected tools, produces output in the expected form, and terminates without error
- **Skills:** invoke the skill with representative arguments; verify the flow reaches its key decision points and the agent loads supporting files on demand rather than all upfront
- **Hooks:** simulate the trigger event; verify the hook fires, the matcher selects the right events, and the handler produces a meaningful response (not just exit 0)
- **MCP servers:** start the server; verify it responds to a list-tools call and the advertised tools match what the agent definition expects
- **Scheduled tasks:** trigger the schedule manually; verify the skill invocation completes

Behavioral checks verify that the artifact *runs* — that it exercises its intended path without crashing or doing nothing. They catch wiring errors (tool not available, file path wrong, matcher too narrow) and gross functional failures (agent ignores its role, skill loads everything upfront despite progressive disclosure design).

What behavioral checks cannot catch: an agent that completes its task but makes the wrong judgment calls. A skill that flows correctly but defers content the human actually needed upfront. A hook that fires on the right events but makes a poor blocking decision. These are semantic defects.

### Semantic

Does the artifact mean what the human intended?

Semantic validation asks whether the artifact's behavior aligns with the human's purpose — not just whether it runs, but whether it does the *right thing*. This is where behavioral checks end and human judgment begins.

For agents, the question is whether the prompt, tool set, and model selection produce the kind of reasoning and output the human expects for this role — something that can only be assessed by observing the agent on real tasks and comparing its behavior to the human's expectations. For skills, it is whether the progressive disclosure structure surfaces the right content at the right time for the human's actual workflow. For hooks, it is whether the matcher breadth and blocking decisions match the human's intent about what should be intercepted and what should pass through.

The Configuration Team's role in semantic validation is to *surface the artifact's behavior for human review*, not to judge it autonomously. After creating an artifact, the relevant specialist reports what was created and how it behaves on a representative task. The human observes, iterates through further conversation, and converges on the right behavior through use.

Full semantic validation of LLM-facing artifacts is an open research problem. An agent's prompt is a natural-language program executed by a language model — verifying that it "means the right thing" is equivalent to verifying natural-language program correctness, which has no general automated solution. The Configuration Team can catch structural and behavioral defects systematically. Semantic correctness emerges through human-in-the-loop iteration, not through testing.

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) -- the "+ New" buttons on dashboard cards pre-seed office manager conversations that trigger this team
- [dashboard-ui](../dashboard-ui/proposal.md) -- agent, skill, hook, and cron cards display what this team creates
- [office-manager](../office-manager/proposal.md) -- the office manager dispatches to this team via AskTeam
