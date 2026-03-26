# Conversational UI via tmux

A proposal to replace the monolithic Textual TUI with a tmux-based interface where each human-agent conversation gets its own terminal pane.

## Motivation

TeaParty's interaction model has the human talking to different agents at different levels of the hierarchy: the office manager (org lead) for day-to-day coordination, a team lead (workgroup lead) when participating in a project conversation, or a human proxy when an escalation needs direct human input. These are independent, concurrent conversations — not tabs in a dashboard.

The current Textual TUI renders everything into a single process. This works for monitoring (watching session progress, viewing logs) but breaks down when the human needs to *participate* in multiple live conversations simultaneously. A dashboard that shows output scrolling by is not the same as a terminal where you can type.

tmux is already a conversation-shaped tool. Each pane is an independent interactive session with its own scrollback, input line, and focus. The terminal multiplexer *is* the window manager — we just need orchestration logic for when to open, arrange, and close conversations.

## Design

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  tmux session: "teaparty"                           │
│                                                     │
│  ┌─────────────────────┬───────────────────────────┐│
│  │ Office Manager      │ Project: Q1 Launch        ││
│  │                     │                           ││
│  │ > what's the status │ [escalation from proxy]   ││
│  │   of the Q1 launch? │                           ││
│  │                     │ The test suite for the    ││
│  │ Two jobs in progr-  │ auth module is failing.   ││
│  │ ess. Engineering    │ The team needs guidance   ││
│  │ has a blocker —     │ on whether to fix the     ││
│  │ I've opened a pane  │ flaky integration test    ││
│  │ for you.            │ or skip it for now.       ││
│  │                     │                           ││
│  │                     │ > skip it, file an issue  ││
│  │                     │                           ││
│  └─────────────────────┴───────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

The system has three layers:

1. **tmux session** — one per TeaParty instance. Contains all conversation panes. The human uses standard tmux navigation (Ctrl-b + arrow keys, or mouse if enabled) to move between conversations.

2. **Pane manager** (Python, using libtmux) — a thin orchestration layer that creates, arranges, and destroys panes in response to system events. It does not own the agent processes; it creates the panes and launches `claude` sessions within them.

3. **Agent sessions** — each pane runs an interactive `claude` process. The human types directly into the pane. The agent's system prompt, tools, and context are configured at launch time by the pane manager.

### Pane Lifecycle

**Persistent panes** — some conversations are always open:

- **Office Manager** — the human's primary interface to the org lead. Always present in the leftmost pane. This is where the human gives instructions, asks for status, and receives notifications.

**Ephemeral panes** — opened on demand, closed when resolved:

- **Escalation panes** — when a human proxy determines that a decision exceeds its confidence threshold, the pane manager opens a new pane with the relevant agent session pre-loaded with the escalation context. The human addresses the question, and the pane closes (or is offered for closing) when the conversation reaches a natural resolution.

- **Participation panes** — when the human wants to join an ongoing project or job conversation. The office manager can open these on request ("let me talk to the engineering team about this").

- **Status panes** — lightweight, read-only panes that show live progress of running jobs (streaming agent output). These replace the current TUI dashboard screens.

### Pane Manager Responsibilities

The pane manager is a long-running Python process (separate from any agent) that:

- **Creates the tmux session** on startup with the office manager pane.
- **Listens for escalation events** from the orchestrator (via the existing EventBus / IPC mechanism) and opens new panes with the appropriate context.
- **Arranges panes** using tmux layouts. Sensible defaults: new escalations split the largest pane; the office manager pane maintains a minimum width.
- **Tracks pane-to-conversation mapping** so it can route events to the right pane and clean up when conversations end.
- **Handles pane closure** — when the human closes a pane (or the conversation ends), the pane manager records the outcome and notifies the orchestrator that the escalation was resolved.

### How Escalations Surface

Today, escalations block the orchestrator and wait for human input via a terminal prompt. With the tmux UI:

1. The proxy decides to escalate (confidence below threshold, novel situation, etc.).
2. The orchestrator emits an escalation event with the conversation context.
3. The pane manager receives the event and opens a new tmux pane.
4. The pane launches a `claude` session pre-loaded with: the escalation context, the agent's question, relevant artifacts, and the proxy's prediction (if any) of what the human might say.
5. The human sees the new pane appear (with a visual indicator — tmux can flash/bell the window) and navigates to it.
6. The human converses with the agent directly until the question is resolved.
7. The resolution flows back to the orchestrator, which unblocks the waiting proxy.

### Integration with Existing Orchestrator

The pane manager sits alongside the orchestrator, not inside it. The orchestrator continues to manage session lifecycle, CfA state machines, worktrees, and agent processes. The pane manager is purely a UI concern — it translates orchestrator events into tmux pane operations.

Key integration points:

- **EventBus** — the pane manager subscribes to escalation events, session start/end events, and status updates.
- **InputProvider** — for escalation panes, the human's input flows back through the existing InputProvider protocol. The pane manager bridges between the tmux pane's I/O and the orchestrator's input channel.
- **StateWriter** — status panes read from the same state files the current TUI reads.

### What Happens to the Current TUI

The Textual TUI (`projects/POC/tui/`) serves a monitoring and launch role. Under this proposal:

- **Monitoring** moves to tmux status panes (lightweight, read-only output streams).
- **Session launch** moves to the office manager conversation ("start a new project for X").
- **Dashboard views** (session list, dispatch drilldown) could remain as a Textual app running in its own tmux pane, or be replaced by CLI commands the human runs in any pane.

The Textual TUI is not deleted — it can coexist as a monitoring tool in a dedicated pane. But it is no longer the primary interaction surface.

## Platform Compatibility

| Platform | tmux available? | libtmux works? |
|----------|----------------|-----------------|
| macOS    | Yes (Homebrew, preinstalled on some systems) | Yes |
| Linux    | Yes (apt, yum, etc.) | Yes |
| WSL      | Yes (apt install tmux) | Yes |
| Windows native (cmd/PowerShell) | No | No |

Windows native is the only gap — and it is not a realistic target given the `claude` CLI dependency. WSL users get full support.

iTerm2 users on macOS get bonus features: iTerm2's tmux integration mode (`tmux -CC`) renders tmux panes as native iTerm2 tabs/splits with full mouse support, scrollback, and native rendering. This is a nice-to-have, not a requirement.

## Dependencies

- **libtmux** (MIT license, PyPI) — Python API for tmux session/window/pane management.
- **tmux** — must be installed on the host. Added as a documented prerequisite, not bundled.

## Open Questions

1. **Notification mechanism** — when an escalation pane opens while the human is focused elsewhere, how do we get their attention? Options: tmux bell, terminal notification (via OSC escape sequences), or a message in the office manager pane.

2. **Pane layout strategy** — should we use tmux's built-in layouts (even-horizontal, tiled, etc.) or manage geometry explicitly? Explicit management gives more control but is more code.

3. **Session persistence** — tmux sessions survive terminal disconnects. Should the pane manager reconnect to an existing tmux session on restart, preserving the human's conversation state?

4. **Multiple humans** — the current design assumes one human per tmux session. If multiple humans need to observe or participate, tmux's shared sessions or separate read-only attach could work, but this needs thought.

5. **Scrollback and history** — tmux pane scrollback is finite. For long conversations, should we persist conversation history to files and provide a way to search/review past exchanges?
