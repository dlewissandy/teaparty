# Issue #266: Documentation Audit for Milestone 3

**Milestone:** Tier 3: Human Interaction Layer
**Date:** 2026-04-10
**Method:** Cross-reference of 31 closed tickets (chronologically ordered, later supersedes earlier), 11 design proposals, existing conceptual/detailed design docs, and current codebase state.

This document identifies every design document that needs updating as a result of Milestone 3. It serves as a roadmap for future agents: start with the summary, drill into the section for the document you're working on.

---

## At a Glance

### What changed

Milestone 3 replaced the dispatch model, restructured the codebase, and unified agent launch:

1. **Codebase restructured** (#390): `orchestrator/`, `scripts/`, `bridge/` → `teaparty/` package
2. **Unified agent launch** (#394): Eight codepaths → single `launch()` in `teaparty/runners/launcher.py`
3. **Bus-mediated dispatch** (#383): Persistent team sessions → Send/Reply on message bus
4. **Real-time streaming** (#392): All agents stream events, not batch-after-completion
5. **Job worktrees** (#384): Flat `.worktrees/` → hierarchical `{project}/.teaparty/jobs/`
6. **Team unification** (#385): `agents/*.json` → `.teaparty/` agent/workgroup format
7. **Config reader overhaul** (#373, #374): Registration vs membership, catalog merging
8. **Dashboard UI** (#365-#389): Config screens, chat blade, filters, subtask navigation
9. **PM role introduced** (#394): Project Manager mediates OM ↔ project leads
10. **`/clear` semantics** (#393): Full reset — bus, subprocesses, worktrees

### Impact on documentation

| Document | Verdict | Priority |
|---|---|---|
| `docs/overview.md` | **Rewrite** — hierarchy, agent types, work model all changed | HIGH |
| `docs/conceptual-design/agent-dispatch.md` | **Rewrite** — persistent sessions → bus dispatch | HIGH |
| `docs/conceptual-design/hierarchical-teams.md` | **Rewrite** — liaisons → bus Send/Reply | HIGH |
| `docs/detailed-design/index.md` | **Rewrite** — scope, pillar status, gaps all stale | HIGH |
| `docs/detailed-design/agent-runtime.md` | **Rewrite** — describes pre-M3 orchestrator | HIGH |
| `docs/reference/folder-structure.md` | **Rewrite** — every path is wrong | HIGH |
| `docs/conceptual-design/human-proxies.md` | **Update** — interaction model changed, internals intact | MEDIUM |
| `docs/conceptual-design/cfa-state-machine.md` | **Update** — add INTERVENE/WITHDRAW | MEDIUM |
| `docs/detailed-design/cfa-state-machine.md` | **Update** — file refs, transition table | MEDIUM |
| `docs/detailed-design/approval-gate.md` | **Update** — gate invocation flow changed | MEDIUM |
| `docs/detailed-design/heartbeat.md` | **Path updates** — mechanisms verified unchanged | LOW |
| `docs/detailed-design/learning-system.md` | **Path updates** | LOW |
| `docs/detailed-design/act-r*.md` | **Path updates** | LOW |

Eight new documents needed (3 conceptual, 4 detailed, 1 reference) — see [New Documents Needed](#new-documents-needed).

Seven code/design discrepancies found — see [Discrepancies](#potential-codedesign-discrepancies).

---

## Recommended Update Order

Dependencies flow downward — later items reference concepts established by earlier ones.

### Phase 1: Foundation (establishes vocabulary for everything else)

1. **`docs/reference/folder-structure.md`** — entirely stale, quick to rewrite, high reference value
2. **`docs/overview.md`** — entry point; establishes hierarchy, agent types, work model
3. **New: `docs/conceptual-design/team-configuration.md`** (N2) — config tree is source of truth; must exist before dispatch and launcher docs can reference it

### Phase 2: Core architecture (dispatch and launch model)

4. **`docs/conceptual-design/agent-dispatch.md`** — full rewrite for bus-mediated dispatch
5. **New: `docs/conceptual-design/messaging.md`** (N1) — bus as universal transport
6. **New: `docs/conceptual-design/office-manager.md`** (N3) — dispatch chain and human interface
7. **`docs/conceptual-design/hierarchical-teams.md`** — replace liaisons with bus dispatch; keep context-isolation insight
8. **`docs/detailed-design/agent-runtime.md`** — rewrite for unified launcher
9. **New: `docs/detailed-design/launcher.md`** or rewrite `unified-agent-launch.md` (N4)
10. **New: `docs/detailed-design/messaging.md`** (N5) — bus implementation
11. **New: `docs/detailed-design/team-configuration.md`** (N6) — config reader implementation

### Phase 3: Subsystems

12. **`docs/detailed-design/index.md`** — update pillar status and scope
13. **`docs/conceptual-design/human-proxies.md`** — update interaction model
14. **`docs/conceptual-design/cfa-state-machine.md`** — add INTERVENE/WITHDRAW
15. **`docs/detailed-design/cfa-state-machine.md`** — file refs and transition table
16. **New: `docs/detailed-design/context-budget.md`** (N7)
17. **`docs/detailed-design/approval-gate.md`** — gate invocation flow
18. **`docs/detailed-design/learning-system.md`** — file path updates
19. **`docs/detailed-design/heartbeat.md`** — file path updates
20. **`docs/detailed-design/act-r*.md`** — file path updates

### Phase 4: Reference

21. **New: `docs/reference/dashboard.md`** (N8)

---

## Detailed Findings by Document

Each section below contains the full audit for one document. Drill into the document you're working on.

<details>
<summary><strong>1. <code>docs/overview.md</code> — Master Conceptual Model (HIGH)</strong></summary>

#### 1.1 Corporate Hierarchy (lines 9-70)

The overview describes Organizations, Workgroups, Partnerships, and a Home agent. Milestone 3 replaced this vocabulary:

| Overview says | Current reality | Ticket |
|---|---|---|
| "Organization" with org lead | "Management team" with Office Manager | #394 design |
| "Home agent" creates orgs | No Home agent; OM is top-level | #394 |
| Partnerships (directional trust) | Not implemented; out of scope (single-user) | M3 proposal |
| Org lead in Administration workgroup | OM at management level; PM per project | #394 |
| `is_lead=True` on Agent records | Lead defined by workgroup YAML `lead:` field | #363, team-config proposal |

**Action:** Rewrite the Corporate Hierarchy section to describe the actual management/project/workgroup hierarchy: OM → PM → Project Lead → Workgroup agents. Remove Partnerships and Home agent (mark as future platform design). Remove Organization/Administration vocabulary.

#### 1.2 Work Hierarchy (lines 74-123)

| Overview says | Current reality | Ticket |
|---|---|---|
| Engagement → Project → Job | No engagements; OM dispatches to PM, PM to project lead | #394 |
| Liaison agents bridge levels via `relay_to_subteam` | Bus Send/Reply replaces liaisons; agents dispatch directly | #383, agent-dispatch proposal |
| Job created by liaison agent | Jobs created by project leads via Send | #384, #394 |
| Project team = org lead + liaisons | PM coordinates project lead + project config lead | #394 |

**Action:** Rewrite Work Hierarchy to describe: OM conversations, PM dispatch, project lead dispatch to workgroups, job/task worktree structure. Remove Engagement (mark as future). Replace liaison model with bus dispatch model.

#### 1.3 Conversation Kinds (line 130)

Single line referencing agent-dispatch.md. The conversation model changed significantly:

- Office manager conversations (human ↔ OM)
- Project manager conversations (human ↔ PM per project)
- Proxy conversations (human ↔ proxy)
- Agent dispatch conversations (agent ↔ agent via Send/Reply)
- Config lead conversations (human ↔ config lead via chat blade)

**Action:** Expand this section to describe the actual conversation kinds and their routing.

#### 1.4 Human Interaction Model (lines 136-158)

| Overview says | Current reality | Ticket |
|---|---|---|
| Humans DM the "organization lead" | Humans chat with OM in chat blade | #371, #392 |
| Cannot DM workgroup leads directly | Can interact via proxy; proxy review sessions | proxy-review proposal |
| Cannot assign work directly | Can launch jobs directly to project lead | #394 design |

**Action:** Update to reflect chat blade interaction, proxy review, and direct job launch.

#### 1.5 Agent Model (lines 160-178)

| Overview says | Current reality | Ticket |
|---|---|---|
| Liaison agents bridge hierarchy levels | Liaisons replaced by bus Send/Reply | #383 |
| Teams use persistent bidirectional stream-json I/O | One-shot `claude -p` with `--resume` | #394 |
| Liaison's sole function is `relay_to_subteam` | No liaisons; agents Send/Reply on bus | #383 |

**Action:** Remove liaison description. Update team session model to describe one-shot launch with `--resume`. Add PM agent type.

#### 1.6 Agent Types table (lines 170-178)

Missing types:
- **Project Manager (PM)** — one per project, mediates OM ↔ project lead
- **Configuration Lead** — routes config requests to specialists
- **CRUD Specialists** — agent-specialist, skills-specialist, workgroup-specialist, etc.

Remove: Liaison (no longer exists as a type), Home agent.

**Action:** Update table to match current agent roster.

#### 1.7 Workspace Model (lines 182-184)

| Overview says | Current reality | Ticket |
|---|---|---|
| "Subteam dispatches create child worktrees" | Session = worktree (1:1:1) per #394 design | #394 |
| References hierarchical-teams.md | Job worktrees now in `{project}/.teaparty/jobs/` | #384 |

**Action:** Update to describe session-worktree 1:1 model and job worktree layout.

#### 1.8 Technology Stack (lines 188-196)

| Overview says | Current reality | Ticket |
|---|---|---|
| Orchestrator at `projects/POC/orchestrator/` | `teaparty/` package | #390 |
| Dashboard at `projects/POC/bridge/` | `teaparty/bridge/` | #390 |

**Action:** Update paths. Add MCP server (`teaparty/mcp/`), messaging (`teaparty/messaging/`), runners (`teaparty/runners/`).

#### 1.9 Further Reading (lines 199-222)

Missing references: Agent Dispatch proposal, Job Worktrees proposal, Unified Agent Launch detailed design, Team Configuration proposal. Stale: Folder Structure doc.

**Action:** Update Further Reading section.

</details>

<details>
<summary><strong>2. <code>docs/conceptual-design/agent-dispatch.md</code> — Message Routing (HIGH)</strong></summary>

This document describes the pre-M3 dispatch model. Nearly every section is stale:

| Section | What it says | Current reality | Ticket |
|---|---|---|---|
| Routing | Messages routed by conversation kind | Messages routed via bus Send/Reply with routing rules | #383, agent-dispatch proposal |
| Multi-Agent Team Sessions | Persistent `claude` processes with bidirectional stream-json | One-shot `claude -p` with `--resume`; no persistent processes | #394 |
| Session lifecycle | "Created on first message... reused for follow-ups... stopped on cancel" | Session = worktree; `--resume` for multi-turn; CloseConversation cleans up | #394 |
| Independent Fan-Out | `@each` runs one per agent | Not described in M3; may be superseded by bus fan-out | #383 |
| Lead Agents table | Home, Organization, Workgroup leads | OM, PM, Project Lead, Workgroup Lead | #394 |
| Hierarchical Team Dispatch | Liaison agents relay via `relay_to_subteam` | Bus Send/Reply; no liaisons | #383 |
| Async notification bridge | Injects notification into parent team session | Bus messages flow between sessions | #392 |
| Feedback Routing | Agent → workgroup lead → org lead → human | Agent → proxy (at any level); escalation via bus | CfA-extensions proposal |

**Action:** Full rewrite. This document should describe:
1. The bus as the universal transport
2. Send/Reply conversation model with open/close lifecycle
3. Routing rules derived from workgroup membership
4. The unified launcher as the invocation mechanism
5. `--resume` for session continuity
6. Real-time event streaming
7. The dispatch chain: OM → PM → project lead → workgroup agents

</details>

<details>
<summary><strong>3. <code>docs/conceptual-design/hierarchical-teams.md</code> — Team Architecture (HIGH)</strong></summary>

The core insight (context isolation via process boundaries) remains valid. What changed:

| Section | What it says | Current reality | Ticket |
|---|---|---|---|
| Liaison agents bridge levels | Bus Send/Reply replaces liaisons | #383 |
| "Engagement Team → Project Team → Job Team" | OM → PM → Project Lead → Workgroup agents | #394 |
| Context compression via liaison relay | Context compression via Send message (caller composes) | agent-dispatch proposal |
| Workspace isolation via worktrees | Session = worktree (1:1:1); job worktrees hierarchical | #384, #394 |

**Action:** Update to replace liaison model with bus dispatch model. Engagement layer can remain as future design. Add PM as the project-level coordinator. Update workspace isolation to describe the `{project}/.teaparty/jobs/` layout.

</details>

<details>
<summary><strong>4. <code>docs/detailed-design/index.md</code> — Implementation Status (HIGH)</strong></summary>

| What it says | Current reality | Ticket |
|---|---|---|
| Scope: "orchestrator layer at `projects/POC/orchestrator/`" | `teaparty/` package | #390 |
| Hierarchical Teams: "Two-level hierarchy works" | OM → PM → PL → workgroups (three levels) | #394 |
| CfA: no mention of INTERVENE/WITHDRAW | Implemented | #386, CfA-extensions proposal |
| No mention of unified launcher | `launch()` in `teaparty/runners/launcher.py` | #394 |
| No mention of bus dispatch | Send/Reply, conversation lifecycle | #383 |
| No mention of real-time streaming | All agents stream | #392 |
| References `projects/POC/` | Deleted; codebase is `teaparty/` | #390 |

**Action:** Full revision of scope, pillar status, and gap summary. Add new pillars: messaging/dispatch, configuration team, dashboard. Update all file path references.

</details>

<details>
<summary><strong>5. <code>docs/detailed-design/agent-runtime.md</code> — CLI Invocation (HIGH)</strong></summary>

| What it says | Current reality | Ticket |
|---|---|---|
| "POC orchestrator at `projects/POC/orchestrator/`" | `teaparty/` | #390 |
| Phase-driven execution: Intent → Planning → Execution | CfA phases still exist but orchestrator is different | #394 |
| `ClaudeRunner` builds subprocess command | `launch()` in `launcher.py` is the entry point; `ClaudeRunner` is a low-level wrapper | #394 |
| `AgentRunner` wraps `ClaudeRunner` | No `AgentRunner`; `launch()` handles everything | #394 |
| `EscalationListener` on Unix socket with `--mcp-config` | MCP server runs centrally; agents connect to it | #394 |
| `phase-config.json` references `agents/*.json` | Retired; agent definitions in `.teaparty/` format | #385 |
| `compose_claude_md` overwrites repo CLAUDE.md | Deleted; repo CLAUDE.md is never touched | #394 |

**Action:** Major rewrite to describe the unified launcher, worktree composition, session lifecycle, and stream processing. Update CLI invocation format for new flags (`--agent`, `--settings`, `--setting-sources user`).

</details>

<details>
<summary><strong>6. <code>docs/reference/folder-structure.md</code> — Directory Layout (HIGH)</strong></summary>

Every path reference is wrong:

| It says | Current reality | Ticket |
|---|---|---|
| `orchestrator/` at repo root | `teaparty/cfa/`, `teaparty/teams/`, etc. | #390 |
| `bridge/` at repo root | `teaparty/bridge/` | #390 |
| `scripts/` at repo root | `teaparty/cfa/statemachine/`, `teaparty/proxy/`, `teaparty/scripts/` | #390 |
| `agents/*.json` | `.teaparty/management/agents/`, `.teaparty/project/agents/` | #385 |
| `cfa-state-machine.json` at repo root | `teaparty/cfa/statemachine/cfa-state-machine.json` (verify) | #390 |
| Memory at `<project>/.sessions/MEMORY.md` | Learnings in session dirs, proxy memory in `.proxy-memory.db` | #384, #394 |
| Worktrees at repo root `.worktrees/` | `{project}/.teaparty/jobs/` for jobs; `.teaparty/{scope}/sessions/` for agent sessions | #384, #394 |

**Action:** Full rewrite to describe the current `teaparty/` package layout, `.teaparty/` config structure (management vs project scope), and session/job directory hierarchy.

</details>

<details>
<summary><strong>7. <code>docs/conceptual-design/human-proxies.md</code> — Proxy Agents (MEDIUM)</strong></summary>

The proxy's internal architecture (ACT-R memory, two-pass prediction, confidence model) is unchanged. What changed:

| Aspect | What it says | Current reality | Ticket |
|---|---|---|---|
| Proxy invoked at CfA gates | Proxy is a standalone agent with its own session | proxy-review proposal, #394 |
| Proxy review = inspect + correct + reinforce | Proxy review is a conversation via chat blade | #371, proxy-review proposal |
| Proxy memory shared with OM | Confirmed unchanged | office-manager proposal |

**Action:** Update the interaction model to describe proxy as a chat-blade participant, invoked via the unified launcher. The memory and prediction internals can remain as-is.

</details>

<details>
<summary><strong>8. <code>docs/conceptual-design/cfa-state-machine.md</code> — CfA Protocol (MEDIUM)</strong></summary>

The state machine itself (states, transitions, phases) is unchanged. What changed:

| Aspect | What it says | Current reality | Ticket |
|---|---|---|---|
| INTERVENE and WITHDRAW | Now implemented as CfA events | #386, CfA-extensions proposal |
| Execution via persistent team session | Execution via one-shot launch with `--resume` | #394 |
| EscalationListener on Unix socket | MCP server handles escalation via tools | #394 design |

**Action:** Add INTERVENE and WITHDRAW events. Update execution model description. Ensure the state transition table includes the new terminal states.

</details>

<details>
<summary><strong>9. <code>docs/detailed-design/cfa-state-machine.md</code> — State Implementation (MEDIUM)</strong></summary>

Verify:
- File location updated from `scripts/cfa_state.py` to `teaparty/cfa/statemachine/cfa_state.py`
- INTERVENE and WITHDRAW transitions added
- State table includes new events

**Action:** Update file references and verify transition table completeness.

</details>

<details>
<summary><strong>10. <code>docs/detailed-design/approval-gate.md</code> — Proxy Decision Model (MEDIUM)</strong></summary>

The proxy's internal decision model (confidence computation, two-pass prediction, ACT-R retrieval) is unchanged. However, the unified launcher (#394) altered the dispatch flow around gate invocation:

- The doc describes `ApprovalGate.run()` in `actors.py` invoking `consult_proxy()`, but the current gate flow uses `teaparty/proxy/approval_gate.py` and `teaparty/proxy/agent.py` with different invocation points.
- The `EscalationListener` integration may have changed with real-time streaming (#392).
- The doc's references to when gates fire in the dispatch lifecycle need updating for the unified launcher.

**Action:** Update gate invocation flow (when in the dispatch lifecycle `consult_proxy()` fires), verify `EscalationListener` paths post-#392, update file path references.

</details>

<details>
<summary><strong>11. <code>docs/detailed-design/heartbeat.md</code> — Session Telemetry (LOW)</strong></summary>

Verified: The heartbeat implementation in `teaparty/bridge/state/heartbeat.py` exactly matches the design spec. Structured `.heartbeat` JSON files, two-phase lifecycle, mtime-based staleness detection (120s stale, 300s dead), PID liveness checks — all unchanged. Real-time streaming (#392) has no impact on heartbeat mechanics.

**Action:** File path reference updates only.

</details>

<details>
<summary><strong>12. <code>docs/detailed-design/learning-system.md</code> — Memory Hierarchy (LOW)</strong></summary>

File references need updating (`orchestrator/learnings.py` → `teaparty/learning/extract.py`, etc.).

**Action:** Update file path references.

</details>

<details>
<summary><strong>13. <code>docs/detailed-design/act-r*.md</code> — ACT-R Memory Model (LOW)</strong></summary>

Pure design rationale document with no stale mechanism references. Implementation in `teaparty/proxy/memory.py` matches the described model (decay d=0.5, noise s=0.08, threshold tau=-0.5).

**Action:** Verify and update any file path references.

</details>

---

## New Documents Needed

M3 introduced load-bearing architectural concepts that have no design doc. Proposals describe intent; design docs describe the as-built system.

### Conceptual Design (the *why* and *what*)

<details>
<summary><strong>N1. <code>docs/conceptual-design/messaging.md</code> — Bus Architecture</strong></summary>

**Source:** messaging proposal, #383
**Why this is a gap:** The bus is the universal transport. Every agent-to-agent and human-to-agent interaction goes through it. This is the single biggest architectural addition in M3 and it has zero design documentation.
**Content:** Send/Reply model, conversation lifecycle (open/close/resume), routing rules derived from workgroup membership, conversation kinds (OM, PM, job, task, proxy, config), the write-then-exit-then-resume execution model, how `--resume` provides multi-turn continuity without persistent processes.

</details>

<details>
<summary><strong>N2. <code>docs/conceptual-design/team-configuration.md</code> — Configuration Tree</strong></summary>

**Source:** team-configuration proposal, workgroup-model proposal, #362-#374
**Why this is a gap:** The `.teaparty/` config tree is the source of truth for agent launch, roster derivation, skill availability, and MCP access. No doc describes the as-built system.
**Content:** Two scopes (management/project), registration vs membership, catalog merging with project-first precedence, D-A-I human roles, config vs runtime separation, scheduled tasks.

**Architectural invariants from workgroup-model proposal** (not captured by individual tickets):
- Communication flows through leads only — direct agent-to-agent is prohibited
- Humans are not members — they participate through proxies, never as dispatchable agents
- Skills are per-agent, not per-workgroup — each agent has its own allowlist
- Configuration authority does not cross project boundaries
- Direct edit for structured data; chat-in-context for prose and judgment calls
- Configuration workgroups sit outside the dispatch hierarchy (registered, never dispatched to)

The configuration-team proposal (specialist workgroup, MCP tools, agent definitions) should be a section within this document.

</details>

<details>
<summary><strong>N3. <code>docs/conceptual-design/office-manager.md</code> — Dispatch Chain and Human Interface</strong></summary>

**Source:** office-manager proposal, #394
**Why this is a gap:** The OM is the human's coordination partner and the top of the dispatch chain. The PM role is entirely new. No doc describes this organizational design.
**Content:** OM → PM → project lead dispatch chain, the PM role (one per project, mediates OM ↔ project lead), four entry points (OM chat, PM chat, proxy 1:1, new job), team-lead authority vs gate authority distinction, shared memory with proxy, steering chunks and intervention.

</details>

### Detailed Design (the *how*)

<details>
<summary><strong>N4. <code>docs/detailed-design/launcher.md</code> — Unified Agent Launch</strong></summary>

**Source:** #394, `docs/detailed-design/unified-agent-launch.md` (exists but reads as a build spec)
**Why this is a gap:** `unified-agent-launch.md` describes what to build. A detailed design doc should describe the as-built system.
**Content:** The `launch()` function contract, worktree composition steps (what gets copied into `.claude/`), session lifecycle (create/resume/close/withdraw), the 1:1:1 invariant (session = worktree = claude-session-id), metrics recording to `{scope}/metrics.db`, poisoned session detection, empty response recovery.
**Action:** Either rewrite `unified-agent-launch.md` as a detailed design doc or create a companion `launcher.md`.

</details>

<details>
<summary><strong>N5. <code>docs/detailed-design/messaging.md</code> — Bus Implementation</strong></summary>

**Source:** messaging proposal, #383, #392
**Content:** `SqliteMessageBus` storage, `BusEventListener` dispatch loop, conversation map in `metadata.json`, per-agent concurrency limits (3 slots), real-time stream processing via `_make_live_stream_relay`, WebSocket broadcast pipeline, `MessageRelay` class.

</details>

<details>
<summary><strong>N6. <code>docs/detailed-design/team-configuration.md</code> — Config Reader Implementation</strong></summary>

**Source:** team-configuration proposal, #373, #374
**Content:** `config_reader.py` internals, `merge_catalog()` logic, path conventions, MCP CRUD tools (19 tools from configuration-team proposal), agent definition resolution (project-first, fall back to management).

</details>

<details>
<summary><strong>N7. <code>docs/detailed-design/context-budget.md</code> — Context Budget and Scratch Files</strong></summary>

**Source:** context-budget proposal
**Why this is a gap:** Context budget monitoring IS implemented (`teaparty/util/context_budget.py`, `teaparty/util/scratch.py`) — but partially. No design doc describes what was built vs what remains a design target.

**Implemented:**
- `ContextBudget` class tracks token usage from stream-json `result` events
- Threshold detection at 70% (warning) and 78% (compaction)
- `/compact` injection at turn boundaries via `_check_context_budget()` in `teaparty/cfa/engine.py`
- `ScratchModel` creates `.context/` directory and handles `user` and `Write`/`Edit` tool events

**Not yet implemented (design targets from the proposal):**
- Stream content extraction for most categories (only user events and file-mod tools handled)
- Detail files (`.context/human-input.md`, `.context/dead-ends.md`) — methods exist but are not called
- Cost budget enforcement (warn at 80%, pause at 100%)
- Post-compaction scratch file reading by agents
- Progressive disclosure hierarchy

**Content for the design doc:** Document the as-built system, explicitly call out unimplemented design targets, describe the `ContextBudget` class contract and scratch file extraction flow.

</details>

### Reference

<details>
<summary><strong>N8. <code>docs/reference/dashboard.md</code> — Dashboard Architecture</strong></summary>

**Source:** dashboard-ui proposal, chat-experience proposal, ui-redesign proposal, #365-#389
**Content:** Screen hierarchy (index → config → workgroup → agent, plus chat and artifacts), chat blade contract (side panel, per-entity conversation, persistence via localStorage), filter system (9 types), subtask navigation (recursive tree), real-time event rendering via WebSocket.

</details>

---

## Potential Code/Design Discrepancies

These are cases where the implemented code diverges from the design established by closed tickets. They may be intentional, in-progress, or bugs.

<details>
<summary><strong>D1. <code>.teaparty/</code> runtime state not fully consolidated</strong></summary>

**Design (#394):** Runtime state should be consolidated into `{scope}/sessions/`. The old scattered dirs (`om/`, `pm/`, `proxy/`, `config/`) should not exist.

**Reality:** `.teaparty/management/sessions/` exists and contains session directories, but `.teaparty/om/`, `.teaparty/pm/`, `.teaparty/proxy/`, `.teaparty/config/` also still exist with active data (session files, message DBs).

**Assessment:** Partial migration. The old dirs may still be read by some code paths. Verify whether the bridge server or any module still reads from the old locations.

</details>

<details>
<summary><strong>D2. <code>.worktrees/</code> at repo root not fully retired</strong></summary>

**Design (#384):** `.worktrees/` at repo root should be retired; worktrees move to `{project}/.teaparty/jobs/`.

**Reality:** `.worktrees/` still exists with 15+ issue worktrees. `worktrees.json` is gone (retired as designed). `.teaparty/jobs/` exists with at least one job entry.

**Assessment:** Old worktrees may be pre-M3 artifacts or the fix-issue skill may still create worktrees in `.worktrees/`.

</details>

<details>
<summary><strong>D3. Worktrees inside agent config directories</strong></summary>

**Design (#394):** "Remove worktrees from agent config directories" is an explicit cleanup item.

**Reality:** `.teaparty/management/agents/project-manager/teaparty-project-manager-workspace/` exists — a full git worktree inside an agent config directory.

**Assessment:** Pre-#394 artifact. Design says session worktrees should be in `{scope}/sessions/`, not in agent config dirs.

</details>

<details>
<summary><strong>D4. <code>cfa-state-machine.json</code> location</strong></summary>

**Design (#390):** Should be at `teaparty/cfa/statemachine/cfa-state-machine.json`.

**Reality:** `cfa-state-machine.json` still exists at repo root. Verify if it was also copied to the target location or if only the root copy remains.

</details>

<details>
<summary><strong>D5. Session outputs still called "Artifacts" — rename incomplete</strong></summary>

**Design (#365):** Session output sections card should be renamed from "Artifacts" to "Sessions" to avoid collision with pinned-items card (which was renamed from "Pins" to "Artifacts").

**Reality:** "Pins" → "Artifacts" rename is complete. But session outputs are still labeled "Artifacts." Two different concepts share the same label.

**Assessment:** UI naming bug per #365 spec.

</details>

<details>
<summary><strong>D6. <code>.teaparty/jobs/</code> exists outside unified sessions structure</strong></summary>

**Design (#394):** Jobs tracked via a catalog pointing to sessions in `{scope}/sessions/`. The catalog is an index, not a container.

**Reality:** `.teaparty/jobs/` exists as a separate directory with `jobs.json` and job subdirectories. This is from #384's design, which predates #394.

**Assessment:** The two designs (#384 job layout and #394 session layout) need reconciliation. #394 should supersede as the later design.

</details>

<details>
<summary><strong>D7. Overview.md Technology Stack references <code>projects/POC/</code></strong></summary>

**Design (#390):** POC directory deleted. All code under `teaparty/`.

**Reality:** `docs/overview.md` lines 193-194 still reference `projects/POC/orchestrator/` and `projects/POC/bridge/`.

**Assessment:** Documentation not updated after restructuring. Actively misleading for agents reading docs.

</details>

---

## Tickets Supersession Chain

Later tickets supersede or refine earlier ones. When reconciling design intent, the later ticket wins.

| Later ticket | Supersedes/refines | What changed |
|---|---|---|
| #394 (unified launch) | #385 (team unification), #392 (streaming), #384 (job worktrees) | Unified all agent launch; defined session=worktree=claude-session-id 1:1:1; introduced PM role; defined directory structure |
| #393 (/clear fix) | — | Full reset semantics: clear bus, kill subprocesses, release worktrees |
| #392 (streaming) | — | All agents stream events (was OM-only); real-time not batch |
| #383 (conversation lifecycle) | — | Conversations have open/close state owned by originator; `--resume` for follow-ups; multiple parallel conversations per agent |
| #385 (team unification) | — | `agents/*.json` retired; all definitions in `.teaparty/` format |
| #384 (job worktrees) | — | Hierarchical job/task layout; `worktrees.json` retired |
| #380 (toggle fix) | #367 (catalog display) | Fixed click handler conflict introduced by #367's toggle |
| #371 (chat blade) | #372 (discuss button) | Chat blade on every screen supersedes per-screen discuss buttons |
