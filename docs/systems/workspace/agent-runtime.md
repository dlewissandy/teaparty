# Agent Runtime

## Design Choice: Claude Code CLI

All agent invocations go through `claude -p` -- the Claude Code CLI in pipe mode. The CLI provides `--agent` definitions, `--agents` team rosters, tool use, permission modes, session persistence via `--resume`, and `stream-json` output as built-in capabilities. Using the CLI lets us move fast: we get multi-agent coordination, file system access, and tool orchestration without building any of it ourselves.

The `--setting-sources user` flag is required on every invocation. This prevents Claude Code from reading project-level settings that could conflict with the launcher's composed configuration, and is required for OAuth token authentication under the Max SLA.

The tradeoff is clear. The CLI is not a stable API -- it's a product interface that can change between releases. A production system would replace CLI invocations with direct Anthropic API calls, reimplementing team coordination, tool dispatch, and permission enforcement at the application layer. For a research platform, the CLI's capabilities far outweigh the coupling risk.

---

## Unified Launcher

Every agent in TeaParty launches through a single async function: `launch()` in `teaparty/runners/launcher.py`. No alternative codepaths exist. The launcher reads `.teaparty/` configuration to derive everything the agent needs, composes the worktree, builds the subprocess arguments, and delegates to `ClaudeRunner` for execution.

```python
async def launch(
    *,
    # Core identity
    agent_name: str,
    message: str,
    scope: str,                   # 'management' or 'project'
    teaparty_home: str,           # path to .teaparty/
    org_home: str | None = None,  # fallback for management-scope lookups

    # Tier split (see unified-launch.md)
    tier: str = 'job',            # 'job' or 'chat'
    worktree: str = '',           # required for job tier
    launch_cwd: str = '',         # required for chat tier (cwd to run in)
    config_dir: str = '',         # where per-launch config is written (chat tier)

    # Session continuity
    resume_session: str = '',     # claude session ID for --resume
    session_id: str = '',
    telemetry_scope: str = '',

    # MCP + bus wiring
    mcp_port: int = 0,            # HTTP MCP server port (0 = no MCP)
    on_stream_event: Callable[[dict], None] | None = None,
    event_bus: Any = None,

    # Heartbeat + children registry
    heartbeat_file: str = '',
    parent_heartbeat: str = '',
    children_file: str = '',
    stall_timeout: int = 1800,

    # Optional overrides — used by CfA to bypass the standard
    # .teaparty/ derivation when it has per-phase PhaseConfig
    settings_override: dict[str, Any] | None = None,
    add_dirs: list[str] | None = None,
    agents_json: str | None = None,
    agents_file: str | None = None,
    stream_file: str = '',
    env_vars: dict[str, str] | None = None,
    permission_mode_override: str = '',
    tools_override: str | None = None,

    # LLM backend (scripted in tests)
    llm_caller: LLMCaller = _default_claude_caller,
) -> ClaudeResult:
```

The function:

1. Calls `compose_launch_worktree()` to write `.claude/` into the worktree
2. Reads agent frontmatter for tool permissions and permission mode
3. Derives the roster JSON if the agent leads a workgroup
4. Builds a sanitized environment (allowlisted env vars only)
5. Instantiates `ClaudeRunner` with the derived configuration
6. Runs the subprocess, streams events, returns `ClaudeResult`
7. Emits a `TURN_COMPLETE` telemetry event via `teaparty.telemetry.record_event`

The launcher is stateless -- it does not cache, track, or persist anything between calls.

---

## CLI Invocation Format

`ClaudeRunner._build_args()` (`teaparty/runners/claude.py`) assembles the subprocess command. Every invocation has this shape:

```bash
claude -p \
  --output-format stream-json \
  --verbose \
  --setting-sources user \
  --permission-mode {mode} \
  --agent {name} \
  --settings {path}                # .claude/settings.json (tool permissions)
  --agents {roster_json}           # if agent leads a workgroup
  --mcp-config {path}              # .mcp.json in the worktree
  --resume {session_id}            # if continuing a conversation
  --add-dir {path}                 # additional visible directories
```

Always present: `--output-format stream-json`, `--verbose`, `--setting-sources user`, `--permission-mode`, `--agent`, `--settings`. The rest are conditional on what `.teaparty/` config declares for that agent.

The prompt is passed via stdin. The process runs to completion, streams events, exits. Multi-turn continuity uses `--resume` with the previous session's Claude session ID. No persistent processes, no NDJSON stdin piping, no warm caching.

Environment variables are stripped to an allowlist (`ClaudeRunner._ENV_ALLOWLIST`) so agent subprocesses do not inherit credentials, tokens, or other sensitive state from the orchestrator.

---

## Worktree Composition

`compose_launch_worktree()` (`teaparty/runners/launcher.py`) writes the `.claude/` directory into an existing worktree without touching the repo's own `CLAUDE.md`. The repo checkout provides project-level instructions; agent-specific configuration is layered on top.

| Worktree file | Source | Notes |
|---------------|--------|-------|
| `.claude/CLAUDE.md` | Already in the repo checkout | Not composed, not touched |
| `.claude/agents/{name}.md` | `{scope}/agents/{name}/agent.md` | Copied; old agent definitions are cleaned first |
| `.claude/skills/{skill}/` | `{scope}/skills/{skill}/` | Symlinked; filtered by agent frontmatter `skills:` allowlist |
| `.claude/settings.json` | `{scope}/settings.yaml` merged with `{scope}/agents/{name}/settings.yaml` | Agent settings win per-key via deep merge |
| `.mcp.json` | Generated | Points to `http://localhost:{port}/mcp/{scope}/{agent}` |

Agent definition resolution (`resolve_agent_definition()`) checks the invocation scope first, then falls back to management scope. A project can override any management-level agent by providing its own version in `.teaparty/project/agents/`.

Skills use the same resolution order: scope-specific first, then management. Only skills listed in the agent's frontmatter `skills:` key are composed. No `skills:` key means no skills.

Settings merge uses `_merge_settings()` which loads the scope-level `settings.yaml` as the base, then deep-merges the agent-level `settings.yaml` on top. The result is written as `.claude/settings.json` and passed via `--settings`.

---

## Session Lifecycle

A session is a worktree. There is a 1:1:1 correspondence between sessions, worktrees, and Claude session IDs. This invariant is structural -- the `Session` dataclass (`teaparty/runners/launcher.py`) captures all three:

```python
@dataclass
class Session:
    id: str                                    # session identifier
    path: str                                  # {scope}/sessions/{id}/
    agent_name: str
    scope: str
    claude_session_id: str = ''                # claude -p --resume value
    conversation_map: dict[str, str] = ...     # request_id -> child session ID
```

### Create

`create_session()` allocates `{scope}/sessions/{session-id}/`, writes `metadata.json` with the agent name and empty conversation map. A git worktree is created inside the session directory at `worktree/`.

### Resume

`load_session()` reads `metadata.json` from the session directory. The stored `claude_session_id` is passed as `--resume` to the launcher. The conversation map is restored for dispatch slot tracking.

### Close

`CloseConversation` (MCP tool) removes the entry from the dispatching agent's conversation map (freeing a slot) and triggers worktree cleanup on the target session.

### Withdraw

Iterates the agent's conversation map, closes each open conversation, cleans up all child sessions recursively.

### Metrics

After each turn, the launcher emits a `TURN_COMPLETE` telemetry event via `teaparty.telemetry.record_event` carrying cost, tokens, duration, and turn metadata. Events are written to the per-scope telemetry event stream (see [Bridge telemetry](../bridge/telemetry.md)) and queried via `/api/telemetry/*` on the bridge. There is no separate `metrics.db` — earlier designs planned one, but the implementation unified on the telemetry event stream.

---

## Stream Processing

Every launch streams JSONL events in real time. `ClaudeRunner.run()` tails stdout line-by-line, persists each line to the stream file, and publishes `STREAM_DATA` events to the `EventBus`.

Stream relay (`teaparty/teams/stream.py`) provides:

- **Deduplication**: `tool_use` and `tool_result` events are deduplicated by ID to prevent double-processing.
- **Classification**: Events are classified by sender type via `_classify_event()` -- distinguishing agent output, tool use, system messages, and non-conversational senders.
- **Bus relay**: `_make_live_stream_relay()` returns a callback that processes each event and relays it to the message bus. This is the baseline for all agents.

The stream callback is passed to `ClaudeRunner` via the `on_stream_event` parameter. `AgentSession.invoke()` wires this up automatically.

---

## Session Health

Two failure modes the launcher detects and recovers from:

### Poisoned Session

`detect_poisoned_session()` scans stream events for `system` events where an MCP server has `status: failed`. When this happens, `--resume` on that session will silently fail forever. The launcher returns an empty session ID so the caller starts fresh on the next invocation.

### Empty Response

`should_clear_session()` checks whether the runner completed with no assistant text. An empty response means the session is dead. The session ID is cleared so the next invocation creates a new session rather than resuming the broken one.

Both checks run after every launch. The caller (typically `AgentSession`) inspects the result and clears `claude_session_id` when either condition is detected.

---

## Max SLA Constraints

The launcher enforces these constraints on every invocation:

- **Genuine binary only.** Invoke via the `claude` binary found on `PATH`. No wrappers, no shims.
- **No OAuth extraction.** Never extract OAuth tokens for direct HTTP use.
- **No throttle circumvention.** Never instrument around Claude Code's built-in rate limiting.
- **Per-agent concurrency limit.** Each dispatching agent's `metadata.json` holds a conversation map (request ID to child session ID). Maximum 3 concurrent conversations per agent (`MAX_CONVERSATIONS_PER_AGENT` in `teaparty/runners/launcher.py`). The fourth `Send` is refused until a slot frees, which forces agents to close conversations when done. This per-agent cap is the only concurrency backpressure in code today — a truly system-wide ceiling bounding total agent processes across all projects has been discussed but is not implemented.
- **CLI sets the pace.** The launcher does not retry, batch, or parallelize beyond what the CLI permits.
- **Stable system prompts.** Agent definitions and settings are deterministic for a given config state.
- **Session resumption.** Use `--resume` rather than reconstructing context from scratch.
- **`--setting-sources user`** on every invocation. Required for Max OAuth authentication.
- **Single user only.**

---

## AgentSession

`AgentSession` (`teaparty/teams/session.py`) is the unified session class for all agent conversations. Every agent type -- office manager, project lead, project manager, configuration lead, proxy -- runs through this single class. There are no per-agent-type session subclasses.

Variable behavior is handled through configuration and hooks, not inheritance:

| Parameter | Purpose |
|-----------|---------|
| `agent_name` | Which agent definition to use |
| `scope` | `'management'` or `'project'` |
| `conversation_type` | How the conversation ID is keyed |
| `dispatches` | Whether to start a `BusEventListener` for Send/Reply |
| `post_invoke_hook` | Called after launch with the response text (e.g. proxy ACT-R processing) |
| `build_prompt_hook` | Overrides default prompt construction (e.g. proxy memory retrieval) |

`AgentSession` manages:

- **Message bus**: Per-agent SQLite bus for conversation history. Human and agent messages are stored and retrieved for context building.
- **Context building**: `build_context()` reconstructs the conversation from bus messages, filtering out non-conversational senders.
- **State persistence**: `save_state()` / `load_state()` read and write session metadata through the launcher's `create_session()` / `load_session()`.
- **Dispatch infrastructure**: Agents with rosters get a `BusEventListener` that handles `Send`, `Reply`, and `CloseConversation` MCP calls. The listener's `spawn_fn` creates child sessions with worktrees and routes through the launcher.

The dispatch spawn function (`_ensure_bus_listener`) creates child sessions, allocates worktrees, checks slot availability, and recursively registers spawn functions for child agents that themselves dispatch. This is how the full team hierarchy -- OM to PM to project lead to workgroup agents -- operates through a single session class.

---

## Key Files

| File | Purpose |
|------|---------|
| `teaparty/runners/launcher.py` | Unified launcher: `launch()`, session CRUD, worktree composition, metrics |
| `teaparty/runners/claude.py` | `ClaudeRunner` -- subprocess wrapper, arg builder, stream processor |
| `teaparty/teams/session.py` | `AgentSession` -- unified session class for all agent types |
| `teaparty/teams/stream.py` | Stream event classification, deduplication, bus relay |
| `teaparty/messaging/listener.py` | `BusEventListener` -- handles Send/Reply/Close for dispatching agents |
| `teaparty/config/config_reader.py` | Agent frontmatter reader |
| `teaparty/config/roster.py` | Roster derivation from workgroup/project config |
