# Agent Configuration View

Clicking an agent on any dashboard opens a modal showing the full configuration as monospace text. This format is designed to be renderable in a TUI with box-drawing characters:

```
Agent:  Office Manager
Role:   Team Lead
File:   .teaparty/management/agents/office-manager/agent.md
Status: active

── Model ──────────────────────────
Model:           claude-opus-4
Max turns:       25
Permission mode: default

── Tools ─────────────────────────
Allowed:
  Read
  Glob
  Grep
  Bash
  WebSearch
  WebFetch

Disallowed:
  Write
  Edit
  NotebookEdit

── MCP Servers ────────────────────
  ask-question

MCP Tools:
  mcp__ask-question__Send
  mcp__ask-question__Reply
  mcp__ask-question__AskQuestion

── Hooks ─────────────────────────
  Stop [agent]
    Summarize conversation as memory chunks

── System Prompt ──────────────────
You are the office manager for TeaParty...
```

The modal is read-only. To modify an agent's configuration, the human uses the office manager chat — the Configuration Team handles changes.
