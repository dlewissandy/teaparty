# Plan: Cross-Phase Failure Handling in the CfA Orchestration

## The Problem

Failures can happen during any phase — file permission errors, missing files, merge conflicts, connectivity drops, process crashes, OOM kills, stall timeouts. The current orchestration swallows all of these with `wait "$bg_pid" 2>/dev/null || true` and proceeds as if the agent succeeded.

The CfA state machine already models `FAILED_TASK` for Phase 3 execution-level failures (agent tried and couldn't), but **infrastructure failures are orthogonal to CfA phase** — they can interrupt any state. A merge conflict during relay.sh, a connectivity drop during intent research, an OOM during planning — these all need the same decision structure.

## Design Principle

Two layers of failure:

1. **Infrastructure failure** (cross-phase) — the process crashed, timed out, or hit an environment error. The CfA state hasn't changed — the task/plan/intent was interrupted, not completed or abandoned. The decision: retry (re-enter the same state), escalate (get help), or withdraw.

2. **Task failure** (Phase 3 only, already in CfA spec) — the agent ran successfully but reported it couldn't accomplish the task. Transitions to `FAILED_TASK` with retry/escalate/backtrack/withdraw options.

Both present the same pattern to the human/proxy: a decision point with branching transitions. But they differ in what triggered them and what options make sense.

## Changes

### 1. `plan-execute.sh` — Capture process exit codes, detect failure, present decision

**`run_claude` function (line 171):**

Change:
```bash
wait "$bg_pid" 2>/dev/null || true
```
To:
```bash
CLAUDE_EXIT=0
wait "$bg_pid" 2>/dev/null || CLAUDE_EXIT=$?
```

Export `CLAUDE_EXIT` so callers can check it. Also write a sentinel `.failed` file with context when the watchdog kills a process.

**After each `run_claude` / `run_orchestrated` call in both execution paths:**

Add a failure check before proceeding to WORK_ASSERT / PLAN_ASSERT:

```bash
if [[ $CLAUDE_EXIT -ne 0 ]]; then
    # Extract error context from stream (last error events, stderr)
    FAILURE_SUMMARY=$(extract_failure "$EXEC_STREAM" "$CLAUDE_EXIT")

    if [[ "$AGENT_MODE" == "true" ]]; then
        # Subteam: propagate failure to outer scope
        echo "$FAILURE_SUMMARY" > "$BACKTRACK_FEEDBACK"
        cfa_set "FAILED_TASK"
        exit 4  # new exit code: infrastructure failure
    fi

    # Interactive: enter failure decision loop
    cfa_failure_decision "$FAILURE_SUMMARY" "$CFA_STATE_FILE"
    # FAILURE_ACTION is set by cfa_failure_decision
    case "$FAILURE_ACTION" in
        retry)    continue ;;  # re-enter execution loop
        escalate) ... ;;       # enter TASK_ESCALATE
        backtrack) exit 3 ;;   # backtrack to planning
        withdraw)  exit 1 ;;   # withdraw
    esac
fi
```

This applies to **all three call sites**: plan phase (line 494), execute-only path (line 296), and legacy execute path (line 690).

**Planning phase failure (line 494):**

Same pattern. If `run_claude` fails during planning:
- Agent-mode: exit 4
- Interactive: present failure decision (retry/withdraw — backtrack doesn't make sense from planning since you're already there)

**Intent phase failure (`intent.sh` line 237):**

Same pattern in `run_turn`. Currently `wait "$bg_pid" 2>/dev/null || true`. Change to capture exit code. If non-zero:
- Present failure to human: retry or withdraw (no backtrack from intent — there's nothing upstream)

### 2. `chrome.sh` — Add `cfa_failure_decision` and `extract_failure`

**`extract_failure` function:**

Scans the stream JSONL + exit code to produce a concise failure summary:
- Non-zero exit code → include exit code
- Stream `is_error: true` blocks → extract error text
- Stall watchdog sentinel → "Process killed after Ns of inactivity"
- Permission denied patterns → list denied operations
- Empty stream → "Process produced no output"

Returns a short markdown summary.

**`cfa_failure_decision` function:**

Presents the failure summary and collects a decision. Similar structure to `cfa_review_loop` but with failure-specific options:

```bash
cfa_failure_decision() {
    local failure_summary="$1"
    local cfa_state_file="$2"

    chrome_header "FAILURE — process did not complete"
    echo -e "  ${C_RED}${failure_summary}${C_RESET}" >&2

    # Consult proxy first
    PROXY_ACTION=$(proxy_decide "FAILURE")
    if [[ "$PROXY_ACTION" == "auto-approve" ]]; then
        # Proxy auto-retries for transient failures
        FAILURE_ACTION="retry"
        return
    fi

    # Human decision
    echo -e "  Options: retry, escalate, backtrack, withdraw" >&2
    chrome_prompt FAILURE_RESPONSE
    # Classify using classify_review.py with FAILURE state
    ...
    FAILURE_ACTION=...
}
```

### 3. `scripts/classify_review.py` — Add FAILURE classification

Add to `STATE_ACTIONS`:
```python
"FAILURE": ["retry", "escalate", "backtrack", "withdraw"],
```

Add a `FAILURE_PROMPT` template that classifies responses in failure context:
- "try again" / "retry" / "one more time" → `retry`
- "help" / "I'll fix it" / "let me look" → `escalate`
- "rethink" / "the plan is wrong" → `backtrack`
- "stop" / "give up" / "cancel" → `withdraw`

### 4. `relay.sh` — Map exit code 4, handle in dispatch loop

Add to the exit code mapping (line 272):
```bash
4) CFA_STATUS="infrastructure_failure" ;;
```

In the dispatch retry loop (line 168), handle exit code 4 the same as exit code 3 (local retry with a cap):
```bash
if [[ $DISPATCH_EXIT -eq 3 || $DISPATCH_EXIT -eq 4 ]]; then
    ((DISPATCH_RETRIES++))
    if [[ $DISPATCH_RETRIES -ge $MAX_DISPATCH_RETRIES ]]; then
        break
    fi
    continue
fi
```

This means subteam infrastructure failures get automatic retries (up to the cap) before escalating to the uber team.

### 5. `run.sh` — Handle exit code 4 from plan-execute.sh

In the CfA backtracking loop (line 494 onward), add handling for exit code 4 from both plan and execute phases. For the uber level (interactive), this enters the failure decision loop. The human sees what failed and chooses retry/withdraw.

### 6. `plan-execute.sh` — Stall watchdog writes failure context

When the watchdog kills a process (line 141), write a sentinel:
```bash
echo "stall_timeout" > "$STREAM_TARGET/.failure-reason"
```

The `extract_failure` function checks for this sentinel.

## Files Modified

| File | Change |
|------|--------|
| `poc/projects/POC/plan-execute.sh` | Capture exit codes in run_claude, add failure checks at all 3 execution call sites and the planning call site, stall watchdog writes sentinel |
| `poc/projects/POC/intent.sh` | Capture exit code in run_turn, failure handling for intent phase |
| `poc/projects/POC/relay.sh` | Map exit code 4, auto-retry on infrastructure failure |
| `poc/projects/POC/run.sh` | Handle exit code 4 in the outer CfA loop |
| `poc/projects/POC/chrome.sh` | Add `extract_failure` and `cfa_failure_decision` functions |
| `poc/projects/POC/scripts/classify_review.py` | Add FAILURE state + prompt |

## What This Does NOT Change

- `cfa_state.py` — no new states needed; infrastructure failures are orthogonal to CfA phase state. The existing `FAILED_TASK` transitions become reachable from the execution failure path.
- Agent prompts — agents don't need to know about infrastructure failures; the orchestration handles them.
- The CfA spec — infrastructure failure is an implementation concern (Section 11: "State persistence and recovery").

## Interaction Examples

**Execution failure (interactive):**
```
── TASK → TASK_IN_PROGRESS (CfA Phase 3: Execution) ──
  [coding] Agent working...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
── FAILURE — process did not complete ──
  Process exited with code 1
  Error: Permission denied: /etc/hosts

  Options: retry, escalate, backtrack, withdraw
> retry
  Re-entering execution...
```

**Planning failure (subteam, auto-retry):**
```
  [art] Agent planning...
  [relay] Infrastructure failure — retry 1/5
  [art] Agent planning...
  [art] Plan complete
```

**Intent failure (interactive):**
```
── PROPOSAL (CfA Phase 1: Intent Alignment) ──
  Agent working...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
── FAILURE — process did not complete ──
  Process timed out after 1800s of inactivity

  Options: retry, withdraw
> withdraw
  WITHDRAWN
```
