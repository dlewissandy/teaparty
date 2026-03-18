# Intent: Graceful Handling of API Error 529 (Overloaded)

## Problem

When the Anthropic API returns HTTP 529 (Overloaded), Claude Code CLI processes
invoked via `claude -p` may fail after exhausting their internal retry budget
(10 attempts with exponential backoff). Today, the TeaParty orchestrator treats
this identically to any other non-zero exit: the `ClaudeRunner` returns a
`ClaudeResult` with `exit_code != 0`, which propagates up as
`ActorResult(action='failed', reason='nonzero_exit')`, triggering the
infrastructure failure dialog.

This is problematic for multi-agent sessions because:

1. **Pipe breakage in team hierarchies.** A 529 failure during an `AskTeam`
   dispatch kills the child orchestrator's phase. The dispatch retry loop
   (`max_dispatch_retries=5`) immediately retries the *entire orchestrator run*
   — not just the failed CLI call — wasting budget and potentially hitting the
   same overload wall.

2. **Silent empty responses.** If the CLI exits non-zero but has already written
   partial stream-json output, the agent that dispatched the work may receive a
   truncated or empty result through the MCP socket, with no indication that the
   failure was transient.

3. **Stall timeout false positives.** During sustained 529 episodes, the CLI's
   internal retries (up to ~40s total backoff) may produce no stdout, causing the
   watchdog to accumulate stall time. A subsequent real agent turn that runs
   close to the timeout limit may then be killed prematurely because the stall
   clock wasn't reset.

4. **Noise in backtrack context.** When the engine retries after infrastructure
   failure, it injects `stderr_lines` from the previous turn into the next agent
   prompt. 529 retry noise (10 lines of `API Error: 529 overloaded`) pollutes
   the agent's context window without providing actionable information.

## Constraints

These are hard constraints — violation of any is a blocking issue:

- **MUST NOT switch from `claude -p` to direct API calls.** The CLI is our
  interface to Claude Code; we do not maintain our own API client.
- **MUST NOT add backoff on top of backoff.** Claude Code CLI already implements
  exponential backoff internally (10 retries, 1s → 2s → 4s → 9s → 19s…). Our
  layer must not add a second backoff loop that compounds delays.
- **MUST NOT inject API error messages into chat history.** Error 529 retry
  lines from stderr must not appear as conversation content that agents see and
  respond to. No ping-pong error pollution.
- **MUST NOT fail silently.** If a 529 causes a CLI process to exit, the calling
  agent or orchestrator must know the failure was transient — not interpret an
  empty response as "the agent had nothing to say."
- **MUST NOT break pipe chains.** The
  `MCP socket → EscalationListener/DispatchListener → Orchestrator` chain and
  the `stdin → claude -p → stdout stream-json` pipe must remain intact. Timeouts
  on these pipes must account for 529 retry delays.

## Current Architecture (for context)

**Subprocess invocation** (`claude_runner.py`):
- `claude -p --output-format stream-json` spawned via `asyncio.create_subprocess_exec()`
- Prompt fed via stdin, stdin closed immediately
- stdout streamed line-by-line, parsed as JSON, persisted to JSONL, published to event bus
- stderr captured into `stderr_lines` list
- Watchdog kills process after `stall_timeout` (default 1800s, extended to 7200s for background agents)
- Returns `ClaudeResult(exit_code, session_id, stall_killed, stderr_lines)`

**Actor layer** (`actors.py`):
- `AgentRunner.run()` maps `stall_killed → ActorResult(action='failed', reason='stall_timeout')`
- Maps `exit_code != 0 → ActorResult(action='failed', reason='nonzero_exit')`
- On failure, engine invokes `failure_dialog()` → human decides retry/backtrack/withdraw

**Dispatch** (`dispatch_cli.py`):
- Child orchestrator runs full CfA session in dispatch worktree
- Retry loop: up to `max_dispatch_retries=5`, no delay between retries
- Result returned as JSON over MCP socket to parent agent

**MCP IPC** (`mcp_server.py`):
- `AskTeam(team, task)` → Unix socket → `DispatchListener` → `dispatch()` → result JSON
- `AskQuestion(question)` → Unix socket → `EscalationListener` → proxy/human → answer
- No timeouts on socket I/O (relies on process-level watchdog)

## Proposed Approach

### 1. Classify 529 as a distinct, transient failure reason

In `ClaudeRunner` or `AgentRunner`, detect 529 errors from stderr patterns
(e.g., lines matching `overloaded` or `529`). Return a new failure reason
`'api_overloaded'` distinct from generic `'nonzero_exit'`.

### 2. Orchestrator-level retry with cooldown (not backoff)

When the engine receives `reason='api_overloaded'`:
- Wait a fixed cooldown (e.g., 60–120s) before retrying the phase — long enough
  for the CLI's *next* invocation to succeed, short enough to not hit stall
  timeouts.
- Cap retries at a small number (e.g., 2–3). After that, surface the failure
  normally (infrastructure failure dialog).
- This is NOT exponential backoff. It's a single-wait retry at the orchestrator
  level, specifically because the CLI already does backoff internally.

### 3. Filter 529 noise from backtrack context

When injecting `stderr_lines` into the next agent prompt, strip lines that are
purely 529 retry noise. Only inject actionable stderr (actual errors, warnings,
diagnostic output).

### 4. Emit structured observability events

Publish an `EventType.API_OVERLOADED` event (or similar) when a 529 failure is
detected, so the TUI can display a clear "API overloaded — waiting to retry"
status rather than a generic failure.

### 5. Audit pipe timeouts

Review the MCP socket reads and the stall watchdog to ensure that:
- The watchdog's stall clock resets when the CLI is actively retrying (producing
  stderr), not only on stdout.
- Socket reads in `mcp_server.py` have explicit timeouts that account for the
  worst-case 529 retry window (~40s) plus the orchestrator cooldown.

## What Success Looks Like

- A sustained 529 episode (minutes) causes a visible "waiting for API" status
  in the TUI, not a cascade of failure dialogs.
- Agents never see "API Error 529" in their context window.
- Dispatch pipes remain open during retries — no broken sockets, no truncated
  responses.
- The orchestrator eventually surfaces the failure to the human if the API
  doesn't recover, with a clear explanation and the option to
  retry/backtrack/withdraw.
- No double-backoff: the total retry wall-time is the CLI's internal backoff +
  one orchestrator cooldown, not a multiplicative product.

## Files Likely Affected

| File | Change |
|------|--------|
| `claude_runner.py` | Detect 529 from stderr; new failure classification |
| `actors.py` | Map `api_overloaded` to distinct `ActorResult` |
| `engine.py` | Cooldown-retry logic for `api_overloaded` failures |
| `events.py` | New `EventType` for API overload observability |
| `dispatch_cli.py` | Audit dispatch retry loop for 529-aware delays |
| `mcp_server.py` | Audit socket timeouts |
| `tests/` | Unit tests for 529 detection, retry logic, stderr filtering |

## References

- [Anthropic API Error Documentation](https://platform.claude.com/docs/en/api/errors)
- [Claude Code CLI 529 retry behavior](https://github.com/anthropics/claude-code/issues/4072) — CLI retries 10× with exponential backoff internally
- [Active 529 incident (2026-03-18)](https://github.com/anthropics/claude-code/issues/35704)
