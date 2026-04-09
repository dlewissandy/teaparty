# MCP Server Architecture — Experiment Journal

## Problem Statement

Dispatched agents need MCP tools (Send, Reply, ListTeamMembers, etc.) to participate in TeaParty's hierarchical dispatch. The original architecture spawned a separate MCP server subprocess per agent. After the issue #390 restructure, the OM couldn't reach its MCP tools at all.

## Findings (chronological)

### 1. CLAUDECODE=1 suppresses MCP subprocess startup

**Date:** 2026-04-08

When Claude Code runs, it sets `CLAUDECODE=1` in its environment. Child processes that inherit this have MCP server startup suppressed — Claude Code's anti-recursion guard. Since the bridge server runs inside a Claude Code session, all OM processes inherited `CLAUDECODE=1`.

**Fix attempted:** Strip `CLAUDECODE` from `ClaudeRunner._build_env()`.

**Result:** This alone didn't fix it — other issues masked the effect.

### 2. `--tools ''` kills ALL tools including MCP

**Date:** 2026-04-08

The OM passed `--tools ''` to disable builtin tools (Read/Write/Bash) while keeping MCP tools. But Claude Code interprets `--tools ''` as "disable ALL tools including MCP." The OM had zero tools and hallucinated every tool call.

**Confirmed:** `--tools` with a specific comma-separated list DOES work — it disables unlisted builtins but keeps MCP tools. The empty string is the problem.

**Fix:** Remove `--tools ''`. Use `--tools Bash,WebSearch,ToolSearch` (explicit list from frontmatter).

### 3. `--resume` preserves stale MCP state

**Date:** 2026-04-08

When Claude Code resumes a session via `--resume`, it uses the MCP config from the ORIGINAL session creation. New `--mcp-config`, `--strict-mcp-config`, and workspace `.mcp.json` changes are ignored for tool discovery. This means every MCP config change requires a fresh session.

**Implication:** Any session created when MCP was broken is permanently poisoned. `/clear` must reset `claude_session_id` to force a fresh session.

**Fix:** MCP failure detection clears `claude_session_id` when system init shows `"status": "failed"`.

### 4. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables unblockable SendMessage

**Date:** 2026-04-08

We set this env var for all dispatched agents. It enables Claude Code's native agent teams, which includes `SendMessage` — a builtin that **cannot be blocked by `--tools`**. The OM found `SendMessage` via ToolSearch and used it instead of `mcp__teaparty-config__Send`. Messages went to Claude Code's internal routing (a black hole) instead of TeaParty's bus listener.

**Source:** Claude Code docs confirm: "Team coordination tools such as SendMessage and the task management tools are always available to a teammate even when tools restricts other tools."

**Fix:** Remove `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` from `_build_env()`.

### 5. Project-scoped .mcp.json requires approval that -p mode can't give

**Date:** 2026-04-09  
**This is the current blocker.**

Claude Code requires explicit user approval before loading MCP servers from project-scoped `.mcp.json` files. This approval is stored in `~/.claude.json` under the project path. In `-p` (print/pipe) mode, there is no interactive prompt — the approval dialog is skipped.

**Evidence:**
- The OM workspace has no entry in `~/.claude.json` → servers silently skipped
- The main repo has `enabledMcpjsonServers: []` → no servers enabled
- The system init event shows Gmail and Calendar (user-scoped) but NO teaparty-config
- The HTTP server at localhost:8082 responds correctly to curl
- Claude Code never attempts to connect

**Key insight:** The `-p` flag docs say "The workspace trust dialog is skipped when Claude is run with the -p mode. Only use this flag in directories you trust." But skipping the trust dialog doesn't mean auto-approving MCP servers — it means they're silently ignored.

**Possible paths forward:**
1. Pre-populate `~/.claude.json` with approval entries for agent workspaces
2. Use `--mcp-config` to bypass project-scoped approval (back to per-agent config, but via HTTP URL not subprocess)
3. Use `claude mcp add --scope local` to register the server at local scope for each workspace
4. Register as user-scoped (available to all projects) — but then all agents see all tools

## Architecture Decisions

### What works

- **One HTTP MCP server** started by the bridge at boot (port 8082) — server responds correctly
- **Per-agent tool filtering** via `create_server(agent_tools=...)` — correctly filters to frontmatter allowlist
- **Builtin tool control** via `--tools` with explicit comma-separated list from frontmatter
- **`json_response=True`** on FastMCP — returns JSON instead of SSE, which Claude Code expects
- **Agent frontmatter as single source of truth** for tool allowlists — no hardcoded Python lists

### What doesn't work

- **Path-based routing** for per-agent filtering — FastMCP's `StreamableHTTPSessionManager` requires a long-lived async context manager that can't be lazily started inside request handlers
- **Project-scoped .mcp.json** — requires interactive approval that `-p` mode can't provide
- **`--mcp-config` with `--strict-mcp-config`** — worked technically but was fragile (temp files, stale sessions)

### What we haven't tried

- **`--mcp-config` with HTTP URL** — `--mcp-config` takes a JSON file/string. Could we pass the HTTP config directly? This bypasses project-scope approval since it's a CLI flag, not a `.mcp.json` file.
- **Pre-populating `~/.claude.json`** — write approval entries for agent workspaces before spawning
- **User-scoped MCP server** — `claude mcp add --scope user --transport http teaparty-config http://localhost:8082/mcp` — available everywhere, no per-project approval needed

## Current State (2026-04-09)

### Code changes made
- HTTP MCP server with path-based routing implemented (`create_http_app`)
- `compose_mcp_config` writes HTTP URLs to `.mcp.json`
- `ClaudeRunner.run()` reads agent frontmatter for `--tools` builtins
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` removed from env
- `CLAUDECODE` stripped from env
- `--mcp-config`/`--strict-mcp-config` removed from ClaudeRunner
- All hardcoded permission lists removed from team sessions
- `dispatch.py` entry point deleted

### Blocker
Claude Code in `-p` mode silently ignores project-scoped `.mcp.json` MCP servers because the approval dialog is skipped. The HTTP MCP server works but Claude Code never connects to it.

## Experiment 6: --mcp-config with HTTP URL

**Date:** 2026-04-09

### Hypothesis

`--mcp-config` is a CLI flag, not a project-scoped file. Claude Code should load MCP servers from `--mcp-config` without requiring interactive approval, even in `-p` mode. If the config points to an HTTP URL instead of a stdio command, Claude Code will connect to the shared HTTP MCP server.

### Test

```bash
# Write HTTP config to temp file
echo '{"mcpServers":{"teaparty-config":{"type":"http","url":"http://localhost:8082/mcp"}}}' > /tmp/test-mcp-http.json

# Run from OM workspace with minimal env (no CLAUDECODE etc.)
claude -p --output-format stream-json --verbose \
  --mcp-config /tmp/test-mcp-http.json \
  <<< "list your mcp tools"
```

**Expected:** teaparty-config appears in `mcp_servers` with `"status": "connected"`, and all 42 tools are listed.

### Result

**CONFIRMED.** `--mcp-config` with HTTP URL works in `-p` mode.

```
MCP: [{"name": "teaparty-config", "status": "connected"}]
TeaParty tools: 42
```

The key difference from `.mcp.json`: CLI-provided `--mcp-config` bypasses the project-scope approval requirement. Claude Code loads it unconditionally.

### Implications for implementation

1. **Stop writing `.mcp.json` to workspaces.** It requires approval that `-p` mode can't provide.
2. **`ClaudeRunner` passes `--mcp-config` with the HTTP URL.** The URL includes the agent scope path for per-agent filtering: `http://localhost:8082/mcp/management/{agent}`.
3. **Use `--strict-mcp-config`** to prevent Claude Code from also loading the workspace's `.mcp.json` (which would fail approval and produce confusing behavior).
4. **`compose_mcp_config` becomes unnecessary** — the runner constructs the config at invocation time from the agent name and scope.

## Experiment 6a: Does --mcp-config persist across --resume?

**Date:** 2026-04-09

### Test

1. Create fresh session with `--mcp-config` (HTTP URL) → count tools
2. Resume that session WITH `--mcp-config` → count tools
3. Resume that session WITHOUT `--mcp-config` → count tools

### Result

```
Session 1 (fresh + --mcp-config):        teaparty_tools=42
Session 2 (resume + --mcp-config):       teaparty_tools=42
Session 3 (resume, no --mcp-config):     teaparty_tools=0
```

**Conclusion:** `--mcp-config` must be passed on EVERY invocation, including resumes. It is not persisted in the session. If omitted on resume, the MCP server is lost.

**Implication:** `ClaudeRunner` must always pass `--mcp-config` — not just on fresh sessions. This is actually good: it means every invocation gets the current config. No stale sessions.

## Experiment 6b: Does path-based agent filtering work via --mcp-config?

**Date:** 2026-04-09

### Test

Pass `--mcp-config` with URL `http://localhost:8082/mcp/management/office-manager` (agent-scoped path).

### Result

```
MCP: [{"name": "teaparty-config", "status": "failed"}]
TeaParty tools: 0
```

**FAILED.** The agent path crashes because the lazily-created agent server's `StreamableHTTPSessionManager` isn't properly initialized. The session manager requires a long-lived async context manager (`mgr.run()`) that can't be started inside a request handler.

**Conclusion:** Path-based routing doesn't work with FastMCP's session manager architecture. We need a different approach for per-agent filtering.

**Options:**
- A. Use one server at `/mcp` with all tools. Filter via `--tools` (builtins) and `--settings` permissions (MCP). Accept that agents SEE all MCP tools but can only CALL their allowed ones.
- B. Pre-create all known agent servers at startup (not lazy). Walk the agent directories, create a server per agent, start all session managers in the lifespan.
- C. Write a custom ASGI handler that doesn't use FastMCP's session manager — intercept `tools/list` JSON-RPC responses and filter them.

## Experiment 6c: Does --strict-mcp-config force MCP rediscovery on resume?

**Date:** 2026-04-09

### Test

1. Create session WITHOUT `--mcp-config` (no MCP tools)
2. Resume with `--mcp-config` + `--strict-mcp-config`

### Result

```
Session 1 (no mcp):                                    tools=0
Session 2 (resume + --mcp-config + --strict-mcp-config): tools=42
```

**CONFIRMED.** `--strict-mcp-config` forces Claude Code to use the provided config even on resume, overriding the session's original (empty) MCP state.

**Implication:** We should always pass both `--mcp-config` and `--strict-mcp-config`. This guarantees every invocation gets the current MCP config regardless of session state. Combined with finding 6a, this means we never have stale MCP.

## Summary of confirmed facts

| # | Fact | Source |
|---|------|--------|
| 1 | `--tools ''` kills all tools including MCP | Experiment 2 |
| 2 | `--tools <list>` controls builtins only; MCP unaffected | Experiment 2 |
| 3 | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables unblockable SendMessage | Claude Code docs |
| 4 | Project-scoped `.mcp.json` requires approval; silently skipped in `-p` mode | Experiment 5 |
| 5 | `--mcp-config` bypasses approval; works in `-p` mode | Experiment 6 |
| 6 | `--mcp-config` must be passed on every invocation (not persisted in session) | Experiment 6a |
| 7 | Path-based agent routing doesn't work (FastMCP session manager limitation) | Experiment 6b |
| 8 | `--strict-mcp-config` forces MCP rediscovery on resume | Experiment 6c |
| 9 | `json_response=True` required for HTTP MCP (Claude Code disconnects on SSE) | Experiment earlier today |

## Decision: ASGI response filter for per-agent tool filtering

**Date:** 2026-04-09

### Why not the other options

- **Accept all tools visible:** Wastes context. 42 tool descriptions for an agent that needs 5. Not acceptable.
- **Pre-create all agent servers at startup:** Agents and their tool allowlists can be created or modified dynamically via the UI. Pre-creation can't handle runtime changes.
- **Path-based routing with multiple FastMCP instances:** Failed (Experiment 6b). FastMCP's `StreamableHTTPSessionManager` requires a long-lived async context manager per instance. Lazy creation inside request handlers crashes.

### Chosen approach: ASGI response filter

Run ONE FastMCP instance with all 42 tools and one session manager. Intercept the `tools/list` JSON-RPC response at the ASGI layer and filter it based on the URL path.

**How it works:**

1. Agent's `--mcp-config` points to `http://localhost:8082/mcp/management/office-manager`
2. ASGI middleware receives `POST /mcp/management/office-manager`
3. Middleware parses the path → extracts `(management, office-manager)`
4. Middleware rewrites path to `/mcp` and forwards to the single FastMCP app
5. FastMCP processes the request normally (init, tools/list, tools/call, etc.)
6. **For `tools/list` responses only:** middleware intercepts the JSON response body, reads the agent's frontmatter allowlist via `_load_agent_tools()`, removes tools not in the allowlist, re-serializes, and sends the filtered response
7. All other methods (init, tools/call, prompts/list, etc.) pass through unmodified

**Why this works:**

- One session manager, one lifespan — no lazy startup problems
- `json_response=True` means responses are plain JSON, trivial to intercept and rewrite
- Agent allowlist is read on each `tools/list` request — handles dynamic agent changes
- No FastMCP internals hacked — filtering is purely at the HTTP layer
- Path routing is just string parsing, not multiple Starlette apps

**Constraints:**

- `tools/call` is NOT filtered — if an agent somehow calls a tool it shouldn't have, it succeeds. This is acceptable because the agent can only call tools it discovered via `tools/list`, which was already filtered. The `--tools` flag blocks builtins. The only risk is a resumed session that cached a stale tool list, and `--strict-mcp-config` handles that.

## Experiment 7: ASGI response filter for tools/list

**Date:** 2026-04-09

### Hypothesis

We can wrap the single FastMCP Starlette app in an ASGI middleware that:
1. Forwards all requests to FastMCP unchanged (path rewritten to `/mcp`)
2. For responses to `tools/list` requests on agent paths, intercepts the JSON body and filters the tools array

Since `json_response=True`, the response is a single JSON object (not SSE), making interception straightforward.

### Test plan

1. Implement the ASGI filter middleware in `create_http_app()`
2. Start the server, send `initialize` + `tools/list` to `/mcp/management/office-manager`
3. Verify: init returns full capabilities, tools/list returns only the OM's 22 allowed tools (not all 42)
4. Test via `claude -p --mcp-config` to verify Claude Code sees only the filtered tools

### Result

**CONFIRMED.** ASGI response filter works end-to-end.

```
/mcp via claude -p:                          status=connected, tools=42
/mcp/management/office-manager via claude -p: status=connected, tools=22
```

One FastMCP instance, one session manager. `tools/list` responses on agent paths are filtered. All other methods pass through. Both paths work with `--mcp-config` + `--strict-mcp-config` in `-p` mode.

### Implementation notes

The ASGI filter:
- Peeks at request body to detect `tools/list` method
- For tools/list: buffers response, parses JSON, filters tools array, rewrites Content-Length
- For everything else: passes through unchanged
- Agent allowlist loaded from frontmatter and cached per scope/agent key

## Revised implementation plan

Based on all experiments, the final architecture is:

1. **Bridge starts one HTTP MCP server** at port 8082 with ASGI response filter middleware
2. **One FastMCP instance** with all tools, one session manager, one lifespan
3. **URL paths** encode agent scope: `/mcp/management/{agent}`, `/mcp/{project}/{agent}`
4. **`tools/list` responses** are filtered per-agent based on frontmatter allowlist
5. **`ClaudeRunner` always passes `--mcp-config` + `--strict-mcp-config`** with the agent-scoped HTTP URL
6. **`ClaudeRunner` passes `--tools`** with builtins from agent frontmatter
7. **Remove `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`** from env (kills SendMessage)
8. **Remove `compose_mcp_config`** — runner constructs config inline
9. **Interactive session** uses `--mcp-config` pointing to `/mcp` (all tools)

## Experiment 8: Permission mode and tool approval in -p mode

**Date:** 2026-04-09

### Problem

The OM has the correct 22 MCP tools visible but can't call them: "Claude requested permissions to use mcp__teaparty-config__Send, but you haven't granted it yet."

### Hypothesis

`permissionMode: acceptEdits` (from agent frontmatter) only auto-approves file edit operations, not MCP tool calls. MCP tools need explicit approval via the `--settings` permissions `allow` list.

### Test

Pass the agent's frontmatter `tools:` list as `--settings '{"permissions":{"allow":[...]}}'`. This should auto-approve the listed tools without prompting.

### Rationale

This is not special-casing. The runner reads the frontmatter `tools:` field (already loaded for `--tools` builtins and MCP filtering) and passes it as the permissions allowlist. One source of truth — the frontmatter — drives three things:
1. `--tools` flag (builtins visible to Claude Code)
2. HTTP MCP path filter (MCP tools visible via tools/list)
3. `--settings` permissions `allow` (tools auto-approved without prompting)

### Result

**PARTIAL SUCCESS.** The permissions allow list works — Send was called without prompting. But the call failed:

```
"Neither DISPATCH_BUS_PATH nor SEND_SOCKET set — cannot send."
```

The MCP Send handler needs socket paths to route messages to the bus listener. Previously these were passed as env vars to the MCP subprocess (when it was a stdio subprocess per agent). Now the MCP server is a shared HTTP server started by the bridge — it runs in the bridge process, not in the agent's process. The socket paths from `_ensure_bus_listener()` never reach the HTTP server.

### Analysis

The Send/Reply/CloseConversation handlers in `teaparty/mcp/tools/messaging.py` read socket paths from `os.environ`:
- `SEND_SOCKET` — path to the bus listener's send unix socket  
- `REPLY_SOCKET` — path to the bus listener's reply unix socket
- `DISPATCH_BUS_PATH` — alternative: path to the sqlite bus for bus-based transport

These env vars were set per-agent when the MCP server was a subprocess. With a shared HTTP server, there's one process for all agents — it can't have per-agent env vars.

### The fundamental problem

The Send handler needs to know WHICH bus listener to route to. Different agents have different bus listeners (the OM has one, the config lead has another). The socket paths are per-session, not per-server. A shared HTTP server can't use per-process env vars for per-session routing.

## Experiment 9: How to route Send/Reply through the shared HTTP server

**Date:** 2026-04-09

### Options

**A. Pass socket paths as tool parameters.** The agent includes `send_socket` as an argument to the Send MCP tool call. This leaks infrastructure details into the agent's tool API — ugly.

**B. Pass socket paths as HTTP headers.** Claude Code doesn't support custom headers per MCP request. Rejected.

**C. Pass socket paths in the MCP session init.** The `clientInfo` in the initialize request could include custom metadata. But we don't control what Claude Code sends.

**D. Pass socket paths as env vars to the Claude process, which passes them as HTTP headers.** Claude Code doesn't forward env vars to MCP HTTP requests.

**E. The bridge's bus listener registers itself with the HTTP MCP server.** The bridge starts the bus listener and registers its socket paths with the MCP server keyed by agent name. When the Send handler runs, it looks up the socket paths by the agent scope from the URL path. The ASGI middleware already knows the agent scope — it could inject it into the request context.

**F. The Send handler routes through the bridge directly.** Since the HTTP server runs inside the bridge process (same Python process via threading), the Send handler can access the bridge's bus listeners directly through a shared registry — no sockets needed.

### Hypothesis

Option F is the cleanest. The HTTP MCP server runs in the bridge process. The bridge owns the bus listeners. A shared registry (module-level dict) maps agent names to bus listener instances. The Send handler looks up the listener by agent name (extracted from the URL path) and calls it directly — no unix sockets, no env vars.

### Test plan

1. Create a module-level registry: `{agent_name: BusEventListener}`
2. When the bridge starts a bus listener for an agent, register it
3. Modify the ASGI middleware to inject the agent scope into a request-scoped context
4. Modify the Send handler to look up the bus listener from the registry instead of reading env vars
5. Test: OM calls Send → handler looks up 'office-manager' → finds bus listener → routes message

## Decision: Single event loop — mount MCP inside the bridge

**Date:** 2026-04-09

### The problem

The HTTP MCP server runs in a background thread (uvicorn). The bus listener runs on the bridge's asyncio event loop (aiohttp). The Send handler needs to call the bus listener. Cross-thread calls into a non-thread-safe async object require `run_coroutine_threadsafe` — fragile and conceptually unclear.

### The decision

Mount the MCP ASGI app inside the bridge's existing aiohttp server. One event loop, one process. The MCP handlers and bus listeners share the same event loop. Direct async function calls, no threads, no sockets.

### Why

| Criterion | Two event loops (thread) | One event loop |
|-----------|-------------------------|----------------|
| **Robustness** | Cross-thread calls; race conditions if bus listener isn't thread-safe | Single-threaded async; no races |
| **Conceptual clarity** | Two web frameworks, thread boundary, `run_coroutine_threadsafe` | One process, one loop, direct calls |
| **Latency** | Thread scheduling + possible GIL contention | Direct async call, zero overhead |

### How

aiohttp can mount ASGI sub-applications. The MCP Starlette app becomes a route on the bridge's aiohttp server:

```python
# In bridge/server.py
from aiohttp_asgi import ASGIApplicationServer
from teaparty.mcp.server.main import create_filtering_app

mcp_app = create_filtering_app()
app.router.add_route('*', '/mcp/{path:.*}', ASGIApplicationServer(mcp_app))
```

Or we use aiohttp's built-in `app.router.add_route` with a raw handler that delegates to the ASGI app.

### What changes

- `teaparty/bridge/__main__.py` — remove threading, remove uvicorn. Mount MCP inside aiohttp.
- `teaparty/bridge/server.py` — add MCP route
- `teaparty/mcp/server/main.py` — `create_filtering_app()` returns the ASGI app (no uvicorn, no `run()`)
- Send/Reply handlers — replace socket reads with direct bus listener calls via a shared registry
- Bus listener stays as-is (async, single-threaded — correct for one event loop)

### What stays the same

- The ASGI response filter for tools/list
- The agent frontmatter as source of truth for tool allowlists
- `--mcp-config` + `--strict-mcp-config` on every ClaudeRunner invocation
- `--tools` for builtin filtering
- `--settings` permissions for auto-approval

## Experiment 9: Single event loop + direct bus listener registry (Option F)

**Date:** 2026-04-09

### What we're doing

Two changes in one commit because they're interdependent:

1. **Mount MCP inside the bridge's aiohttp server** (single event loop)
2. **Replace socket-based Send/Reply routing with direct bus listener calls** (Option F)

### Why they're coupled

Option F (direct registry) requires the MCP handlers and bus listeners to share the same process and event loop. The single event loop decision (mounting MCP inside aiohttp) is what makes Option F possible. Doing one without the other is pointless:

- Single event loop without Option F: MCP is in-process but still uses sockets to talk to the bus listener sitting right next to it. Sockets to yourself.
- Option F without single event loop: Direct calls from the uvicorn thread into the bus listener's event loop. Cross-thread, race conditions, `run_coroutine_threadsafe`. Fragile.

Together: MCP handlers call bus listener functions directly via `await`. Same event loop, same thread, zero overhead. The sockets were only needed when the MCP server was a separate process.

### What gets removed

- Unix socket creation for Send/Reply/CloseConversation
- Socket connection in `teaparty/mcp/tools/messaging.py` (`_default_send_post`, `_default_reply_post`, `_default_close_conv_post`)
- `SEND_SOCKET`, `REPLY_SOCKET`, `CLOSE_CONV_SOCKET` env vars
- `_mcp_env_to_args` helper
- Threading for the MCP server in `bridge/__main__.py`
- uvicorn dependency for the bridge MCP server (remains for standalone `main.py` CLI)

### What gets added

- Module-level bus listener registry: `{agent_name: BusEventListener}`
- Bridge registers each bus listener when created
- MCP Send/Reply handlers look up the listener by agent name from the registry
- aiohttp route that delegates to the MCP ASGI app
- Agent name injected into request context by the ASGI middleware (already parsed from URL path)

### Hypothesis

With the MCP server on the same event loop as the bus listener, Send will call the bus listener's spawn function directly. The bus listener spawns the target agent asynchronously. The Send handler returns the result. No sockets, no env vars, no cross-process IPC.

### Test plan

1. Implement the registry and aiohttp mounting
2. Restart bridge, clear OM session
3. OM calls Send('pybayes-lead', 'Tell me a joke')
4. Verify: bus listener receives the call, spawns pybayes-lead, returns result
5. Verify: no SEND_SOCKET env var needed anywhere

### Result (single event loop)

**CONFIRMED.** MCP server mounted inside the bridge's aiohttp server on the same event loop. No threading, no separate port.

- Bridge port 9000 serves both the dashboard and MCP at `/mcp`, `/mcp/{scope}/{agent}`
- aiohttp-to-ASGI bridge handler forwards requests to FastMCP's Starlette app
- Session manager started in `_on_startup`, cleaned in `_on_cleanup`
- OM sees 22 filtered MCP tools (correct)
- `--mcp-config` URL now points to `http://localhost:9000/mcp/management/office-manager`

### Remaining: Option F — direct bus listener calls

Send still fails with "Neither DISPATCH_BUS_PATH nor SEND_SOCKET set." The MCP Send handler reads socket paths from `os.environ`, but sockets no longer exist. The handler needs to call the bus listener directly through the in-process registry.

## Experiment 9b: Wire Send handler to bus listener registry

**Date:** 2026-04-09

### What we're doing

Replace the socket-based Send/Reply routing in `teaparty/mcp/tools/messaging.py` with direct calls to the bus listener via `teaparty/mcp/registry.py`.

### How

1. When the bridge starts a bus listener for an agent (in `_ensure_bus_listener`), register its `spawn_fn` in the registry
2. The ASGI middleware already knows the agent name from the URL path. It needs to make the agent name available to the tool handler.
3. The Send handler looks up the spawn function from the registry by agent name and calls it directly: `await spawn_fn(member, composite, context_id)`
4. No sockets, no env vars, no IPC — direct async function call on the same event loop

### The context-passing problem

The Send MCP tool handler (`send_handler` in messaging.py) needs to know which agent is calling so it can look up the right bus listener. The agent name comes from the URL path (parsed by the ASGI middleware). But FastMCP's tool handler signature is fixed — it receives the tool parameters, not request metadata.

Options:
- **contextvars**: Set a context variable in the ASGI middleware before forwarding. The tool handler reads it. Thread-safe and async-safe.
- **Env var per-request**: Not possible (shared process).
- **Custom header**: FastMCP doesn't expose request headers to tool handlers.

**Decision:** Use `contextvars`. The ASGI middleware sets `current_agent_scope` before each request. The Send handler reads it.

### Test plan

1. Implement contextvars for agent scope
2. Modify Send handler to read from registry via contextvars
3. Register OM's spawn_fn when bus listener starts
4. OM calls Send('pybayes-lead', 'Tell me a joke')
5. Verify: spawn_fn receives the call, spawns pybayes-lead
