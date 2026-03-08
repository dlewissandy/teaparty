# MCP Tools for CfA Infrastructure

## Problem

The CfA pipeline relies on a layer of custom bash scripts and Python CLI
wrappers to give agents access to infrastructure services. An agent that needs
to check proxy confidence calls `python3 approval_gate.py --decide` via Bash.
An agent that needs to dispatch a subteam calls `dispatch.sh --team coding` via
Bash. Review classification, dialog response generation, session
summarization, memory indexing — all of these go through the same pattern:
bash shell-out to a Python script that does the real work.

This works but has several costs:

1. **Fragile plumbing.** Every service call is a subprocess with arg parsing,
   stdout capture, exit code conventions, and error handling. `dispatch.sh` alone
   is 300 lines of worktree setup, CfA child state creation, settings
   generation, retry loops, git merge/squash, and JSON result construction —
   none of which is the actual work of "dispatch a subteam."

2. **Invisible to the agent.** The agent doesn't know these services exist
   until it's told about them in a prompt or discovers them through convention.
   There's no tool discovery, no schema, no parameter validation. The agent
   constructs bash commands by string concatenation and hopes the args are
   right.

3. **No structured I/O.** Everything goes through stdout strings. `dispatch.sh`
   builds a JSON result via `jq`. `approval_gate.py` returns "auto-approve" or
   "escalate" as a bare string. `classify_review.py` returns tab-delimited
   `action\tfeedback`. Each script has its own ad-hoc output format that the
   caller must parse.

4. **Subprocess overhead.** Every service call spawns a new process (sometimes
   spawning `claude -p` inside it). For quick operations like proxy lookups
   or state transitions, this is disproportionate.

5. **No composability.** The shell scripts can't easily call each other's
   services. `plan-execute.sh` calls `proxy_decide` (a bash function that
   shells out to Python), `cfa_review_loop` (a bash function that shells out
   to three different Python scripts), and `run_claude` (a bash function that
   shells out to claude CLI). These can't be reused in a different context
   without sourcing the entire bash file.

Claude Code's local MCP server provides a clean alternative: expose these
services as MCP tools with typed schemas, structured JSON responses, and
automatic discovery. The agent calls `cfa_proxy_decide` like any other tool
— with parameter validation, structured output, and no bash intermediary.

## What Becomes an MCP Tool

### Tier 1: Direct replacements for bash→Python shell-outs

These are Python functions that already exist and are currently invoked
through bash wrapper functions or subprocess calls. Converting them to MCP
tools is a straightforward lift.

| Current pattern | MCP tool | Parameters | Returns |
|----------------|----------|------------|---------|
| `proxy_decide()` → `python3 approval_gate.py --decide` | `cfa_proxy_decide` | `state`, `task_type`, `model_path` | `{action: "auto-approve"\|"escalate", confidence: 0.87, reason: "..."}` |
| `proxy_record()` → `python3 approval_gate.py --record` | `cfa_proxy_record` | `state`, `task_type`, `outcome`, `diff_summary?`, `model_path` | `{ok: true, new_confidence: 0.91}` |
| `cfa_set()` → `python3 cfa_state.py --set-state` | `cfa_set_state` | `state_file`, `target_state` | `{state: "PLAN_ASSERT", phase: "planning"}` |
| `cfa_transition()` → `python3 cfa_state.py --transition` | `cfa_transition` | `state_file`, `action` | `{state: "PLAN", phase: "planning", is_backtrack: false}` |
| `python3 cfa_state.py --read` | `cfa_read_state` | `state_file` | `{state, phase, actor, backtrack_count, ...}` |
| `python3 cfa_state.py --init` | `cfa_init_state` | `output_path`, `task_id?`, `team?` | `{state_file: "...", state: "IDEA"}` |
| `python3 cfa_state.py --make-child` | `cfa_make_child_state` | `parent_file`, `team`, `output_path` | `{state_file: "...", state: "INTENT", parent_id: "..."}` |
| `classify_task.py` | `cfa_classify_task` | `task`, `projects`, `memory_context?` | `{project: "my-proj", mode: "workflow"}` |
| `detect_stage.py` | `cfa_detect_stage` | `content` | `{stage: "implementation"}` |

### Tier 2: Heavier services that benefit from structured contracts

These do more work (spawn Claude, read files, manage git) but still fit the
tool model — the agent calls the tool, waits for a result, and acts on the
structured response.

| Current pattern | MCP tool | Parameters | Returns |
|----------------|----------|------------|---------|
| `dispatch.sh` (full subteam dispatch) | `cfa_dispatch_subteam` | `team`, `task`, `cfa_parent_state?` | `{status, summary, output_files, cfa_state, cfa_backtrack, backtrack_reason, exit_code}` |
| `generate_review_bridge.py` | `cfa_review_bridge` | `file_path`, `state`, `task?` | `{bridge_text: "..."}` |
| `classify_review.py` | `cfa_classify_review` | `state`, `response`, `intent_summary?`, `plan_summary?`, `dialog_history?` | `{action: "approve"\|"correct"\|"dialog"\|..., feedback: "..."}` |
| `generate_dialog_response.py` | `cfa_dialog_response` | `state`, `question`, `artifact?`, `exec_stream?`, `task?`, `dialog_history?` | `{reply: "..."}` |
| `summarize_session.py` | `cfa_summarize_session` | `stream_path`, `output_path` | `{learnings_count: 3, output_file: "..."}` |
| `run_premortem.py` | `cfa_premortem` | `task`, `context?`, `output_path` | `{risks: [...], output_file: "..."}` |
| `generate_confidence_posture.py` | `cfa_confidence_posture` | `task`, `context` | `{posture_text: "..."}` |
| `memory_indexer.py` (query) | `cfa_memory_query` | `task`, `project_dir` | `{entries: [...], relevance_scores: [...]}` |

### Tier 3: Composite operations (dispatch.sh decomposition)

`dispatch.sh` is the heaviest script. Rather than lifting it wholesale into one
monolithic tool, decompose it into the constituent operations that an agent
(or the CfA skill from the sibling backlog item) can compose:

| Operation | MCP tool | What it does |
|-----------|----------|-------------|
| Worktree setup | `git_create_dispatch_worktree` | Create a dispatch branch + worktree, return paths |
| Subteam invocation | `cfa_dispatch_subteam` | Run plan-execute.sh for a team, return structured result |
| Worktree merge | `git_squash_merge_dispatch` | Commit deliverables, squash-merge into session, clean up |
| Result assembly | (inline — agent does this) | Agent reads the result JSON and decides what to do |

This decomposition lets the agent orchestrate dispatch itself: create the
worktree, invoke the subteam, merge results, handle escalations. The agent
owns the flow; the tools provide the atomic operations.

## What Gets Deleted

Once the MCP tools are in place and the CfA skill (see
`backlog/cfa-as-claude-skill.md`) internalizes the protocol:

- **`dispatch.sh`** — replaced by `git_create_dispatch_worktree` +
  `cfa_dispatch_subteam` + `git_squash_merge_dispatch`, composed by the agent
- **`ui.sh` service functions** — `classify_review()`, `dialog_response()`,
  `cfa_review_loop()`, `proxy_decide()`, `proxy_record()` bash wrappers all
  replaced by direct MCP tool calls
- **`plan-execute.sh` infrastructure** — `run_claude()`, `stall_watchdog()`,
  `filter_stream()`, `extract_session_id()` become unnecessary when the agent
  drives its own Claude sessions or the MCP server manages them
- **Subprocess calls in Python scripts** — scripts that currently call
  `claude -p` as a subprocess (classify_review, generate_review_bridge,
  generate_dialog_response, etc.) either become MCP tools that use
  `llm_client.create_message()` directly or are retired entirely (see the
  CfA skill backlog item)

What survives:
- **`ui.sh` presentation functions** — `chrome_header()`,
  `chrome_banner()`, `chrome_heavy_line()`, `chrome_prompt()`,
  `chrome_beep()`. These are terminal UI, not services. They stay as bash
  functions or become a thin presentation layer.
- **`cfa_state.py`** — the state machine module. It backs the MCP tools but
  remains a standalone Python module with CLI for testing/debugging.
- **`approval_gate.py`** — the confidence model module. Same: backs the MCP
  tools, stays as a standalone module.

## MCP Server Design

### Location

The MCP server lives in the POC project as a Python module:
`scripts/mcp_server.py` (or `scripts/cfa_mcp/`). It imports the existing
Python modules (`cfa_state`, `approval_gate`, `classify_review`, etc.) and
exposes them as MCP tools.

### Configuration

Claude Code discovers the MCP server via `.claude/settings.json`:

```json
{
  "mcpServers": {
    "cfa": {
      "command": "python3",
      "args": ["scripts/mcp_server.py"],
      "env": {
        "POC_PROJECT_DIR": ".",
        "POC_REPO_DIR": "."
      }
    }
  }
}
```

### Tool schemas

Each tool gets a JSON Schema definition. Example:

```json
{
  "name": "cfa_proxy_decide",
  "description": "Check human proxy confidence for a CfA review gate. Returns auto-approve if the proxy is confident enough, escalate otherwise.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "state": {"type": "string", "description": "CfA state (e.g. PLAN_ASSERT, WORK_ASSERT)"},
      "task_type": {"type": "string", "description": "Project/task type for proxy model lookup"},
      "model_path": {"type": "string", "description": "Path to proxy confidence model JSON"}
    },
    "required": ["state", "task_type", "model_path"]
  }
}
```

The agent sees these in its tool list, knows exactly what parameters are
needed, and gets structured JSON back — no string parsing, no exit code
conventions, no arg construction.

### Stateful vs. stateless

Most tools are stateless: they take input, do work, return output. Two
exceptions need consideration:

- **Proxy model** (`cfa_proxy_decide`, `cfa_proxy_record`): these read/write
  a JSON file. The MCP server can hold the model in memory and flush to disk
  on writes, or it can do file I/O on every call. File I/O per call is simpler
  and matches the current behavior.

- **CfA state** (`cfa_transition`, `cfa_set_state`): same pattern — read
  JSON file, modify, write back. Stateless file I/O is fine.

### Error handling

MCP tools return structured errors. Instead of exit code 1 and a stderr
message, the tool returns `{error: "InvalidTransition: action 'approve' not
valid from state DRAFT. Valid: question, escalate, assert, auto-approve,
withdraw, refine-intent"}`. The agent gets a clear error it can reason about,
not a bare failure.

## Migration Path

### Phase 1: MCP server with Tier 1 tools

Expose the simple, stateless tools: `cfa_proxy_decide`, `cfa_proxy_record`,
`cfa_transition`, `cfa_set_state`, `cfa_read_state`, `cfa_classify_task`,
`cfa_detect_stage`. These are pure function wrappers — low risk, high value.

The shell scripts continue to work. The MCP tools are additive. Agents in
skill mode (see `backlog/cfa-as-claude-skill.md`) can use the tools; the
legacy bash pipeline ignores them.

### Phase 2: Tier 2 tools (classification, bridging, dialog)

Expose `cfa_classify_review`, `cfa_review_bridge`, `cfa_dialog_response`.
These currently shell out to `claude -p`; the MCP tool versions call
`llm_client.create_message()` directly, eliminating the subprocess overhead.

This is where the CfA skill starts to replace the shell pipeline for
single-level tasks: the agent uses MCP tools for proxy checks and
classification instead of the bash wrapper functions in `ui.sh`.

### Phase 3: Relay decomposition

Expose `git_create_dispatch_worktree`, `cfa_dispatch_subteam`,
`git_squash_merge_dispatch`. The agent (running the CfA skill) composes
these to dispatch subteams, replacing `dispatch.sh`.

This phase depends on the CfA skill being stable enough to drive
hierarchical dispatch. The MCP tools provide the atomic operations; the
skill provides the orchestration knowledge.

### Phase 4: Retire shell scripts

Once the CfA skill + MCP tools handle all scenarios (single-level and
hierarchical), retire `dispatch.sh`, the bash wrapper functions in `ui.sh`,
and the infrastructure functions in `plan-execute.sh`. What remains:

- `cfa_state.py` (module, backing `cfa_*` MCP tools)
- `approval_gate.py` (module, backing `cfa_proxy_*` MCP tools)
- `scripts/mcp_server.py` (the MCP server)
- `ui.sh` presentation functions (terminal UI only)
- `run.sh` (entry point — now thin: classify task, invoke skill)

## Relationship to Other Backlog Items

| Backlog item | Relationship |
|-------------|-------------|
| **CfA as Claude skill** (`cfa-as-claude-skill.md`) | The skill is the *consumer* of MCP tools. The skill provides protocol knowledge; the tools provide service access. They are complementary — the skill replaces shell orchestration logic, the tools replace shell service wrappers. |
| **Context-aware proxy** (`context-aware-proxy.md`) | The `cfa_proxy_decide` tool is the natural place to add artifact-aware confidence checks. Phase 1 of the proxy reads file content; the MCP tool accepts an optional `artifact_path` parameter. |
| **Reference-based info passing** (`reference-based-information-passing.md`) | MCP tools naturally pass file paths as parameters rather than inline content. The tool schema enforces this — `artifact_path: string` not `artifact_content: string`. |

## Risks and Open Questions

**MCP server lifecycle.** The MCP server runs as a long-lived process
alongside the Claude session. For the POC, this is fine — one session, one
server. For production, need to consider: does the server start/stop with
each `run.sh` invocation? Does it persist across sessions? Who manages its
lifecycle?

**Subteam dispatch via MCP.** `cfa_dispatch_subteam` would spawn a
`claude -p` subprocess from within the MCP server. This is architecturally
odd — the tool server spawning agent sessions. Alternative: the agent
composes git worktree tools + a "start claude session" primitive. But that
pushes complex orchestration back to the agent. Need to find the right
boundary.

**Tool discovery budget.** Each MCP tool consumes context in the agent's
tool list. With 15-20 CfA tools, this is significant. Can tools be
namespaced or lazy-loaded? Does the agent need all tools in every phase,
or can the available set be scoped by CfA state?

**Testing.** MCP tools need integration tests — the MCP protocol, parameter
validation, structured responses. The current tests mock `subprocess.run`;
MCP tool tests would mock at the module level (e.g., mock
`approval_gate.should_escalate` inside the `cfa_proxy_decide` tool handler).
This is actually cleaner than the current approach.

**Concurrent dispatch.** When the uber lead dispatches multiple subteams in
parallel (via SendMessage to liaisons, each calling `cfa_dispatch_subteam`),
does the MCP server handle concurrent tool calls? MCP servers are typically
single-threaded. May need async handlers or a process-per-dispatch model.

## Reference Documents

| Document | Path | Relevance |
|----------|------|-----------|
| Dispatch script | `dispatch.sh` | Primary target for decomposition: worktree setup, subteam invocation, git merge, result assembly |
| UI functions | `ui.sh` | Bash wrapper functions that become MCP tools: classify_review, dialog_response, proxy_decide, proxy_record, cfa_review_loop |
| Plan-execute pipeline | `plan-execute.sh` | Infrastructure functions that MCP tools replace: run_claude, stall_watchdog, filter_stream, extract_session_id |
| CfA state machine | `scripts/cfa_state.py` | Module backing cfa_transition, cfa_set_state, cfa_read_state, cfa_init_state, cfa_make_child_state tools |
| Approval gate | `scripts/approval_gate.py` | Module backing cfa_proxy_decide, cfa_proxy_record tools |
| Review classifier | `scripts/classify_review.py` | Becomes cfa_classify_review tool |
| Review bridge | `scripts/generate_review_bridge.py` | Becomes cfa_review_bridge tool |
| Dialog response | `scripts/generate_dialog_response.py` | Becomes cfa_dialog_response tool |
| Task classifier | `scripts/classify_task.py` | Becomes cfa_classify_task tool |
| Stage detector | `scripts/detect_stage.py` | Becomes cfa_detect_stage tool |
| Session summarizer | `scripts/summarize_session.py` | Becomes cfa_summarize_session tool |
| Premortem | `scripts/run_premortem.py` | Becomes cfa_premortem tool |
| Confidence posture | `scripts/generate_confidence_posture.py` | Becomes cfa_confidence_posture tool |
| Memory indexer | `scripts/memory_indexer.py` | Query path becomes cfa_memory_query tool |
| CfA skill (backlog) | `backlog/cfa-as-claude-skill.md` | The skill consumes these tools; they are complementary |
| Context-aware proxy (backlog) | `backlog/context-aware-proxy.md` | cfa_proxy_decide is the integration point for artifact-aware confidence |
| Reference-based passing (backlog) | `backlog/reference-based-information-passing.md` | MCP tool schemas naturally enforce path-based references |
| POC architecture | `POC.md` | Two-level hierarchy, dispatch bridge, process model |
| Intent engineering spec | `intent-engineering-spec.md` | CfA protocol spec that the tools serve |
| CfA spec (original) | `agentic-cfa-spec.docx` | Six-role state machine, phase definitions |
