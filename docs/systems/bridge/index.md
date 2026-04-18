# Bridge (Dashboard)

Bridge is the HTML dashboard and the aiohttp server that backs it — the
human-facing surface of TeaParty. It runs on `localhost:8081`, renders a
small family of static pages, and streams live events from the rest of the
platform over a single WebSocket. Bridge is a reflection and interaction
layer on top of the orchestrator, not an orchestrator in its own right. It
observes state produced by other systems, and it forwards human input back
into them. It does not decide, dispatch, or drive work.

## Why it exists

Humans need visibility into running sessions and a place to talk to agents
without leaving the surface. Bridge gives them both in one browser tab.

- **One place to watch everything.** Active sessions, dispatch trees,
  heartbeat, cost, and artifacts are all rendered from the same state the
  orchestrator already writes. Operators do not need a terminal open to
  know what is happening.
- **One place to talk.** The chat blade is the primary interaction
  surface. Every page except `chat.html` mounts it, so the user can hold a
  conversation with the office manager, a project lead, or their own
  proxy without context-switching away from the page they are on. See
  [chat-ux](chat-ux.md).
- **One place to edit configuration.** Config screens expose the
  `.teaparty/` tree — management team, projects, workgroups, agents,
  skills, hooks — as browsable, toggleable forms instead of YAML the
  human has to hand-edit.
- **One place to intervene.** Typing into an active job's chat triggers
  an INTERVENE event; the Withdraw button emits a kill signal. Bridge is
  where direct intervention happens, because that is where the human
  already is.

## How it works

Bridge is a thin aiohttp application that serves static HTML and JS from
`teaparty/bridge/static/`, exposes a REST surface for config CRUD, and
maintains a single WebSocket broadcast channel at `/ws`.

- **State in.** A `StateReader` reads session and config state from disk.
  A `StatePoller` watches for heartbeat, participant, and CfA state
  changes and emits `state_update` events. A `MessageRelay` polls the
  per-session [messaging](../messaging/index.md) `SqliteMessageBus`
  instances and emits `message` and `input_requested` events. Every
  event dict is fanned out as a JSON frame to all connected clients.
- **State out.** Human chat input posts through the relay back into the
  conversation that the blade is bound to, where the target agent picks
  it up on its next turn.
- **Navigation.** Pages are organized as project → session → detail,
  with in-place anchor navigation so browser-native gestures
  (`Cmd+click`, middle-click) keep working. See
  [navigation](navigation.md) for the rule and the regression guard that
  enforces it.
- **Chat is one codepath.** Every page that shows a chat mounts
  `accordion-chat.js`. There is exactly one chat UX implementation; a CI
  test blocks merges that introduce a second. See [chat-ux](chat-ux.md).
- **Workspace integration.** Artifact pages render files directly out of
  the session worktree surfaced by [workspace](../workspace/index.md);
  Bridge does not own the worktree, it just reads it.

The server lives in `teaparty/bridge/server.py`; the state layer lives in
`teaparty/bridge/state/`; the static UI lives in `teaparty/bridge/static/`.
Launch it with `./teaparty.sh` from the repo root.

## Status

Operational and used daily. The case study in
[execution](../../case-study/execution.md) includes screenshots of the
dashboard during a live run — see the
[dashboard screenshot](../../case-study/artifacts/e2e%20workspace.png) for
the blade, the dispatch accordion, and the session list in context.

Known rough edges:

- The config screens render the full catalog for every page load; for
  large `.teaparty/` trees this is noticeable but not blocking.
- Heartbeat, stats, and telemetry each have their own emitter; the three
  have not yet been consolidated onto a shared event schema.
- A dedicated reference page for the Bridge REST surface was forthcoming
  in the legacy design layout and is still owed.

## Deeper topics

- [navigation](navigation.md) — in-place anchor navigation, browser-native
  gestures, the regression guard.
- [chat-ux](chat-ux.md) — the accordion chat blade, the one-codepath
  rule, the page routing table.
- [artifact-page](artifact-page.md) — the artifact viewer and pinning
  model.
- [heartbeat](heartbeat.md) — three-state liveness indicator.
- [stats-bar](stats-bar.md) — cost and token display.
- [telemetry](telemetry.md) — what Bridge emits and how it is consumed.
