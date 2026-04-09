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

### Remaining questions

1. Does `--mcp-config` work with `--resume`? Or does `--resume` ignore it (finding #3)? Need to test.
2. Does path-based routing work now that we have `json_response=True`? The agent path crashed earlier due to `asyncio.run()` in an async context — that's fixed. Need to verify the lazy session manager startup works.
3. If `--resume` ignores `--mcp-config`, we need `--strict-mcp-config` to force it. Need to verify this flag works with HTTP transport on resume.
