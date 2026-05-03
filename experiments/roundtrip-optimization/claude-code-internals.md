# Claude Code Internals (from v2.1.88 source leak)

Key findings relevant to dispatch optimization. Source: accidental `.map` file in npm
package (v2.1.88), analyzed by multiple independent researchers. Confirmed against
minified cli.js in v2.1.92 npm package where possible.

---

## 1. Startup Sequence (Process Start → First API Call)

### Four-phase initialization

**Phase 1: CLI Entrypoint (`src/entrypoints/cli.tsx`)**
- Captures startup profiling timestamp for time-to-interactive measurement
- Fast-path exits: `--version`, `-v` bail immediately without expensive imports
- Fires async side-effect prefetches at module-eval time (~135ms total):
  - `startMdmRawRead()` — MDM policy via plutil (macOS)
  - `startKeychainPrefetch()` — OAuth token + API key from keychain (~65ms)
  - Results cached; `init()` awaits the promises later
- ABLATION_BASELINE gate runs here (before any tool module loads):
  - If `feature('ABLATION_BASELINE') && process.env.CLAUDE_CODE_ABLATION_BASELINE`,
    sets 7 env vars via nullish coalescing (`??=`), preserving user overrides:
    `CLAUDE_CODE_SIMPLE`, `CLAUDE_CODE_DISABLE_THINKING`,
    `DISABLE_INTERLEAVED_THINKING`, `DISABLE_COMPACT`, `DISABLE_AUTO_COMPACT`,
    `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `DISABLE_BACKGROUND_TASKS`

**Phase 2: Commander Orchestration (`src/entrypoints/main.tsx`)**
- Commander.js parses CLI flags
- Global flags parsed: `--model`, `--verbose`, `--dangerously-skip-permissions`, etc.
- Action handler invokes `init` from `src/entrypoints/init.ts`

**Phase 3: System Initialization (`src/entrypoints/init.ts`)**
- Telemetry bootstrap (OpenTelemetry providers, analytics pipeline)
- Config loading (hierarchy: MDM > CLI Flags > Project Config > Global)
- Auth initialization (validates credentials, triggers OAuth PKCE or API key)
- Scratchpad setup (temp directory for tool execution)

**Phase 4: Setup + UI Mount (`setup.ts` → REPL or print)**
1. Node.js version check
2. `startUdsMessaging()` — Unix Domain Socket server for hook injection
3. `captureTeammateModeSnapshot()` (non-bare only)
4. `setCwd(cwd)` — MUST precede hooks
5. `captureHooksConfigSnapshot()` — reads .claude/settings.json
6. `initializeFileChangedWatcher()`
7. Background: `initSessionMemory()`, `getCommands()` prefetch, `loadPluginHooks()`
8. `initSinks()` — analytics
9. `logEvent('tengu_started')` — health beacon
10. Permission checks
11. Mode routing: local REPL, remote, SSH, teleport, deep-link, or **print**

### `-p` (print) mode specifics

There is no separate fast path function for `-p` mode. The same four phases run.
The distinction is in `state.ts`: `isInteractive` is set to `false` when stdin is not
a TTY or `-p` is passed. This boolean gates:
- The Ink-based REPL UI (skipped in print mode)
- Interactive permission prompts (blocked; requires `--allowedTools` or permission mode)
- The workspace trust dialog (skipped entirely in `-p` mode)
- ANTHROPIC_API_KEY is always used when present (no approval prompt in `-p` mode)
- Plugins should not load or must gracefully degrade (to avoid stdin/stdout interference)

**The big lever for `-p` mode is `--bare`.** Without it, `-p` loads the same context
as an interactive session (hooks, CLAUDE.md, MCP servers, skills, plugins, etc.).
With `--bare`, startup is dramatically reduced. Anthropic has stated `--bare` will
become the default for `-p` in a future release.

---

## 2. `--bare` Flag

Sets `CLAUDE_CODE_SIMPLE=1` internally.

**Skips:**
- UDS messaging server (`startUdsMessaging()`)
- Teammate snapshot (`captureTeammateModeSnapshot()`)
- Session memory initialization (`initSessionMemory()`)
- Plugin hook pre-loading (`loadPluginHooks()`)
- Attribution + repo classification
- ALL deferred prefetches (keychain, MDM)
- CLAUDE.md discovery and directory walks
- Skill directory walks
- LSP initialization
- OAuth and keychain reads
- Auto-memory
- Background prefetches

**Still runs:**
- Auth (API key only: `ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings`)
- 3P provider auth (Bedrock/Vertex/Foundry use their own credentials)
- Migrations
- Analytics beacon (`tengu_started`)
- Permission checks
- Skill resolution via `/skill-name` still works

**Context must be provided explicitly via flags:**
- `--system-prompt[-file]`, `--append-system-prompt[-file]`
- `--add-dir` (for CLAUDE.md directories)
- `--mcp-config`
- `--settings`
- `--agents`
- `--plugin-dir`

**Impact:** "Up to 10x faster startup" per source analysis. Will become default for
`-p` in a future release.

---

## 3. MCP Server Connection Timing

### Confirmed from minified source (v2.1.92 cli.js)

Three functions parse env vars with fallback defaults:

```
MCP_TIMEOUT:                    parseInt(env) || 30000   (30s — connection timeout)
MCP_TOOL_TIMEOUT:               parseInt(env) || 1e8     (100,000s — effectively infinite)
MCP_SERVER_CONNECTION_BATCH_SIZE: parseInt(env) || 3      (parallel connection slots)
```

### Connection flow (from `AF1` / `z01` in minified source)

1. All configured servers are collected from `getAllMcpConfigs()` (or `--mcp-config`
   only if `--strict-mcp-config` is set)
2. Servers are connected in **batches** of `MCP_SERVER_CONNECTION_BATCH_SIZE` (default 3)
3. Within each batch, connections run in parallel via `Promise.all`
4. Each connection races against a `setTimeout` of `MCP_TIMEOUT` ms
5. For stdio servers: spawns process, pipes stderr, connects MCP client
6. After connection: fetches tools, commands, and resources in parallel via
   `Promise.all([fetchTools, fetchCommands, fetchResources])`
7. Tool timeout uses `MCP_TOOL_TIMEOUT` (per-call, not per-connection)

### Timing implications for dispatch

- **With 1 stdio server:** Connection + tool listing is typically 1-3s
- **With 3+ servers:** Batching means latency = max(batch) + serial overhead
- **Setting `MCP_TIMEOUT=5000`:** Safe for local stdio servers that start fast;
  risky for SSE/HTTP servers that need OAuth negotiation
- **Connection timeout is separate from tool timeout:** Reducing `MCP_TIMEOUT`
  does not affect how long tool calls can take

### Config scopes (aggregated via `getAllMcpConfigs`)
1. User: `~/.claude/mcp-config.json`
2. Project: `./.mcp.json`
3. Local: cwd-specific
4. Dynamic: runtime-added

### `--strict-mcp-config`
- Only uses servers from `--mcp-config`, ignoring all other sources
- Combined with `--bare`, prevents surprise MCP server discovery

---

## 4. `ENABLE_TOOL_SEARCH` Environment Variable

### Valid values
- `true` — Force-enable tool search (MCP tool descriptions are NOT preloaded
  into context; loaded on-demand via search)
- `false` — Disable tool search; load ALL tool definitions into context on every turn
- `auto:N` — Activate tool search when tools exceed N% of context
  (e.g., `auto:5` triggers at 5%)
- Not set — Default behavior; automatic activation should trigger when MCP tool
  descriptions exceed 10% of context, but there is a known bug
  (GitHub issue #18397): the `tengu_mcp_tool_search` config flag does NOT
  trigger automatic activation. Only the env var works.

### What `false` does exactly
When `ENABLE_TOOL_SEARCH=false`:
- The ToolSearch meta-tool is removed from the tool list
- ALL tool schemas (built-in + MCP) are inlined into the system prompt
- Every turn pays the full token cost for all tool descriptions
- This removes the search round-trip latency but increases prompt size

### Token impact (from user measurements)
| Configuration | System tools tokens | Total initial context |
|---------------|--------------------|-----------------------|
| Default (few tools) | ~9.8k (4.9%) | ~13k (6%) |
| Many MCP tools, no tool search | ~70.5k (35.3%) | ~98k (49%) |
| Many MCP tools, ENABLE_TOOL_SEARCH=true | ~0 (on-demand) | ~23k (11%) |

### When to set `false`
When you have fewer than ~10 tools total and want to eliminate the ToolSearch
round-trip. The definitions fit comfortably in context and the overhead is small.

---

## 5. Startup Optimization Env Vars

### `CLAUDE_CODE_FAST` — Does NOT exist
Confirmed absent from both the env var gists and the minified source.

### What DOES exist:

| Variable | Effect |
|----------|--------|
| `CLAUDE_CODE_SIMPLE` | "Simplified mode" — disables MCP tools, attachments, hooks, CLAUDE.md loading, auto-memory, and other advanced features. Set automatically by `--bare`. |
| `CLAUDE_CODE_ABLATION_BASELINE` | Testing preset. When feature flag active, sets 7 env vars at once (SIMPLE, DISABLE_THINKING, etc.) for harness-science experiments. Uses `??=` so explicit user values are preserved. |
| `CLAUDE_CODE_NEW_INIT` | Switches `/init` from codebase-scanning to interview mode. Not a startup optimization. |
| `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` | Disables background work. |
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY` | Disables auto-memory (MEMORY.md updates). |
| `DISABLE_AUTO_COMPACT` | Disables automatic context compaction. |
| `CLAUDE_CODE_DISABLE_THINKING` | Disables extended thinking. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | Reduces auxiliary network traffic. |
| `CLAUDE_CODE_DISABLE_CLAUDE_MDS` | Disables loading of CLAUDE.md instruction files. |

---

## 6. `--tools` Flag Behavior

### Confirmed behavior
- `--tools ""` — Disables ALL built-in tools. Claude has no Bash, Read, Edit, Write,
  Glob, Grep, Agent, etc. Only MCP tools (if any) remain available.
- `--tools "default"` — All built-in tools (same as not passing the flag).
- `--tools "Read,Bash"` — Only those specific built-in tools are available.

### System prompt impact
- Disabling tools removes their descriptions from the system prompt
- Adding tools to `permissions.deny` in settings.json also removes them from prompt
- Measured token savings (from Japanese blog analysis):
  - Full tools: ~16.0k system tools tokens (8.0% of 200k context)
  - After removing several tools: ~9.8k tokens (4.9%)
  - With `--tools ""`: approaches 0 for built-in tools

### Interaction with `CLAUDE_CODE_SIMPLE`
When `CLAUDE_CODE_SIMPLE=1` (set by `--bare`), the available tool set is restricted
to Bash, Read, and Edit only. MCP tools, attachments, hooks are disabled.
`--tools` can further restrict even that set.

### `assembleToolPool()` in tools.ts
- Built-ins sorted alphabetically (prefix) + MCP tools sorted alphabetically (suffix)
- Sort order preserves prompt cache breakpoints between groups
- Tool schemas validated via Zod

---

## 7. System Prompt Composition

### Architecture
The system prompt is NOT monolithic. It is assembled from 110+ distinct component
strings that are conditionally included based on environment, features, and config.

### Components (from Piebald-AI/claude-code-system-prompts analysis)
- ~60+ system prompt sections (16-2,938 tokens each)
- ~33 system reminders (12-1,297 tokens each)
- ~25 agent prompts (133-3,325 tokens each)
- ~30 data/reference materials (1,334-5,106 tokens each)

### Key size points
- **Base system prompt alone:** ~269 tokens (identity, basic rules)
- **With full built-in tools (no MCP):** ~16k tokens for tool descriptions
- **Minimal (`--bare --tools ""` with no MCP):** ~2-3k tokens estimated
  (base prompt + minimal dynamic sections)
- **Security monitor autonomous agent prompt:** 6,426 tokens combined
- **Exact counts vary ±20 tokens** due to interpolated variables

### Static/dynamic split for caching
```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```
Located at `src/constants/prompts.ts:114-115`. Everything before the boundary is
cached across turns; everything after is rebuilt each turn. Two section constructors:
- `systemPromptSection()` (line 20) — memoized, computed once per session
- `DANGEROUS_uncachedSystemPromptSection()` (line 32) — bypasses caching

### Minimal prompt estimate
With `--bare --tools "" --mcp-config <1-server>`:
- Base prompt: ~269 tokens
- Minimal dynamic: ~2k tokens (language, output format, etc.)
- 1 MCP server tools: depends on server (100-2000 tokens typical)
- Total: roughly 2.5-4.5k tokens

---

## 8. `apiKeyHelper` in `--settings`

### JSON schema
In settings.json, `apiKeyHelper` is a **string** (not an object):
```json
{
  "apiKeyHelper": "/path/to/script.sh"
}
```
The value is: "Custom script, to be executed in /bin/sh, to generate an auth value.
This value will be sent as X-Api-Key and Authorization: Bearer headers."

### Script requirements
- Executed via `/bin/sh`
- Must print the API key to stdout and exit 0
- stderr output is treated as an error
- No arguments are passed to the script

### Refresh behavior
- Called on startup
- Called again after 5 minutes OR on HTTP 401
- TTL configurable via `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` (milliseconds)
- If the script takes >10 seconds, a warning is shown in the prompt bar

### Usage with `--bare`
```bash
claude --bare -p "task" --settings '{"apiKeyHelper": "/path/to/get-key.sh"}'
```
This is the primary auth mechanism in `--bare` mode (since OAuth/keychain are skipped).
The script can be a vault lookup, AWS Secrets Manager call, or simple `echo $KEY`.

### Auth precedence (with `--bare`)
1. Cloud provider credentials (CLAUDE_CODE_USE_BEDROCK, etc.)
2. `ANTHROPIC_AUTH_TOKEN` env var
3. `ANTHROPIC_API_KEY` env var
4. `apiKeyHelper` script output
5. OAuth (disabled by `--bare`)

### Conflicts
- Cannot coexist with `ANTHROPIC_AUTH_TOKEN` (auth conflict warning)
- Does not receive `ANTHROPIC_BASE_URL` from settings.json in its env (known bug,
  GitHub issue #26999)

---

## 9. `CLAUDE_CODE_SIMPLE`

### What it is
Set automatically by `--bare`. Can also be set directly as an env var.

### What it disables
- MCP tools (from auto-discovered servers)
- Attachments
- Hooks
- CLAUDE.md file loading
- Auto-memory (MEMORY.md updates)
- "Other advanced features" (unspecified in docs)

### What it does NOT disable
- Built-in tools (Bash, Read, Edit remain available)
- Explicitly provided context (via `--system-prompt`, `--mcp-config`, etc.)
- Auth
- Analytics/telemetry
- Permission checks

### Relationship to `--bare`
`--bare` sets `CLAUDE_CODE_SIMPLE=1` AND additionally skips:
- Keychain/OAuth reads
- UDS messaging
- Teammate snapshots
- Session memory init
- Plugin pre-loading
- LSP
- Skill/CLAUDE.md directory walks
- Attribution

So `CLAUDE_CODE_SIMPLE=1` alone is a subset of what `--bare` does. `--bare` is
strictly more aggressive.

---

## Prompt Cache

### Fork subagent cache optimization
- `buildForkedMessages()` builds byte-identical prefixes across forked agents
- Only final directive differs per child → prompt cache sharing
- Relevant for parallel fan-out dispatches

### Cache stability latches
- `afkModeHeaderLatched`, `fastModeHeaderLatched`, `thinkingClearLatched`
- Once activated, remain stable for session lifetime
- Prevents mutations that cause expensive cache misses

### Worktree path → project hash
- Session files at `~/.claude/projects/{sanitized-cwd}/{session_id}.jsonl`
- Same cwd = same project hash = cache hits on system prompt
- Unique worktree per dispatch = cold cache every time

---

## Session Persistence

### `--no-session-persistence`
- Skips JSONL write entirely (only works with `--print`)
- Sessions cannot be resumed
- Eliminates append-only write overhead

### Session file growth
- Known bug: JSONL files grow to 100-400 MB for long conversations
- Progress events store entire conversation history in `normalizedMessages`
- Resume picker must parse all these → CPU freeze

---

## Performance Constants

| Constant | Value | Notes |
|----------|-------|-------|
| `DEFAULT_MAX_RETRIES` | 10 | API call retries |
| `CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` | 10 | Parallel tool slots |
| `LITE_READ_BUF_SIZE` | 65536 | Session listing tail read |
| `MCP_TIMEOUT` | 30000ms | Connection timeout |
| `MCP_TOOL_TIMEOUT` | 100000000ms | Tool call timeout (effectively infinite) |
| `MCP_SERVER_CONNECTION_BATCH_SIZE` | 3 | Parallel MCP connections |
| Base retry delay | 500ms x 2^attempt | Capped at ~32s |
| Tool output escalation | 8k → 64k tokens | On max_output_tokens |
| apiKeyHelper TTL | 300000ms (5min) | Or on HTTP 401 |

---

## Key Flags for Dispatch Optimization

| Flag | Effect | Estimated Savings |
|------|--------|------------------|
| `--bare` | Skip hooks/LSP/plugins/memory/prefetches/OAuth | 3-6s startup |
| `--no-session-persistence` | Skip JSONL writes | <1s |
| `--tools ""` | No built-in tools (only MCP) | ~16k tokens saved |
| `--tools "Read,Bash"` | Minimal tool set | ~10k tokens saved |
| `--model sonnet` | Faster model for routing | 2-3s inference |
| `--effort low` | Less reasoning depth | 1-2s inference |
| `--disable-slash-commands` | Skip skill loading | <0.5s |
| `--strict-mcp-config` | Only declared MCP servers | Skip .mcp.json discovery |
| `MCP_TIMEOUT=5000` | Reduce MCP connection wait | Up to 25s saved on timeout |
| `MCP_SERVER_CONNECTION_BATCH_SIZE=10` | More parallel MCP connections | Reduces serial batching |
| `ENABLE_TOOL_SEARCH=false` | Skip tool search round-trip | 1 fewer API round (if <10 tools) |

---

## Sources

- [markdown.engineering/learn-claude-code/](https://markdown.engineering/learn-claude-code/) — 50-lesson deep dive
- [ccleaks.com/architecture](https://ccleaks.com/architecture) — Architecture overview
- [alex000kim.com](https://alex000kim.com/posts/2026-03-31-claude-code-source-leak/) — Anti-distillation, undercover mode
- [sabrina.dev](https://www.sabrina.dev/p/claude-code-source-leak-analysis) — High-level analysis
- [read.engineerscodex.com](https://read.engineerscodex.com/p/diving-into-claude-codes-source-code) — Code quality analysis
- [superframeworks.com](https://superframeworks.com/articles/claude-code-source-code-leak) — Architecture patterns
- [deepwiki.com](https://deepwiki.com/Sachin1801/claude-code/2.1-entrypoints-and-initialization) — Entrypoints and init
- [siddhantkhare.com](https://siddhantkhare.com/writing/the-plumbing-behind-claude-code) — Source internals
- [victorantos.com](https://victorantos.com/posts/i-pointed-claude-at-its-own-leaked-source-heres-what-it-found/) — AI-assisted analysis
- [Haseeb Qureshi gist](https://gist.github.com/Haseeb-Qureshi/d0dc36844c19d26303ce09b42e7188c1) — Architecture notes
- [jedisct1 env vars gist](https://gist.github.com/jedisct1/9627644cda1c3929affe9b1ce8eaf714) — Full env var list
- [unkn0wncode env vars gist](https://gist.github.com/unkn0wncode/f87295d055dd0f0e8082358a0b5cc467) — CLI env vars
- [xdannyrobertsx settings schema](https://gist.github.com/xdannyrobertsx/0a395c59b1ef09508e52522289bd5bf6) — JSON schema
- [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) — Prompt components
- [GitHub #18397](https://github.com/anthropics/claude-code/issues/18397) — ENABLE_TOOL_SEARCH bug
- [GitHub #424](https://github.com/anthropics/claude-code/issues/424) — MCP_TIMEOUT configuration
- [GitHub #26999](https://github.com/anthropics/claude-code/issues/26999) — apiKeyHelper env bug
- [GitHub #11587](https://github.com/anthropics/claude-code/issues/11587) — Auth conflict
- [code.claude.com/docs/en/authentication](https://code.claude.com/docs/en/authentication) — Official auth docs
- [code.claude.com/docs/en/headless](https://code.claude.com/docs/en/headless) — Official headless docs
- [code.claude.com/docs/en/settings](https://code.claude.com/docs/en/settings) — Official settings docs
- [zenn.dev/sqer](https://zenn.dev/sqer/articles/5c52615eeabce0?locale=en) — Tool disable token measurements
- v2.1.92 minified cli.js — Direct confirmation of MCP constants
