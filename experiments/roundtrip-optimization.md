# Dispatch Round-Trip Optimization

Goal: reduce hierarchical dispatch round-trip by >50% (baseline ~28s for 2-level dispatch below OM).

## Problem Decomposition

Three-level dispatch: Human → OM → config-lead → project-specialist → result bubbles back.
Each level pays the full cost of a `claude -p` lifecycle. 99% of time is inside `claude -p` — worktree creation, .claude/ composition, and roster derivation are all <250ms combined.

## Instrumentation

See: [instrumentation.md](roundtrip-optimization/instrumentation.md)

## Claude Code Internals (from source leak analysis)

See: [claude-code-internals.md](roundtrip-optimization/claude-code-internals.md)

## Candidate Interventions

See: [interventions.md](roundtrip-optimization/interventions.md)

## Experiment Log

### Baseline (no optimizations)
- Config-lead: 21.5s (proc_run=21.27s)
- Project-specialist: 6.1s (proc_run=5.94s)
- **Total: 27.6s**
- Config-lead used sonnet (from agent frontmatter via --agent flag)
- ToolSearch present: 58 deferred tools (41 MCP + 17 builtin)
- ToolSearch cost: ~7s (3.2s first turn + 0.4s call + 3.4s second turn)

### Experiment 1: ENABLE_TOOL_SEARCH=false + DISABLE_NONESSENTIAL_TRAFFIC=1 + MCP_TIMEOUT=5000
- Config-lead: 27.9s (**worse**)
- Project-specialist: 11.6s (**worse**)
- **Total: 39.5s (+43%)**
- **Finding:** ENABLE_TOOL_SEARCH=false inlines all 41 MCP tool schemas into the system prompt. The token cost of 41 schemas per turn overwhelmed the savings from eliminating ToolSearch. This approach only works with a small tool count.

### Experiment 2: Exp1 + --setting-sources user,project (for permissions)
- Config-lead: 28.6s (**worse**)
- Project-specialist: 11.8s (**worse**)
- **Total: 40.4s (+46%)**
- **Finding:** `--setting-sources project` causes Claude Code to auto-discover and load ALL agents and skills from `.claude/` in the worktree. compose_worktree symlinks 30+ agent definitions and 20+ skills there. This bloats the system prompt massively.

### Experiment 3: Reverted ENABLE_TOOL_SEARCH, pass settings via --settings instead of --setting-sources project
- Config-lead: 15.3s (**improved**)
- Project-specialist: 4.3s (**improved**)
- **Total: 19.6s (-29%)**
- **Finding:** Back to `--setting-sources user` only. Permissions passed via `--settings <json>` inline. No agent/skill bloat. Specialist has no MCP server (leaf scope, no roster). DISABLE_NONESSENTIAL_TRAFFIC=1 and MCP_TIMEOUT=5000 still active.

### Experiment 4: MCP tool scoping via AGENT_TOOL_SCOPE env var
- Config-lead: 15.7s (same)
- Project-specialist: 4.3s (same)
- **Total: 20.0s (no change from Exp3)**
- **Finding:** AGENT_TOOL_SCOPE env var never reaches the MCP server process. Tried three delivery mechanisms:
  1. Set on spawner process env → claude -p inherits → MCP server should inherit: **FAILED** (41 MCP tools still registered)
  2. Set in mcp_config `env` field: **FAILED** (Claude Code's env field does not set actual process env vars — it's for config JSON variable substitution only)
  3. Appended to mcp_config `args` field as `--scope=dispatch`: **NOT TESTED YET** (abandoned after env approach failed, but args may work differently)
- **Key insight:** The mcp_config `env` field does NOT set process environment variables. Socket paths (SEND_SOCKET etc.) work because they're set in `extra_env` on the `claude -p` process and inherited by the MCP server child. The `env` field in mcp_config may only be used for `${VAR}` substitution in config strings.

### Experiment 5: SEND_SOCKET in extra_env as scope signal
- Config-lead: 15.9s (same)
- Project-specialist: 3.8s (same)
- **Total: 19.7s (no change)**
- **Finding:** Added SEND_SOCKET/REPLY_SOCKET/CLOSE_CONV_SOCKET to extra_env so claude -p process has them. MCP server still shows 41 tools. The MCP server child does NOT inherit the parent claude -p process environment. Claude Code sanitizes/replaces the child env.
- **Still 58 deferred tools, ToolSearch still happening.**

## Current State

- **Best result: 19.6s (Experiment 3) — 29% reduction from 27.6s baseline**
- Remaining gap to 50%: need to reach ~14s
- The ToolSearch round-trip costs ~7s per dispatching level
- Eliminating ToolSearch would bring config-lead from ~15s to ~8-9s, total to ~12-13s (>50%)
- **Blocker:** Cannot get the MCP tool scope to the MCP server process. Claude Code isolates the MCP server's environment.

### Experiment 6: File-based tool scope (.tool-scope in worktree)
- Wrote `.tool-scope` file to worktree before spawn
- MCP server reads from `os.path.join(os.getcwd(), '.tool-scope')`
- **Result: Still 41 MCP tools.** File exists in worktree but MCP server's cwd is NOT the agent worktree — Claude Code may set the MCP server's cwd to something else.
- **Finding:** Three delivery mechanisms tried (env var on claude -p, mcp_config env field, file in worktree). None reach the MCP server. Claude Code fully isolates MCP server subprocess environment AND cwd.

### Experiment 6b: Separate MCP entry point (mcp_server_dispatch.py)
- Created `orchestrator/mcp_server_dispatch.py` that sets AGENT_TOOL_SCOPE before importing main
- **Result: 0 MCP tools loaded.** The file doesn't exist in the worktree because it's not committed to git. Worktrees only contain committed files.
- Tried `-c` inline Python in args field: **Still 41 MCP tools.** Claude Code doesn't pass args to the Python interpreter as expected.

### Experiment 8: Committed dispatch entry point + fresh OM workspace
- Committed `mcp_server_dispatch.py` and all `office_manager.py` changes
- Deleted stale OM workspace so it gets recreated from committed state
- **Result: 20 MCP tools (down from 41).** Dispatch entry point works!
- Config-lead: 18.9s, Specialist: 6.3s, **Total: 18.9s (-32% from baseline)**
- ToolSearch still happening: 37 deferred total (20 MCP + 17 builtin)
- Prompt optimization visible: agent calls Send on turn 2 (was turn 3)
- **Key lesson:** OM workspace worktree must contain committed code. Uncommitted changes in the main checkout don't propagate to worktrees.

### FINDING: ToolSearch threshold
37 deferred tools still triggers ToolSearch. Need to get below ~15-20 to eliminate it.
Options: reduce builtin tools via `--tools "Read,Bash"` (cuts 17 builtins to 2), or reduce MCP tools further.

### Experiment 7: Progressive disclosure in agent prompt
- Rewrote config-lead prompt to put Send front and center with concrete example
- Hypothesis: even with ToolSearch, if the agent knows to call Send immediately on turn 1, it saves the "decide what to do" deliberation time
- Old prompt: 60 lines, Send never mentioned, agent discovers it via exploration
- New prompt: 20 lines, Send is the second section with usage example
- **Not yet measured**

### Experiment 9: --tools "" + committed dispatch entry point + prompt + remove Reply/Close
- 14 MCP tools (Send + AskQuestion + 12 read), 0 builtins
- No deferred tools at all — everything eagerly loaded
- No ToolSearch round-trip
- No Reply/CloseConversation calls (removed from dispatch scope)
- Send called on first model turn (0.1s after startup)
- Config-lead: **13.1s**, Specialist: **3.9s**
- **Total: 13.1s — 53% reduction from 27.6s baseline. TARGET MET.**

Config-lead session timeline:
```
+4.3s  startup → first API response
+0.1s  calls Send (no ToolSearch, no deliberation)
+3.9s  specialist runs and returns
+3.6s  processes result, outputs text
```

## Current State

- **Best result: 13.1s (Experiment 9) — 53% reduction from 27.6s baseline**
- Target of >50% reduction: **ACHIEVED**

## Next Steps to Try

1. **Measure Experiment 7** — prompt optimization alone
2. **Separate MCP entry point** — `orchestrator.mcp_server_dispatch` module that imports create_server with hardcoded dispatch scope. Pass via `args: ["-m", "orchestrator.mcp_server_dispatch"]`. This bypasses the env/file delivery problem entirely.
3. **Combine** prompt optimization + tool scoping for maximum impact
