# Orchestrator Gap Report

> Generated: 2026-03-11
> Purpose: Drive subsequent coding work — every [GAP] is a concrete task.

---

## Part A — Behavioral Parity

### A1: run.sh vs session.py

#### Environment variables exported

| Behavior | run.sh | session.py | Status |
|---|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | exported at top | set in `_build_env()` inside `ClaudeRunner` | [PASS] (set per-process, not global — equivalent) |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000` | exported at top (with env override) | hardcoded in `ClaudeRunner._build_env()`, no env override | [GAP] Python ignores pre-existing `CLAUDE_CODE_MAX_OUTPUT_TOKENS` env var |
| `POC_PROJECT`, `POC_PROJECT_DIR`, `POC_SESSION_DIR`, `POC_SESSION_WORKTREE`, `POC_CFA_STATE` | all exported | passed as `env_vars` dict to `Orchestrator`, injected into settings overlay | [PASS] |
| `POC_OUTPUT_DIR`, `POC_RELATIVE_PATH`, `POC_REPO_DIR` | exported | missing from `_build_env_vars()` | [GAP] Three vars absent from Python env injection |
| `PROJECTS_DIR`, `SCRIPT_DIR` | exported into settings `env` block | not in `_build_env_vars()` | [GAP] Subprocesses that need `SCRIPT_DIR` (e.g., dispatch.sh launched by agents) will not have it |
| `POC_TASK_MODE`, `POC_PREMORTEM_FILE`, `POC_ASSUMPTIONS_FILE` | exported | not present | [GAP] Three lifecycle vars missing |
| `POC_CFA_STATE` | exported as path | included in `_build_env_vars()` | [PASS] |

#### Session lifecycle steps

| Step | run.sh | session.py | Status |
|---|---|---|---|
| Parse `--project`, `--skip-intent`, `--with-intent` CLI flags | yes | yes (constructor params) | [PASS] |
| Classify task via `classify_task.py` → project slug + mode | yes, returns `slug\tmode` | yes, calls subprocess but discards mode (only reads `parts[0]`) | [GAP] Task mode (`workflow`/`conversational`) never read; conversational short-circuit path missing |
| Conversational mode short-circuit (pipe to `claude -p` directly) | yes (`TASK_MODE=conversational`) | not implemented | [GAP] No conversational path |
| Detect linked-repo vs standalone repo (`.linked-repo` file) | yes, three-branch logic | not implemented; always calls `git rev-parse --show-toplevel` from `poc_root` | [GAP] Linked-repo detection absent; new-project init (git init + CLAUDE.md) absent |
| Compute `POC_RELATIVE_PATH` | yes | not computed | [GAP] |
| Session worktree name: `session-SHORT_ID--SLUG` (8-char UUID prefix + 40-char task slug) | yes | uses last 6 chars of session_id timestamp, not a UUID | [GAP] Naming scheme differs; timestamp suffix != random UUID prefix |
| Register worktree in `worktrees.json` manifest | yes, via `worktree_manifest.py` | yes, via `_register_worktree()` in `worktree.py` | [PASS] (different implementation, same effect) |
| Create infra subdirs: `art/`, `writing/`, `editorial/`, `research/`, `coding/` | yes | not done | [GAP] Team infra dirs not created |
| Touch `OBSERVATIONS.md`, `ESCALATION.md` | yes (backward compat) | not done | [GAP] |
| Create `CONVERSATION_LOG` file and start poll-based tail to stderr | yes (poll-based Python reader avoids deadlock) | not done; console output handled by TUI bridge differently | [GAP] No live stream relay to user terminal |
| Build `AGENTS_JSON` from `agents/uber-team.json` with `__POC_DIR__` / `__SESSION_DIR__` substitution | yes | not done; agents file path read in `AgentRunner` but substitutions not performed | [GAP] Placeholder substitution absent |
| Build settings file with `permissions.allow` rules + `hooks` (enforce-write-scope, block-task) | yes, inline Python | settings overlay built from `phase_config.json`; no hooks injected | [GAP] `hooks.PreToolUse` enforcement missing |
| Memory retrieval: institutional.md (global + project), proxy.md, fuzzy tasks/ | yes, three layers with `--scope-base-dir` | yes, three layers but `memory_indexer.py` called with different CLI API (`--retrieve --query --tasks-dir --limit`) vs shell's (`--db --source --task --top-k --output --retrieved-ids`) | [GAP] CLI argument mismatch — Python call will fail |
| Confidence posture generation (`generate_confidence_posture.py`) | yes, injected into task if non-HIGH dimensions | not implemented | [GAP] |
| Pre-mortem generation (`run_premortem.py`) | yes, injected as context | not implemented | [GAP] |
| Cross-project path resolution in task text | yes (regex slug matching) | not implemented | [GAP] |
| Export `POC_STALL_TIMEOUT=1800` | yes | stall timeout is a `PhaseConfig` field; default 1800 | [PASS] |
| CfA backtracking loop: plan→execute with up to N backtracks | yes (unbounded while loop) | yes (`engine.py`) | [PASS] (structure) |
| Session commit + squash-merge into main | yes, with LLM-generated commit message | yes (`merge.py`), but message is plain `f"Session {id}: {task[:80]}"` — no LLM generation | [GAP] LLM commit message generation absent |
| Merge conflict retry with `-X theirs` | yes | not implemented in `merge.py` | [GAP] |
| Worktree cleanup + branch delete | yes | yes (`cleanup_worktree`) | [PASS] |
| Learnings pipeline (10 phases) | yes, explicit 10 steps | only 3 scopes (`observations`, `escalation`, `intent-alignment`) | [GAP] Missing: team rollup, session rollup, project rollup, global rollup, prospective, in-flight, corrective, reinforcement tracking |
| Reinforcement tracking (`track_reinforcement.py`) | yes, at session end | not implemented | [GAP] |
| Stage detection (`detect_stage.py`) + retire old stage entries | yes, after intent approval | not implemented | [GAP] |
| Final banner with deliverables list | yes | not implemented | [GAP] |
| Signal beep at completion | yes | not implemented | minor, skip |

---

### A2: intent.sh vs engine.py

| Behavior | intent.sh | engine.py | Status |
|---|---|---|---|
| INTENT phase invoked unless `skip_intent=true` | yes | yes | [PASS] |
| Build initial prompt with context files inline | yes (context files prepended) | `task_for_phase('intent')` returns `self.task` which already has memory context prepended | [PASS] (context injected at session level) |
| `INTENT.md` written to CWD; stale file removed before first run | yes (`rm -f "$PROJECT_WORKDIR/INTENT.md"`) | not done — no stale-file removal | [GAP] |
| Find `INTENT.md` by mtime (newer than session start) with fallback search | yes | `_interpret_output` checks `os.path.exists(artifact_path)` where artifact is fixed path from phase config | [GAP] No mtime guard; stale INTENT.md from prior session could be accepted |
| Session ID extraction from stream JSON (`type=system, subtype=init`) | yes (`extract_session_id`) | yes (`_maybe_extract_session_id` in `ClaudeRunner`) | [PASS] |
| INTENT version bumping (HTML comment header) | yes (`bump_intent_version`) | not implemented | [GAP] |
| Copy INTENT.md to `INFRA_DIR/INTENT.md` after approval, then delete from worktree | yes | not implemented; INTENT.md location management absent | [GAP] |
| Prepend INTENT.md content to task for planning phase | yes | `_task_for_phase` reads INTENT.md from `session_worktree/INTENT.md` | [PASS] (reads it, but file is never relocated — depends on agent leaving it in worktree) |
| INTENT_ESCALATE state: agent writes `.intent-escalation.md`, human clarifies | yes (full loop) | `escalation_file` detection exists in `AgentRunner._interpret_output`; escalation action returned but `ApprovalGate` does not implement the INTENT_ESCALATE clarification dialog | [GAP] |
| CfA state transitions: PROPOSAL -> INTENT_ASSERT -> (approve/correct/withdraw) | yes, explicitly managed | engine drives via `transition()` calls | [PASS] (structure) |
| Proxy auto-approve at INTENT_ASSERT | yes | yes (`ApprovalGate._proxy_decide`) | [PASS] |
| Permission-block detection when INTENT.md not produced | yes (parses stream for `denied`/`not allowed`) | not implemented | [GAP] |
| Infrastructure failure handling with retry option | yes (`cfa_failure_decision`) | engine maps stall/nonzero to `PhaseResult(infrastructure_failure=True)` which triggers retry at outer loop | [GAP] No CfA-aware failure decision dialog (retry vs backtrack vs withdraw) |
| Backtrack context (`--backtrack-context`) prepended to first prompt | yes | yes (in `AgentRunner.run()`: `backtrack_context` injected into prompt) | [PASS] |
| Intent extract background jobs: observations -> proxy.md, escalation -> proxy-tasks/ | yes, immediately after approval | not done during intent phase; deferred to `extract_learnings` | [GAP] Background extraction after approval absent |
| `--permission-mode acceptEdits` for all intent turns | yes | `phase_spec.permission_mode` driven by config | [PASS] if config sets it correctly |

---

### A3: plan-execute.sh vs engine.py

#### Plan phase

| Behavior | plan-execute.sh | engine.py | Status |
|---|---|---|---|
| Run claude with `--permission-mode plan` for planning | yes | yes (from `phase_spec.permission_mode`) | [PASS] |
| Record `PLANS_BEFORE` snapshot of `~/.claude/plans/` before planning | yes | not implemented | [GAP] |
| `relocate_new_plans()`: detect newly created plan file by comparing snapshot + mtime, move to `STREAM_TARGET/plan.md` | yes | not implemented; assumes agent writes to `phase_spec.artifact` path | [GAP] Plan file detection and relocation absent |
| Permission block gate (`gate_plan_perm_blocks`) before PLAN_ASSERT | yes (check only if `plan.md` not produced) | not implemented | [GAP] |
| PLANNING_ESCALATE: agent writes `.plan-escalation.md`, human clarifies in loop | yes | `escalation_file` detection exists in `AgentRunner._interpret_output`; escalation action returned but `ApprovalGate` does not implement the clarification dialog | [GAP] |
| Save `SESSION_ID` to `.plan-session-id` file | yes | session ID tracked in `_phase_session_ids` dict | [PASS] (in memory) but file not written for cross-process handoff |
| Log plan content to session log | yes | not implemented | [GAP] (minor) |
| PLAN_ASSERT proxy check | yes | yes (`ApprovalGate`) | [PASS] |
| `--auto-approve-plan` flag (outer team pre-approved) | yes, single-use flag | `dispatch_cli.py` passes `skip_intent=True` but no auto-approve-plan equivalent | [GAP] |
| Plan correction loop: human corrects -> re-plan via `--resume SESSION_ID` | yes | yes (engine micro-loop with `resume_session`) | [PASS] |
| `refine-intent` backtrack from PLAN_ASSERT -> exit 2 | yes | engine checks `result.backtrack_to == 'intent'` | [PASS] |
| Withdraw from PLAN_ASSERT -> exit 1 | yes | yes (terminal state WITHDRAWN) | [PASS] |
| INTENT.md pre-flight check (warns on "open question") | yes | not implemented | [GAP] (minor) |

#### Execution phase

| Behavior | plan-execute.sh | engine.py | Status |
|---|---|---|---|
| Run claude with `--permission-mode acceptEdits` for execution | yes | yes | [PASS] |
| Resume from plan session ID via `--resume` | yes | yes | [PASS] |
| Stall watchdog: poll stream mtime, check active dispatches via `.running` files | yes (Bash watchdog function, checks `POC_SESSION_DIR` for `.running` files) | yes (`ClaudeRunner._stream_with_watchdog`), but does NOT check `.running` files — kills unconditionally on stall | [GAP] Active-dispatch awareness absent from Python watchdog |
| TASK_ESCALATE: agent writes `.task-escalation.md` | yes | `phase_spec.escalation_file` detection exists | [PASS] (structure) |
| Auto-detect permission blocks from stream when exec fails | yes (parse stream for `denied`/`not allowed`) | not implemented | [GAP] |
| WORK_ASSERT proxy check | yes | yes | [PASS] |
| Work correction loop: human corrects -> resume with feedback | yes | yes | [PASS] |
| `revise-plan` backtrack from WORK_ASSERT -> exit 3 | yes | engine checks `result.backtrack_to == 'planning'` | [PASS] |
| `refine-intent` backtrack from WORK_ASSERT -> exit 2 | yes | engine checks `result.backtrack_to == 'intent'` | [PASS] |
| Backtrack feedback file `.backtrack-feedback.txt` | yes | not written by engine | [GAP] Child processes / dispatch_cli expect this file |

#### Exit codes

| Code | Meaning | plan-execute.sh | engine.py / dispatch_cli.py | Status |
|---|---|---|---|---|
| 0 | success / plan approved | yes | yes (COMPLETED_WORK) | [PASS] |
| 1 | rejected/failed (WITHDRAWN) | yes | yes | [PASS] |
| 2 | backtrack to intent | yes | yes (PhaseResult.backtrack_to='intent') | [PASS] |
| 3 | backtrack to planning | yes | yes (PhaseResult.backtrack_to='planning') | [PASS] |
| 4 | infrastructure failure | yes | yes (PhaseResult.infrastructure_failure=True) | [PASS] |
| 10 | plan escalation (agent-mode only) | yes (exits 10 from PLANNING_ESCALATE in agent-mode) | not implemented as distinct exit code | [GAP] |
| 11 | work escalation (agent-mode only) | yes (exits 11 from WORK_ASSERT or TASK_ESCALATE in agent-mode) | not implemented as distinct exit code | [GAP] |

Note: Codes 10 and 11 are agent-mode-only exits that bubble up through dispatch.sh. dispatch_cli.py calls the orchestrator but does not produce these codes.

---

### A4: dispatch.sh vs dispatch_cli.py

| Behavior | dispatch.sh | dispatch_cli.py | Status |
|---|---|---|---|
| Accept `--team`, `--task`, `--cfa-parent-state`, `--auto-approve-plan` | yes | `--team`, `--task`, `--auto-approve-plan`; no `--cfa-parent-state` | [GAP] `--cfa-parent-state` absent |
| Fall back to `POC_CFA_STATE` env var for parent state | yes | not implemented | [GAP] |
| Create dispatch worktree with self-describing name (`TEAM-SHORT_ID--SLUG`) | yes | yes (`create_dispatch_worktree`) but naming scheme differs: `{team}-{dispatch_id[:6]}--{task_slug[:25]}` vs shell's `{team}-{8char_uuid}--{task_slug[:40]}` | [GAP] Naming scheme differs (timestamp prefix vs UUID prefix; shorter slugs) |
| Collision detection for worktree names | yes (counter loop) | not implemented | [GAP] |
| Support fallback flat-directory mode (no worktree when env vars absent) | yes | not implemented; returns error if `POC_SESSION_DIR` not set | [GAP] |
| Per-team Bash permission rules in settings (coding gets `python3`, `uv run`) | yes | not implemented; settings come from `phase_config.json` only | [GAP] |
| `hooks.PreToolUse` for `Task`/`TaskOutput`/`TaskStop` -> block-task.sh | yes | not implemented in dispatch settings | [GAP] |
| `unset CLAUDECODE; unset CLAUDE_CODE_ENTRYPOINT` before child process | yes | not done | [GAP] |
| Create child CfA state via `make_child_state` | yes (shell calls `cfa_state.py --make-child`) | uses `make_initial_state` + `transition(cfa, 'propose')` — NOT `make_child_state` | [GAP] Child starts at IDEA not INTENT; `parent_id`/`team_id`/`depth` fields not set |
| Team-specific proxy model (`.proxy-confidence-{team}.json`) | yes | yes | [PASS] |
| Retry loop for exit codes 3 and 4 (MAX_DISPATCH_RETRIES, default 5) | yes | yes (`retries <= max_retries`) | [PASS] |
| Exit codes 10/11 (escalation): stop retry loop, bubble up | yes (`break` on 10, 11, 0, 1, 2) | not modeled; loop only breaks on COMPLETED_WORK or WITHDRAWN terminal states | [GAP] |
| Commit deliverables in dispatch worktree before merge | yes (`git add -A; git commit`) | not done; `squash_merge` called directly | [GAP] |
| Squash-merge dispatch branch into session branch | yes | yes (`squash_merge`) | [PASS] |
| Merge conflict retry with `-X theirs` | yes | not implemented in `merge.py` | [GAP] |
| Generate commit message via `generate_commit_message.py` | yes | plain message `f"[{team}] {task[:80]}"` | [GAP] |
| Update worktree manifest: `complete` or `fail` based on exit code | yes (`worktree_manifest.py complete/fail`) | not done | [GAP] |
| Remove `.running` sentinel on completion | yes | yes | [PASS] |
| Output JSON result with CfA fields to stdout | yes (jq-built JSON with 10+ fields) | yes (simpler dict with 5 fields) | [GAP] Missing fields: `output_files`, `cfa_state`, `cfa_backtrack`, `backtrack_reason`, `escalation_context`, `dispatch_retries`, `exit_code` |
| Post-dispatch: `summarize_session.py` in background | yes | not done | [GAP] |
| `DispatchRunner` class in actors.py | — | Deleted — subprocess isolation via `dispatch_cli.py` is the intended design (process boundary = context isolation) | [RESOLVED] |

---

### A5: promote_learnings.sh vs learnings.py

| Behavior | promote_learnings.sh | learnings.py | Status |
|---|---|---|---|
| `--scope team`: dispatch MEMORY.md -> team institutional.md + team/tasks/\<ts\>.md | yes | `promote('team', ...)` in `summarize_session.py`; wired via `_promote_team` in `learnings.py` | [PASS] |
| `--scope session`: team files -> session institutional.md + session/tasks/\<ts\>.md | yes | `promote('session', ...)` in `summarize_session.py`; wired via `_promote_session` in `learnings.py` | [PASS] |
| `--scope project`: session files -> project institutional.md + project/tasks/\<ts\>.md | yes | `promote('project', ...)` in `summarize_session.py`; wired via `_promote_project` in `learnings.py` | [PASS] |
| `--scope global`: project institutional.md -> projects/ institutional.md + projects/tasks/\<ts\>.md | yes | `promote('global', ...)` in `summarize_session.py`; wired via `_promote_global` in `learnings.py` | [PASS] |
| `--scope prospective`: pre-mortem -> project/tasks/\<ts\>-prospective.md | yes | `promote('prospective', ...)` in `summarize_session.py`; wired via `_promote_prospective` in `learnings.py` | [PASS] |
| `--scope in-flight`: assumptions file -> project/tasks/\<ts\>-inflight.md | yes | `promote('in-flight', ...)` in `summarize_session.py`; wired via `_promote_in_flight` in `learnings.py` | [PASS] |
| `--scope corrective`: exec stream -> project/tasks/\<ts\>-corrective.md | yes | `promote('corrective', ...)` in `summarize_session.py`; wired via `_promote_corrective` in `learnings.py` | [PASS] |
| Compact institutional.md after session/project/global rollup | yes (`compact_memory.py`) | `_try_compact()` called inside `promote()` for session, project, and global scopes | [PASS] |
| `learnings.py` current scopes | — | All 10 scopes implemented: 3 via `_run_summarize`, 7 via `_call_promote` | [PASS] |
| Prefer typed files (institutional.md + tasks/) over legacy MEMORY.md | yes | not applicable (learnings.py only writes output, reads streams) | [GAP] Input-side hierarchy for rollup scopes not implemented |
| Multiple streams passed (intent + plan + exec) | yes, discovers available streams | yes, checks for `.intent-stream.jsonl`, `.plan-stream.jsonl`, `.exec-stream.jsonl` | [PASS] |
| Output path for `escalation` scope: directory (proxy-tasks/) not a file | shell creates timestamped file inside dir | `learnings.py` passes directory path as `--output` directly; behavior depends on `summarize_session.py` | [UNVERIFIED] needs cross-check with summarize_session.py output handling |

---

## Part B — claude -p Argument Audit

### Shell invocations (intent.sh and plan-execute.sh)

**intent.sh `run_turn()`:**
```
claude -p --output-format stream-json --verbose --setting-sources user
       --agents <JSON_STRING>
       --agent intent-lead
       --settings <settings_file>
       [--add-dir <path>...]
       [--resume <session_id>]
       --permission-mode acceptEdits
```
Prompt delivered via stdin (echo into FIFO).

**plan-execute.sh `run_claude()` — plan phase:**
```
claude -p --output-format stream-json --verbose --setting-sources user
       [--agents <JSON_STRING>]
       [--agent <lead>]
       [--settings <settings_file>]
       [--add-dir <path>...]
       --permission-mode plan
```

**plan-execute.sh `run_claude()` — exec phase:**
```
claude -p --output-format stream-json --verbose --setting-sources user
       [--agents <JSON_STRING>]
       [--agent <lead>]
       [--settings <settings_file>]
       [--add-dir <path>...]
       [--resume <session_id>]
       --permission-mode acceptEdits
```

### Python invocation (claude_runner.py `_build_args()`)

```
claude -p
       --output-format stream-json
       --verbose
       --setting-sources user
       [--permission-mode <mode>]          # only if mode != 'default'
       [--agents <agents_json_string>]     # file read at build-args time
       [--agent <lead>]
       [--settings <settings_path>]
       [--add-dir <path>...]               # silently skipped if dir not found
       [--resume <resume_session>]
```

### Differences

| # | Item | Shell | Python | Status |
|---|---|---|---|---|
| 1 | `--setting-sources user` | always present | always present | [PASS] |
| 2 | `--agents` value | inline JSON string, after `sed` substitution of `__POC_DIR__`/`__SESSION_DIR__` | file read at build-args time; no placeholder substitution applied | [GAP] Placeholder substitution missing; if agents JSON contains `__POC_DIR__` it will be passed literally to Claude |
| 3 | `--permission-mode` omission | never omitted — always `plan` or `acceptEdits` | omitted entirely when `phase_spec.permission_mode == 'default'` | [GAP] Shell always sends an explicit mode; omitting lets Claude use its own default which may differ |
| 4 | Prompt delivery | `echo "$input" | claude ...` via FIFO | bytes written to `stdin` asyncio pipe | [PASS] (functionally equivalent) |
| 5 | stderr handling | stream tee'd to `CONVERSATION_LOG` + terminal via `filter_stream` | `stderr=asyncio.subprocess.DEVNULL` — all Claude stderr silently discarded | [GAP] Claude stderr (error messages, warnings) lost entirely |
| 6 | Stream file writing | `tee "$stream_file"` — full stream captured atomically before processing | line-by-line append in `read_stream()` | [PASS] (same data, different write granularity) |
| 7 | `--add-dir` filtering | no filtering; dirs passed regardless | `if d and os.path.isdir(d)` — silently skips non-existent dirs | [PASS] (safer; acceptable difference) |

---

## Part C — Helper Import Status Table

| Script | Importable API (beyond `__main__`) | Called via subprocess in orchestrator/ | Needs importable API added? |
|---|---|---|---|
| `scripts/cfa_state.py` | Yes — `make_initial_state`, `make_child_state`, `transition`, `save_state`, `load_state`, `set_state_direct`, `is_globally_terminal`, `phase_for_state`, `CfaState`, and more | Imported directly (no subprocess) | No — API is complete and actively used |
| `scripts/human_proxy.py` | Yes — `load_model`, `save_model`, `should_escalate`, `record_outcome`, `make_model` | Imported directly in `actors.py` | No — BUT `actors.py` imports from `human_proxy.py` when it should import from `approval_gate.py` (see below) |
| `scripts/memory_indexer.py` | Yes — `chunk_text`, `open_db`, `retrieve_bm25`, `retrieve_hybrid`, `refresh_index`, `main`, and more | Called via subprocess in `session.py` using `--retrieve --query --tasks-dir --limit` flags — flags that do not exist in `memory_indexer.py`'s argparser | [YES] Add `retrieve(task, db_path, source_paths, top_k, scope_base_dir) -> str` importable function; fix `session.py` to call it directly and avoid the broken subprocess |
| `scripts/summarize_session.py` | Yes — `summarize(...)`, `promote(scope, session_dir, project_dir, output_dir, ...)`, `extract_conversation`, `extract_human_turns` | `summarize()` called directly in `learnings.py` (3 scopes); `promote()` called via `_call_promote` in `learnings.py` (7 scopes) | No — `promote()` API is complete and actively used; all 7 scopes implemented |
| `scripts/compact_memory.py` | Yes — `compact_file(input_path, output_path)`, `compact_entries(entries)` | Not called anywhere in orchestrator/ | [YES] Wire `compact_file()` into `learnings.py` after institutional.md writes; currently never called in Python path |
| `scripts/classify_task.py` | Yes — `classify(task, projects_dir) -> str` (returns tab-separated `slug\tmode`) | Called via subprocess in `session.py` | [YES] `session.py` discards the mode field from subprocess output; direct import of `classify()` would prevent this; at minimum, `session.py` must be fixed to read both fields |
| `scripts/memory_entry.py` | Yes — `MemoryEntry`, `parse_memory_file`, `serialize_memory_file`, `make_entry` | Not called in orchestrator/ | No — library only; imported by other scripts |
| `scripts/detect_stage.py` | Partial — `detect_stage_from_content(content: str) -> str` | Not called in orchestrator/ | [YES] `session.py` has no stage detection at all; wire `detect_stage_from_content()` into post-intent-approval path in engine.py (or session.py) |
| `scripts/approval_gate.py` | Yes — `should_escalate`, `record_outcome`, `load_model`, `save_model`, `generate_response`, `resolve_team_model_path`, `make_model`, and more | Not called in orchestrator/ | [YES] `approval_gate.py` is the richer successor to `human_proxy.py`: it adds `GenerativeResponse`, `generate_response()` (for INTENT_ESCALATE/PLANNING_ESCALATE generative responses), `resolve_team_model_path()`, and question-pattern learning. `actors.ApprovalGate` imports `human_proxy.py` instead — it should import `approval_gate.py` |
| `scripts/file_lock.py` | Yes — `locked_open`, `locked_append`, `locked_read_json`, `locked_write_json` | Not called in orchestrator/ | [YES] Concurrent dispatch sessions writing to shared files (`worktrees.json`, `institutional.md`, `proxy.md`) have no locking; `file_lock.py` exists for this purpose but is entirely unused in the orchestrator |
| `scripts/track_reinforcement.py` | Yes — `reinforce_entries(entries, retrieved_ids)`, `load_ids(ids_file)` | Not called in orchestrator/ | [YES] Reinforcement tracking is entirely absent from the Python session lifecycle; `extract_learnings()` in `learnings.py` must call `reinforce_entries()` at session end |

---

## Summary

### All Gaps (60 total, 8 resolved)

**A1 — session.py (23 gaps):**
1. `CLAUDE_CODE_MAX_OUTPUT_TOKENS` env override ignored
2. `POC_OUTPUT_DIR`, `POC_RELATIVE_PATH`, `POC_REPO_DIR` absent from env injection
3. `PROJECTS_DIR`, `SCRIPT_DIR` absent from env injection (breaks agent subprocesses)
4. `POC_TASK_MODE`, `POC_PREMORTEM_FILE`, `POC_ASSUMPTIONS_FILE` missing
5. Task mode (`workflow`/`conversational`) discarded after classify; no conversational short-circuit
6. Linked-repo detection (`.linked-repo`) and new-project git init absent
7. `POC_RELATIVE_PATH` not computed
8. Session worktree short ID uses timestamp suffix, not 8-char UUID prefix
9. Team infra subdirectories not created at session start
10. `OBSERVATIONS.md` / `ESCALATION.md` backward-compat touch absent
11. No live CONVERSATION_LOG stream relay to terminal
12. Agent JSON `__POC_DIR__`/`__SESSION_DIR__` placeholder substitution absent
13. `permissions.allow` and `hooks.PreToolUse` enforcement not injected into settings
14. `memory_indexer.py` called with non-existent CLI flags — subprocess will fail
15. Confidence posture generation absent
16. Pre-mortem generation absent
17. Cross-project path resolution in task text absent
18. LLM-generated commit message absent
19. Merge conflict retry with `-X theirs` absent
20. Learnings pipeline missing 7 of 10 scopes
21. Reinforcement tracking absent
22. Stage detection + retirement absent
23. Final session report banner absent

**A2 — engine.py / intent phase (8 gaps):**
24. Stale INTENT.md not removed before intent phase starts
25. INTENT.md mtime guard absent — stale file from prior session could be accepted
26. INTENT.md version bumping (HTML comment header) absent
27. INTENT.md not relocated to infra_dir after approval
28. INTENT_ESCALATE clarification dialog not implemented in `ApprovalGate`
29. Permission-block detection when INTENT.md not produced absent
30. CfA-aware failure decision dialog (retry/backtrack/withdraw) absent
31. Background extraction (observations/escalation) after intent approval absent

**A3 — engine.py / plan-execute phases (11 gaps):**
32. `~/.claude/plans/` snapshot before planning absent
33. Plan file detection and relocation (`relocate_new_plans`) absent
34. Permission block gate before PLAN_ASSERT absent
35. PLANNING_ESCALATE clarification dialog not implemented in `ApprovalGate`
36. `.plan-session-id` file not written (cross-process handoff broken)
37. `--auto-approve-plan` not propagated through dispatch path
38. Active-dispatch awareness in stall watchdog absent (kills unconditionally)
39. Permission block auto-detection in exec stream absent
40. `.backtrack-feedback.txt` not written by engine
41. Exit code 10 (plan escalation) not modeled as distinct outcome
42. Exit code 11 (work escalation) not modeled as distinct outcome

**A4 — dispatch_cli.py (16 gaps):**
43. `--cfa-parent-state` flag and `POC_CFA_STATE` fallback absent
44. Dispatch worktree naming scheme differs (timestamp vs UUID prefix; shorter slug)
45. Collision detection for worktree names absent
46. Fallback flat-directory mode absent
47. Per-team Bash permission rules absent from settings
48. `hooks.PreToolUse` for Task/TaskOutput/TaskStop block-task.sh absent
49. `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` unset before child process absent
50. Uses `make_initial_state` not `make_child_state`; `parent_id`/`team_id`/`depth` not set
51. Exit codes 10/11 (escalation) not modeled in retry loop
52. Commit deliverables in dispatch worktree before merge absent
53. Merge conflict retry with `-X theirs` absent
54. LLM commit message generation absent
55. Worktree manifest `complete`/`fail` update absent
56. JSON result missing 7 fields vs shell version
57. Post-dispatch `summarize_session.py` background call absent
58. ~~`DispatchRunner` (actors.py) is dead code~~ — RESOLVED: deleted. Subprocess isolation is the intended design.

**A5 — learnings.py (0 gaps — all resolved):**
~~59. `--scope team` rollup absent~~ — RESOLVED: `promote('team')` in summarize_session.py, wired via `_promote_team`
~~60. `--scope session` rollup absent~~ — RESOLVED: `promote('session')`, wired via `_promote_session`
~~61. `--scope project` rollup absent~~ — RESOLVED: `promote('project')`, wired via `_promote_project`
~~62. `--scope global` rollup absent~~ — RESOLVED: `promote('global')`, wired via `_promote_global`
~~63. `--scope prospective` absent~~ — RESOLVED: `promote('prospective')`, wired via `_promote_prospective`
~~64. `--scope in-flight` absent~~ — RESOLVED: `promote('in-flight')`, wired via `_promote_in_flight`
~~65. `--scope corrective` absent~~ — RESOLVED: `promote('corrective')`, wired via `_promote_corrective`
~~66. `compact_memory.py` not called after any institutional.md write~~ — RESOLVED: `_try_compact()` called inside `promote()` for session/project/global

**Part B — claude -p argument gaps (3 gaps):**
67. `__POC_DIR__`/`__SESSION_DIR__` substitution not applied to agents JSON before passing to Claude
68. `--permission-mode` omitted when phase config value is `'default'`; shell always sends explicit mode
69. Claude stderr silently discarded (`stderr=DEVNULL`); shell routes to display

### Helpers needing importable APIs added or fixed

| Helper | Action needed |
|---|---|
| `memory_indexer.py` | Add `retrieve(task, db_path, source_paths, top_k, scope_base_dir) -> str` importable function; fix `session.py` to call it directly instead of subprocess with non-existent flags |
| ~~`summarize_session.py`~~ | ~~Add `promote()` importable function~~ — RESOLVED: `promote()` exists and all 7 scopes are wired in `learnings.py` |
| ~~`compact_memory.py`~~ | ~~Wire existing `compact_file()` into `learnings.py`~~ — RESOLVED: `_try_compact()` called inside `promote()` for session/project/global scopes |
| `classify_task.py` | Fix `session.py` to read both tab-separated fields (slug and mode); consider adding `classify_with_mode(task, projects_dir) -> tuple[str, str]` to make the API unambiguous |
| `detect_stage.py` | Wire existing `detect_stage_from_content()` into post-intent-approval path in engine.py |
| `approval_gate.py` | Update `actors.ApprovalGate` to import from `approval_gate.py` instead of `human_proxy.py`; the two files have diverged and `approval_gate.py` is the richer implementation with generative response support |
| `file_lock.py` | Add lock calls around shared-file writes in `worktree.py` (`_register_worktree`) and any future institutional.md / proxy.md write paths |
| `track_reinforcement.py` | Wire `reinforce_entries()` into `extract_learnings()` in `learnings.py` at session end |
