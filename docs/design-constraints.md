# Design Constraints — Claude Code Integration

Confirmed facts about Claude Code's behavior that constrain TeaParty's architecture. Each was discovered through experimentation (issue #390, 2026-04-08/09).

## Tool Control

| Constraint | Detail |
|-----------|--------|
| `--tools ''` kills ALL tools including MCP | Use explicit comma-separated list, never empty string |
| `--tools <list>` controls builtins only | MCP tools unaffected by `--tools` |
| `--settings` permissions `allow` auto-approves tools | Does not hide tools — only skips the approval prompt |
| `permissionMode: acceptEdits` covers file edits only | MCP tool calls still require explicit approval or `allow` list |

## MCP Server Configuration

| Constraint | Detail |
|-----------|--------|
| Project-scoped `.mcp.json` requires interactive approval | Silently skipped in `-p` mode — servers never connect |
| `--mcp-config` bypasses approval | Works in `-p` mode unconditionally |
| `--mcp-config` is NOT persisted in the session | Must be passed on every invocation, including `--resume` |
| `--strict-mcp-config` forces MCP rediscovery on `--resume` | Without it, resumed sessions use the original MCP config |
| `--resume` preserves stale tool state | A session created with broken MCP is permanently poisoned without `--strict-mcp-config` |
| `json_response=True` required for HTTP MCP transport | Claude Code disconnects immediately when receiving SSE for init response |
| FastMCP `StreamableHTTPSessionManager` requires long-lived async context | Cannot lazily create per-agent server instances inside request handlers |

## Agent Teams and SendMessage

| Constraint | Detail |
|-----------|--------|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables `SendMessage` | Cannot be blocked by `--tools` — always available when agent teams are enabled |
| `SendMessage` bypasses TeaParty's bus listener | Routes through Claude Code's internal agent system, not TeaParty's dispatch |
| Multiple agents in `.claude/agents/` may enable `SendMessage` | Claude Code's agent discovery contributes to team tool availability |

## Environment

| Constraint | Detail |
|-----------|--------|
| `CLAUDECODE=1` suppresses MCP subprocess startup | Claude Code's anti-recursion guard; set automatically in subprocess env |
| Claude Code re-sets `CLAUDECODE` internally | Stripping from parent env is necessary but not always sufficient |

## Architecture Decisions (derived from constraints)

**Single HTTP MCP server in the bridge process.** One FastMCP instance, one session manager, mounted on the bridge's aiohttp event loop. Per-agent tool filtering via ASGI response filter on `tools/list`. No threads, no per-agent subprocesses, no sockets between MCP and bus listener.

**`--mcp-config` + `--strict-mcp-config` on every invocation.** The only reliable way to ensure MCP tools are available regardless of session state.

**Agent frontmatter as single source of truth.** The `tools:` field drives three things: `--tools` (builtin visibility), ASGI filter (MCP tool visibility), `--settings` permissions `allow` (auto-approval).

**Direct bus listener calls via in-process registry.** The MCP Send handler looks up the bus listener's spawn function by agent name (via contextvars) and calls it directly. No unix sockets, no env vars, no IPC.
