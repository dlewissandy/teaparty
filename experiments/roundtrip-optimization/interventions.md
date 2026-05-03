# Candidate Interventions

Ranked by expected impact. Target: >50% reduction (baseline ~30s for 3-level dispatch).

## Overhead Breakdown (from SDK issue #33)

| Phase | Time | Productive? |
|-------|------|-------------|
| Process spawn (Node.js cold start) | ~4-5s | No |
| CLI init (settings, hooks, CLAUDE.md, MCP) | ~3-4s | No |
| Model loading / first API call | ~2-3s | No |
| **Actual LLM response** | **~2-3s** | **Yes** |

Only 2-3s of a ~10s invocation is productive work.

## Tier 1: Startup Elimination

### A. `--bare` + `DISABLE_NONESSENTIAL_TRAFFIC=1`

**`--bare`** (Boris Cherny, Anthropic): "up to 10x faster startup. Will become default for -p in a future version."

Skips: hooks, skills discovery, plugin sync, MCP auto-discovery, auto-memory, CLAUDE.md discovery, attribution, prefetches (Statsig, GrowthBook), keychain/OAuth, LSP.

Still provides context via: `--system-prompt`, `--add-dir`, `--mcp-config`, `--settings`, `--agents`.

**`DISABLE_NONESSENTIAL_TRAFFIC=1`** kills: Statsig telemetry, Sentry, auto-updater, version checks. All make network calls during startup.

**Blocker:** `--bare` requires `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`. OAuth is dead.

**Workaround options:**
1. Set `ANTHROPIC_API_KEY` in environment
2. Use `apiKeyHelper` in `--settings` JSON pointing to a script that extracts the OAuth token

Expected: 4-8s savings per level (the entire non-productive startup phase).
Status: NOT IMPLEMENTED

### B. `--no-session-persistence`

Skip JSONL writes. Dispatched agents are one-shot — no resume needed.
Expected: <1s savings. Combinable with everything.
Status: NOT IMPLEMENTED

## Tier 2: Eliminate ToolSearch Round-Trip

### C. `ENABLE_TOOL_SEARCH=false` (env var)

From paddo.dev analysis: this env var controls whether tool schemas are deferred.
- `false` = load all tool schemas upfront in the system prompt
- `auto` (default) = defer if tools exceed ~10% of context
- `auto:0` = defer ALL tools

Setting `false` means Send/Reply schemas are in the system prompt from turn 1. No ToolSearch call needed. Costs more prompt tokens but saves an entire model turn (~5s).

Expected: ~5s savings per dispatching level.
Status: NOT IMPLEMENTED

### D. `--tools ""` to disable built-in tools

All built-in tools (Read, Bash, Edit, etc.) are deferred behind ToolSearch as of v2.1.69. Dispatched routing agents communicating via Send don't need them.

`--tools ""` eliminates the entire built-in tool set. Combined with a small MCP tool count, the total tool count stays low enough that nothing gets deferred even without `ENABLE_TOOL_SEARCH=false`.

Expected: significant when combined with C or small MCP tool set.
Status: NOT IMPLEMENTED

### E. Reduce MCP tool count for dispatched agents

Filter based on AGENT_ID in create_server():
- Dispatching leads: Send, Reply, AskQuestion + List/Get (~12 tools)
- Leaf workers: no MCP tools at all (or minimal config tools)

With `--tools ""` + ~12 MCP tools, total count is well under any deferral threshold.
Status: NOT IMPLEMENTED (aborted first attempt, needs clean impl)

## Tier 3: Inference Speed

### F. `--model` from agent definition frontmatter

Agent definitions already have `model: claude-sonnet-4-5`. Spawner doesn't pass `--model` — defaults to opus.
Sonnet is ~2-3x faster inference for simple routing tasks.

Expected: 2-4s savings per level.
Status: NOT IMPLEMENTED — read frontmatter in spawner, pass `--model`.

### G. `--effort low` for routing agents

Reduces reasoning depth. Good for leads that just forward requests.
Expected: 1-2s savings.
Status: NOT IMPLEMENTED

### H. `CLAUDE_CODE_DISABLE_THINKING=1`

Disables extended thinking entirely. Good for simple dispatch tasks.
Expected: 1-2s savings.
Status: NOT IMPLEMENTED

## Tier 4: Process Reuse (Architectural)

### I. `--input-format stream-json` (persistent process)

Keep one `claude -p` process alive per agent role. Feed messages via stdin NDJSON. Eliminates the 8-12s cold start on all subsequent calls.

```bash
claude --bare -p \
  --output-format stream-json \
  --input-format stream-json \
  --permission-mode bypassPermissions \
  --system-prompt "..."
```

This is Anthropic's official answer to the cold-start problem.

**Trade-off:** Requires managing long-lived subprocesses, bidirectional NDJSON parsing, and process lifecycle management. Significant architectural change.

Expected: eliminates cold start entirely after first call (~8-10s per level on subsequent dispatches).
Status: NOT IMPLEMENTED — future optimization, requires architecture work.

## Tier 5: Cache Optimization

### J. Stable worktree paths per role

Same cwd = same project hash = prompt cache hits.
Currently: unique path per dispatch (`agents/agent_om_config-lead_{uuid}`).
Proposed: stable path per role (`agents/dispatch/configuration-lead/`).

Expected: ~2-3s savings per level on repeat calls (first call still cold).
Risk: concurrent dispatches to same role need coordination.
Status: NOT IMPLEMENTED

## Projected Impact Matrix

### Quick wins (no architectural change):

| Intervention | Per-level savings | Effort |
|-------------|------------------|--------|
| F: --model from frontmatter | 2-4s | Low |
| B: --no-session-persistence | <1s | Low |
| C: ENABLE_TOOL_SEARCH=false | ~5s | Low (env var) |
| D: --tools "" | ~1s | Low |
| G: --effort low | 1-2s | Low |

### Medium effort:

| Intervention | Per-level savings | Effort |
|-------------|------------------|--------|
| A: --bare + API key setup | 4-8s | Medium (auth change) |
| E: MCP tool filtering | ~2s | Medium (server refactor) |
| J: Stable worktrees | 2-3s | Medium (concurrency) |

### High effort:

| Intervention | Per-level savings | Effort |
|-------------|------------------|--------|
| I: Persistent process | 8-10s (after first) | High (architecture) |

## Recommended Experiment Order

1. **Measure baseline** with current instrumentation
2. **F + C + D + G + B** — all are single-flag changes, stack them
3. **A** — if API key is available, add --bare
4. Measure combined improvement
5. If >50%, stop. If not, proceed to E or I.

### Best-case quick-win stack (F + C + D + G + B):

| Level | Baseline | Optimized | How |
|-------|----------|-----------|-----|
| Config-lead | ~10s | ~4-5s | sonnet + no ToolSearch + no builtins + low effort |
| Project-specialist | ~7s | ~3-4s | sonnet + no builtins + no session persistence |
| **Total** | **~17s** | **~7-9s** | **~50-55% reduction** |

### With --bare added:

| Level | Optimized | How |
|-------|-----------|-----|
| Config-lead | ~2-3s | bare + sonnet + no ToolSearch + no builtins |
| Project-specialist | ~1-2s | bare + sonnet + no builtins |
| **Total** | **~3-5s** | **~80% reduction** |
