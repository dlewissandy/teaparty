# Idea: Project-scoped team selection from organizational team definitions

## Problem

Team composition is currently hardcoded in `phase-config.json`. Every project uses the same teams (art, writing, editorial, research, coding) with the same agent definitions, the same tools, and the same permissions. A research paper project gets the same coding team as a software tooling project. A game development project gets the same editorial team as a medical content project.

Projects have different needs. A LaTeX paper project needs a latex-writer agent with access to a PDF render tool but no need for a frontend coding agent. A software project needs a test-runner agent with Bash access but no need for an art team. The current system offers no way for a project to say "I need these teams, configured this way."

Separately, agent instructions are global. There is no per-project `.claude/` directory where project-specific CLAUDE.md, settings, or agent overrides can live. An agent working on the hierarchical memory paper receives the same system context as one working on the TUI — the project has no voice in shaping agent behavior.

## Two layers

### Layer 1: Organizational team definitions

The organization (the top-level POC directory) defines the *catalogue* of available teams. Each team definition specifies:

- **Agents** — who is on the team, their roles, models, and base prompts.
- **Tools** — what tools are available to each agent (Read, Write, Edit, Bash, WebSearch, custom MCP tools, project-specific tools like the PDF render tool).
- **Skills** — what skills the team can invoke (research, editorial review, code review, etc.).
- **Permission mode** — default permission posture for the team's agents.

These are the building blocks. They live at the organizational level because they represent capabilities the organization has invested in defining and refining. They are not project-specific — they are reusable across projects.

This is what currently exists in `agents/*.json`, but without the tool/skill/permission configurability.

### Layer 2: Project team selection and configuration

Each project selects which teams it needs from the organizational catalogue and can override specific settings:

- **Team selection** — "This project uses: writing, research, editorial. It does not use: art, coding."
- **Agent overrides** — "The latex-writer on this project should use opus, not sonnet" or "The research-lead's prompt should include: 'This is an academic paper targeting COLM 2025.'"
- **Tool overrides** — "The writing team on this project gets access to the PDF render tool" or "The coding team on this project gets Bash access."
- **Project .claude/** — Each project gets its own `.claude/` directory with:
  - `CLAUDE.md` — project-specific instructions that all agents in the project receive.
  - `settings.json` — project-specific settings (model preferences, permission defaults).
  - Agent definition overrides that layer on top of the organizational definitions.

The project configuration is the project's voice in shaping how teams work within its context.

## Configuration via TUI

The TUI should provide an interface for:

1. **Browsing the organizational catalogue** — see all defined teams, their agents, tools, and skills.
2. **Selecting teams for a project** — check/uncheck which teams a project uses.
3. **Overriding agent settings per project** — modify model, prompt additions, tool access for specific agents within the project's context.
4. **Editing the project's .claude/CLAUDE.md** — project instructions that shape all agent behavior.

This is configuration, not runtime. Changes take effect on the next session, not mid-session.

## Resolution order

When the orchestrator assembles a team for a session, settings resolve in layers:

1. **Organizational default** — the base team definition from `agents/*.json`.
2. **Project override** — the project's team configuration, layering on model/prompt/tool changes.
3. **Session override** — (future) any session-specific overrides from the task or the human.

Later layers override earlier ones. Prompts are additive (project prompt is appended to org prompt, not replacing it). Tools and permissions use the most specific setting.

## What this enables

- A research paper project configures a writing team with LaTeX agents, a research team with web search and arxiv tools, and an editorial team — but no coding or art teams.
- A software project configures a coding team with Bash and test tools, a research team for API documentation lookup — but no writing or art teams.
- A game project configures an art team, a coding team, and a writing team with a narrative-focused prompt — but no editorial or research teams.
- Each project's `.claude/CLAUDE.md` gives agents the domain context they need without polluting other projects' agent behavior.

## Relationship to existing components

| Component | Current state | With this change |
|---|---|---|
| `agents/*.json` | Global team definitions | Become the organizational catalogue |
| `phase-config.json` | Hardcoded team→agent file mapping | References project config, falls back to org catalogue |
| Project directories | No `.claude/`, no team selection | Get `.claude/` and team config |
| TUI | No team/agent configuration UI | Adds project setup and team configuration screens |
| `PhaseConfig` | Loads from single `phase-config.json` | Resolves org defaults + project overrides |
