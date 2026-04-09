# MCP Server Architecture

## Problem

Dispatched agents need MCP tools (Send, Reply, ListTeamMembers, etc.) to participate in TeaParty's hierarchical dispatch. The previous architecture spawned a separate MCP server subprocess per agent via Claude Code's `--mcp-config` flag. This broke for multiple reasons:

- `CLAUDECODE=1` env var suppresses MCP subprocess startup in nested Claude Code processes
- `--tools ''` (used to hide builtins) also kills MCP tools
- `--resume` preserves stale tool state from the original session
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables Claude Code's builtin `SendMessage` which bypasses TeaParty's bus listener and **cannot be blocked** by `--tools`
- Per-agent stdio MCP subprocesses are wasteful — N agents = N server processes running identical code

## Design

### One HTTP MCP server, path-based per-agent filtering

The bridge starts a single HTTP MCP server at boot. All Claude Code sessions — interactive and dispatched — connect to it over HTTP. The URL path determines which tools are visible.

```
http://localhost:8082/mcp                           # all tools (interactive session)
http://localhost:8082/mcp/management/{agent}        # management-scoped agent
http://localhost:8082/mcp/{project}/{agent}         # project-scoped agent
```

Each path returns only the tools listed in that agent's frontmatter `tools:` field. The server caches filtered FastMCP instances per path after first creation.

### Tool resolution and scope layering

Agent tool allowlists come from the `tools:` field in the agent's frontmatter (`agent.md`). Resolution follows the same scope chain as `config_reader.merge_catalog`:

1. **Project scope**: `{project_dir}/.teaparty/project/agents/{agent}/agent.md`
2. **Management scope**: `.teaparty/management/agents/{agent}/agent.md`

Project-level definitions override management-level definitions of the same name. A project can define its own `auditor` agent with a different tool allowlist than the management `auditor`.

### Builtin tool control

The frontmatter `tools:` field lists both MCP tools (prefixed `mcp__teaparty-config__`) and builtin tools (Bash, Read, Edit, etc.). The runner separates them:

- **MCP tools**: Controlled by the HTTP server's per-agent filtering. The agent only sees the MCP tools in its allowlist.
- **Builtin tools**: Passed to Claude Code's `--tools` flag. Only the builtins listed in the frontmatter are available. `ToolSearch` is always included so deferred tools can be discovered.

This means `SendMessage` (a Claude Code builtin not in any agent's frontmatter) is never available.

### .mcp.json per agent

`compose_mcp_config` writes a `.mcp.json` to each agent's worktree pointing to the scoped URL:

```json
{
  "mcpServers": {
    "teaparty-config": {
      "type": "http",
      "url": "http://localhost:8082/mcp/management/office-manager"
    }
  }
}
```

The interactive session's `.mcp.json` (repo root) points to the unscoped path:

```json
{
  "mcpServers": {
    "teaparty-config": {
      "type": "http",
      "url": "http://localhost:8082/mcp"
    }
  }
}
```

### Environment changes

- **Remove** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` from `ClaudeRunner._build_env()`. This disables `SendMessage`.
- **Remove** `CLAUDECODE` stripping — no longer needed since we don't spawn MCP subprocesses.
- **Remove** `--mcp-config`, `--strict-mcp-config` — agents use workspace `.mcp.json` natively.

## Implementation

### Files to change

| File | Change |
|------|--------|
| `teaparty/mcp/server/main.py` | Add `create_http_app()` that builds a Starlette app with path-based routing. Each path lazily creates a filtered FastMCP instance. |
| `teaparty/bridge/__main__.py` | Start the HTTP MCP server in a background thread on port 8082. |
| `teaparty/cfa/agent_spawner.py` | `compose_mcp_config` writes HTTP URL with scope (`management/{agent}` or `{project}/{agent}`). |
| `teaparty/runners/claude.py` | Read agent frontmatter, extract builtins for `--tools`. Remove `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`. Remove `CLAUDECODE` pop. Remove `--mcp-config`/`--strict-mcp-config` logic. |
| `teaparty/teams/office_manager.py` | Remove all `mcp_config` plumbing, `_build_mcp_config`, `_mcp_env_to_args`. |
| `teaparty/teams/config_lead.py` | Same cleanup. |
| `teaparty/teams/project_lead.py` | Same cleanup. |
| `teaparty/teams/project_manager.py` | Same cleanup. |
| `teaparty/cfa/agent_pool.py` | Remove `mcp_config` parameter and `--mcp-config` flag construction. |
| `.mcp.json` | Change to HTTP transport pointing to `http://localhost:8082/mcp`. |

### Files to delete

| File | Reason |
|------|--------|
| `teaparty/mcp/server/dispatch.py` | No longer needed — one server, no dispatch variant. |

### What stays the same

- `create_server(agent_tools=...)` — still the core tool registration, now called per-path
- `_load_agent_tools(agent_name)` — still reads frontmatter, extended to accept scope
- Agent frontmatter `tools:` field — still the single source of truth
- Bus listener sockets — still used for Send/Reply routing (passed as env vars to the Claude process, read by the MCP server via `os.environ`)

## Sequence: agent dispatched by the bridge

```
1. Bridge receives user message
2. Bridge calls OfficeManagerSession.invoke()
3. invoke() calls compose_mcp_config(worktree, 'office-manager', scope='management')
   → writes .mcp.json: {"type": "http", "url": "http://localhost:8082/mcp/management/office-manager"}
4. invoke() calls ClaudeRunner(lead='office-manager', ...)
5. ClaudeRunner.run() reads office-manager frontmatter:
   tools: Bash, WebSearch, WebFetch, mcp__teaparty-config__Send, ...
6. Separates: builtins=[Bash, WebSearch, WebFetch, ToolSearch]
              mcp=[Send, Reply, ListTeamMembers, ...]
7. Passes --tools Bash,WebSearch,WebFetch,ToolSearch to claude -p
8. Claude Code starts, reads .mcp.json, connects to http://localhost:8082/mcp/management/office-manager
9. HTTP server returns tools/list filtered to [Send, Reply, ListTeamMembers, ...]
10. Agent sees ONLY: Bash, WebSearch, WebFetch, ToolSearch + Send, Reply, ListTeamMembers, ...
11. SendMessage does not exist (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS not set)
12. Agent calls mcp__teaparty-config__Send → bus listener → spawns target agent
```
