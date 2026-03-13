# Docs Rewrite Research Report

Produced to drive the five-pass rewrite plan. All findings are based on direct
inspection of the worktree at
`/Users/darrell/git/teaparty/projects/POC/.worktrees/session-112714--the-docs-folder-contains-the-p/`.

---

## 1. File Inventory

### docs/*.md — 16 files

| File | Approx lines | One-sentence description |
|------|-------------|--------------------------|
| `ARCHITECTURE.md` | 289 | Platform-level conceptual model: corporate hierarchy, work hierarchy (job/project/engagement), conversation kinds, agent model, workspace model, and tech stack. |
| `UX.md` | ~120 | Design philosophy and UI principles for the TeaParty chat/collaboration interface. |
| `agent-dispatch.md` | 246 | How messages are routed to agents, how team sessions work, and the hierarchical dispatch flow including liaison-to-subteam mechanics. |
| `cfa-state-machine.md` | 243 | Formal description of the three-phase CfA state machine (Intent, Planning, Execution) with mermaid diagrams, actors, and backtrack transitions. |
| `cognitive-architecture.md` | ~400+ | Future-phase design: research-grounded cognitive architecture for learning agents (episodic, semantic, procedural memory), labeled Phase 3. |
| `engagements-and-partnerships.md` | 299 | Full engagement lifecycle, partnership directionality and lifecycle, org lead orchestration, workspace visibility, cycle prevention, and file structure. |
| `file-layout.md` | 315 | Virtual file tree for the TeaParty platform: full tree with scopes, config files, tools/toolkits, templates, and git/virtual-file coexistence. |
| `folder-structure.md` | 124 | POC-specific directory layout: org at top, projects as separate git repos, memory hierarchy, worktree isolation, and the dogfooding setup. |
| `hierarchical-teams.md` | 498 | Deep design for hierarchical Claude Code team sessions: team composition (job/project/engagement teams), liaison agent spec, `relay_to_subteam` tool, execution flows, failure handling. |
| `human-proxies.md` | 77 | Autonomy-oversight dilemma, least-regret escalation, proxy learning (preferential and task-based), cold-start-to-warm-start progression. |
| `index.md` | ~40 | Top-level entry-point doc: the four pillars of TeaParty (context scoping, context rot, learning/retrieval, human oversight). |
| `intent-engineering.md` | 126 | Intent engineering as a UX project: intent gathering dialog, principle of "bring solutions not questions," relationship to institutional memory, and open questions. |
| `learning-system.md` | 305 | Full learning system design: three learning types (institutional, task-based, proxy), scope × type taxonomy, retrieval architecture (always-loaded vs fuzzy), promotion chain, confidence/decay, and research references. |
| `poc-architecture.md` | 527 | Deep dive into the POC implementation: two-level hierarchy (uber/sub), dispatch.sh bridge, worktree model, memory hierarchy, stream-json parsing, CLI flags, env vars, and agent lifecycle. |
| `sandbox-design.md` | ~800 | Future-phase design (Phases 4–5): Docker containers, git repos per workgroup, job worktrees, Claude Code CLI delegation, sandbox tool suite. |
| `workflows.md` | ~80 | Workgroup workflow playbooks: markdown files in `files/workflows/`, discovery/execution via toolkit tools, state tracking per job. |

### docs/research/ — 5 files (filenames only)

- `cognitive-architectures-supplement.md`
- `INDEX.md`
- `python-state-machine-libraries.md`
- `python-statemachine-persistence.md`
- `textual-tui-selection-widgets.md`

### projects/POC/docs/ — 7 files (filenames only)

- `agentic-cfa-spec.docx`
- `GLOSSARY.md`
- `intent-engineering-detailed-design.md`
- `intent-engineering-spec.md`
- `learning-system.md`
- `POC.md`
- `PROXY_WIRE_TASK.md`

---

## 2. Open Question 1 — What Is Built vs. Designed?

### Verification: What Is Actually Present in projects/POC/orchestrator/

The following files were confirmed present by directory listing:

**`projects/POC/orchestrator/`** — 15+ Python files:

| File | What it does |
|------|-------------|
| `engine.py` | CfA state loop. Drives the state machine from current state to terminal state by invoking actors at each step. Replaces the shell control flow of `run.sh`, `intent.sh`, and `plan-execute.sh`. Imports `cfa_state.py` for state transitions. |
| `worktree.py` | Git worktree management. Creates session worktrees (`create_session_worktree`) and dispatch worktrees. Replaces worktree creation/cleanup logic formerly in `run.sh` and `dispatch.sh`. |
| `learnings.py` | Post-session learning extraction. Implements all 10 scopes of the promote_learnings pipeline: observations, escalation, intent-alignment, team/session/project/global rollups, and prospective/in-flight/corrective temporal scopes. |
| `actors.py` | Actor types: `AgentRunner`, `ApprovalGate`, `InputProvider`. These are the callable agents at each CfA state. |
| `claude_runner.py` | Runs `claude -p` subprocesses, handles stream-json output. |
| `dispatch_cli.py` | CLI entry point for dispatch operations. |
| `session.py` | Session lifecycle management. |
| `events.py` | `Event`, `EventBus`, `EventType`, `InputRequest` — the event system for inter-component communication. |
| `phase_config.py` / `phase-config.json` | Per-phase configuration (which actor runs in which state). |
| `state_writer.py` | Persists CfA state to disk. |
| `tui_bridge.py` | Bridge between orchestrator events and the TUI. |
| `watchdog.py` | Stall detection for hung processes. |
| `merge.py` | Git merge operations for worktree completion. |

**`projects/POC/scripts/cfa_state.py`** — Confirmed present. Implements the runtime CfA state machine API: loads from `cfa-state-machine.json`, provides `transition()`, `save_state()`, `is_phase_terminal()`, `is_globally_terminal()`, `phase_for_state()`. Pure stdlib, no external dependencies.

**`projects/POC/cfa-state-machine.json`** — Confirmed present. The single source of truth for all CfA states and valid transitions. `cfa_state.py` loads from this file at runtime.

**`projects/POC/scripts/`** — 20+ Python files including:
- `human_proxy.py` — proxy model implementation
- `approval_gate.py` — approval gate logic
- `memory_indexer.py` — memory indexing
- `summarize_session.py` — learning extraction runner
- `classify_task.py` — project classification
- `generate_confidence_posture.py`, `generate_dialog_response.py`, etc. — LLM-backed generation scripts

**`projects/POC/agents/*.json`** — 8 team definitions: `uber-team.json`, `coding-team.json`, `writing-team.json`, `art-team.json`, `research-team.json`, `editorial-team.json`, `intent-team.json`, `project-team.json`.

### Built in POC vs. Platform/Designed

**Built in POC (implemented in `projects/POC/`):**

| Feature | Evidence |
|---------|---------|
| Two-level uber/sub hierarchy | `agents/uber-team.json`, `dispatch_cli.py`, `poc-architecture.md` |
| CfA state machine (3-phase: Intent, Planning, Execution) | `cfa-state-machine.json` + `scripts/cfa_state.py` + `orchestrator/engine.py` |
| Git worktree isolation per session/dispatch | `orchestrator/worktree.py` |
| Learning extraction (10 scopes, 3 temporal moments) | `orchestrator/learnings.py` + `scripts/summarize_session.py` + `scripts/promote_learnings.sh` |
| Human proxy model | `scripts/human_proxy.py` + `scripts/approval_gate.py` |
| Stall watchdog | `orchestrator/watchdog.py` |
| TUI dashboard | `projects/POC/tui/` |
| Stream-json parsing and display | `stream/display_filter.py` (referenced in `poc-architecture.md`) |
| Project classification via LLM | `scripts/classify_task.py` |
| Memory indexing (memsearch integration) | `scripts/memory_indexer.py` |

**Platform/Designed (described in docs but lives in `teaparty_app/`, not in this worktree):**

| Feature | Doc source |
|---------|-----------|
| Corporate hierarchy (Home/Org/Workgroup data model) | `ARCHITECTURE.md` |
| Engagement and partnership lifecycle | `engagements-and-partnerships.md` |
| Virtual file tree + file scoping | `file-layout.md` |
| Team session infrastructure (`TeamSession`, `team_registry.py`, `team_bridge.py`) | `agent-dispatch.md` |
| `relay_to_subteam` tool + liaison agent generation | `hierarchical-teams.md` (marked as new components needed) |
| Async notification bridge | `hierarchical-teams.md` (marked as new components needed) |
| Org-level orchestration tools (`create_project`, `create_job`, etc.) | `engagements-and-partnerships.md` |
| Docker sandbox + git repos per workgroup | `sandbox-design.md` (explicitly labeled Future Phase 4–5) |
| Cognitive architecture (per-agent episodic/semantic memory) | `cognitive-architecture.md` (explicitly labeled Future Phase 3) |
| UX / frontend | `UX.md` |
| Workgroup workflows | `workflows.md` |

**Key distinction:** The POC implements the *orchestration runtime* (CfA state machine, worktree isolation, learning extraction, human proxy, dispatch loop). The platform docs describe the *multi-tenant collaboration layer* (org hierarchy, engagements, virtual files, team session infrastructure). These are complementary but separate. The POC's uber/sub hierarchy maps conceptually to the platform's project-team/job-team model, but the POC's actual code is a standalone orchestrator, not a TeaParty platform feature.

---

## 3. Open Question 2 — Should ARCHITECTURE.md Be Split or Summarized?

### Size and Structure of ARCHITECTURE.md

`ARCHITECTURE.md` is **289 lines** and has these major sections:

1. `## Corporate Hierarchy` — Home, Organization, Workgroup, Partnerships (with ASCII diagram)
2. `## Work Hierarchy` — Job, Project, Engagement (with ASCII diagram)
3. `## Conversation Kinds` — routing table by kind
4. `## Human Interaction Model` — what humans can/cannot do, feedback bubble-up model
5. `## Agent Model` — agent philosophy, agent types table
6. `## Cycle Prevention` — engagement chain mechanism
7. `## Workspace and Filestore Model` — virtual vs. git files, job workspace isolation
8. `## Technology Stack` — tech table
9. `## Open Questions` — 5 questions
10. `## Further Reading` — links to sub-docs

### Do Sub-Docs Cover ARCHITECTURE.md's Sections Adequately?

| ARCHITECTURE.md section | Sub-doc coverage |
|------------------------|-----------------|
| Corporate Hierarchy (Home/Org/Workgroup/Partnerships) | Partially in `engagements-and-partnerships.md` (org lead, partnerships) and `agent-dispatch.md` (lead agents table). Neither fully replicates the hierarchy diagram or Home/Workgroup descriptions. |
| Work Hierarchy (Job/Project/Engagement) | Substantially covered in `hierarchical-teams.md` (team composition and execution flows) and `engagements-and-partnerships.md` (engagement lifecycle). The ARCHITECTURE.md treatment is the conceptual summary; sub-docs are the operational detail. |
| Conversation Kinds routing table | Only in `agent-dispatch.md`. ARCHITECTURE.md has a 7-row summary table; `agent-dispatch.md` has the same table plus full dispatch mechanics. **Redundant.** |
| Human Interaction Model | The feedback bubble-up model appears in both `ARCHITECTURE.md` and `engagements-and-partnerships.md` (near-identical content). **Redundant.** |
| Agent Model | `agent-dispatch.md` covers lead agents. `hierarchical-teams.md` covers liaison agents. ARCHITECTURE.md's agent types table is unique here. |
| Cycle Prevention | Appears in both `ARCHITECTURE.md` (brief) and `engagements-and-partnerships.md` (full mechanism with depth limits). **Partially redundant.** |
| Workspace/Filestore | `file-layout.md` covers the full virtual tree and job workspace isolation in depth. ARCHITECTURE.md's section is a high-level summary. |
| Technology Stack | Unique to ARCHITECTURE.md. |
| Open Questions | See Section 4 below. |

### Recommendation: Option B — Summarize + Point

**Rationale:** ARCHITECTURE.md functions correctly as a conceptual entry point. Its Corporate Hierarchy and Work Hierarchy sections with their ASCII diagrams provide orientation that no sub-doc replicates. Removing those would leave readers without a navigable overview. The right action is to trim the genuinely redundant content (Conversation Kinds routing table, verbatim feedback bubble-up model, cycle prevention detail) and replace each with a one-sentence summary + link to the sub-doc that owns the detail. This reduces ARCHITECTURE.md to a true architecture overview (~180 lines) while keeping it readable standalone. Splitting further would fragment the conceptual model that currently lives in one place.

---

## 4. Open Question 3 — Open Questions: Distributed or Consolidated?

### Files With "Open Questions" Sections

| File | Approx # of questions | Topic |
|------|-----------------------|-------|
| `ARCHITECTURE.md` | 5 | Contract-based visibility, cycle prevention mechanics, home agent discovery, partnership revocation mid-engagement, legacy data model cleanup |
| `engagements-and-partnerships.md` | 3 | Contract-based visibility implementation, partnership revocation during active engagement, engagement pricing/payments |
| `intent-engineering.md` | 4 | Learning from downstream outcomes, stated vs. revealed preferences divergence, minimum viable memory architecture, domain segmentation for escalation |
| `sandbox-design.md` | 6 | Container orchestration tool, Claude Code invocation mode, conflict resolution strategy, file browser source of truth, cost attribution, warm pool sizing |
| `learning-system.md` | 5 | Embedding model choice, scope multiplier calibration, cross-type retrieval, proxy model validation, cold start ramp rate |

**Total: ~23 open questions across 5 files.**

`cognitive-architecture.md` does not have a formal Open Questions section (its open questions are embedded in prose). `hierarchical-teams.md`, `human-proxies.md`, `folder-structure.md`, `file-layout.md`, `workflows.md`, `agent-dispatch.md`, `hierarchical-teams.md`, `poc-architecture.md`, `cfa-state-machine.md`, `UX.md`, and `index.md` have no Open Questions sections.

### Overlap in Distributed Questions

`ARCHITECTURE.md` Q1 (contract-based visibility) and `engagements-and-partnerships.md` Q1 (contract-based visibility implementation) are near-identical. `ARCHITECTURE.md` Q4 (partnership revocation) and `engagements-and-partnerships.md` Q2 are the same question. This is direct duplication of questions across two files.

### Recommendation: Consolidate into research-directions.md

**Rationale:** The questions are currently scattered, duplicated between `ARCHITECTURE.md` and `engagements-and-partnerships.md`, and mixed with operational content in ways that make it unclear whether a doc is normative or exploratory. Consolidating into a single `docs/research-directions.md` (or keeping the existing `docs/research/INDEX.md` as the target) provides one place to find unsettled questions, removes the need for readers to evaluate every doc for uncertainty signals, and lets the main docs be purely descriptive. The individual docs should retain a brief cross-reference ("see `research-directions.md` for open implementation questions") but not carry the question bodies themselves. Questions from `sandbox-design.md` and `cognitive-architecture.md` are particularly well-suited for removal from those docs since both are already labeled as future-phase.

---

## 5. Overlap and Duplication Pairs

### folder-structure.md vs. file-layout.md

These address different subjects and overlap only partially:

| Dimension | `folder-structure.md` | `file-layout.md` |
|-----------|----------------------|-----------------|
| Focus | POC project's actual directory layout on disk | Platform's virtual file tree (JSON-stored, conceptual) |
| Audience | POC users/developers working with the existing codebase | Platform architects and agent developers |
| Content unique to it | `.claude/agents/`, `projects/` as separate git repos, memory hierarchy paths, dogfooding setup, worktree model | Full virtual tree with all entity types, scopes table, config files table, tools/toolkit registry, templates structure, git+virtual coexistence |
| Shared content | Memory hierarchy concept, git worktree isolation concept | Same |

**Verdict:** Moderate conceptual overlap (both describe "where things live"), but they describe different things — the POC's filesystem vs. the platform's virtual tree. They should not be merged. However, `folder-structure.md` currently mixes POC-specific layout (accurate, POC-built) with platform aspirational layout (the corporate hierarchy diagram at top). The platform portion of `folder-structure.md` is partially redundant with `file-layout.md`. In a rewrite, `folder-structure.md` should be narrowed to POC-only layout and the platform portions removed or pointed to `file-layout.md`.

### ARCHITECTURE.md vs. engagements-and-partnerships.md

**Substantial overlap** in three areas:

1. **Engagement lifecycle:** `ARCHITECTURE.md` describes the engagement lifecycle states (`proposed -> negotiating -> accepted -> in_progress -> completed -> reviewed`). `engagements-and-partnerships.md` describes the same lifecycle with identical state names and more operational detail (what happens in each state).

2. **Feedback bubble-up model:** `ARCHITECTURE.md` section "Feedback Bubble-Up Model" and `engagements-and-partnerships.md` section "Feedback Bubble-Up Model" are near-identical — same diagram shape, same 5-step description. This is direct duplication.

3. **Org lead role:** Both describe the org lead's responsibilities (receive, negotiate, decompose, track, deliver). `engagements-and-partnerships.md` goes deeper on the org lead tools; `ARCHITECTURE.md` is shorter but covers the same ground.

4. **Open Questions:** Two questions are verbatim duplicates across both files (contract visibility, partnership revocation).

**Verdict:** `ARCHITECTURE.md` should treat engagements at the conceptual level only (one paragraph + link) and remove the detailed lifecycle states, feedback model, and cycle prevention detail. `engagements-and-partnerships.md` owns those topics.

### poc-architecture.md vs. other docs

`poc-architecture.md` (527 lines) is the most self-contained doc in the set — it describes the POC implementation specifically. It overlaps with:

| Doc | Overlap |
|-----|---------|
| `hierarchical-teams.md` | Both describe uber/sub hierarchy and liaison pattern. `poc-architecture.md` describes what is built; `hierarchical-teams.md` describes the platform design. Conceptually the same pattern, different implementations. |
| `folder-structure.md` | Both describe the POC's memory hierarchy (`dispatch → team → session → project → global`) and git worktree model. `poc-architecture.md` is more detailed; `folder-structure.md` covers it at a higher level. |
| `learning-system.md` | `poc-architecture.md` describes the promotion chain and learning scopes in the context of the POC implementation. `learning-system.md` designs the generalized learning system. `poc-architecture.md`'s "Automated Learning Extraction" and "Promotion Chain" sections cover ground that `learning-system.md` builds on. |
| `cfa-state-machine.md` | `poc-architecture.md`'s process model (plan → approve → execute) is the behavioral surface of the CfA state machine. `cfa-state-machine.md` is the formal state specification. No direct content duplication, but they describe the same underlying mechanism at different levels. |

**Verdict:** `poc-architecture.md` is justified as the single implementation reference for the POC. Its overlaps with `hierarchical-teams.md` and `learning-system.md` are design-vs-implementation overlaps (different abstraction levels), not identical content. The `folder-structure.md` overlap on memory hierarchy and worktrees is the most redundant — in a rewrite, `folder-structure.md` should point to `poc-architecture.md` rather than re-describe those subsystems.

---

## 6. Summary of Findings for Rewrite Planning

| Question | Answer |
|----------|--------|
| Total docs to rewrite | 16 in `docs/*.md`, plus awareness of 7 in `projects/POC/docs/` |
| ARCHITECTURE.md action | Summarize + point (option B). Trim ~100 lines of content that duplicates sub-docs. Keep hierarchy diagrams, agent model, tech stack. Remove verbatim feedback model, conversation kinds routing table, and cycle prevention detail. |
| Open questions action | Consolidate into `research-directions.md`. Remove question bodies from individual docs; replace with single cross-reference line. |
| folder-structure.md action | Narrow to POC-only; remove platform hierarchy content (it belongs in `file-layout.md`). |
| engagements-and-partnerships.md action | No structural change needed — it owns its topic. Remove the two questions that duplicate `ARCHITECTURE.md` once both are consolidated. |
| poc-architecture.md action | No structural change needed — it is the authoritative POC implementation reference. Ensure `folder-structure.md` points here for memory hierarchy and worktree details rather than restating them. |
| cognitive-architecture.md and sandbox-design.md | Both are clearly labeled as future-phase. In the rewrite, add a consistent "Future Phase" callout box at the top and move their open questions to `research-directions.md`. |
| Duplicate content hot spots | Feedback bubble-up model (ARCHITECTURE.md ↔ engagements-and-partnerships.md), contract visibility question (same two files), engagement lifecycle states (same two files). All three should live only in `engagements-and-partnerships.md`. |
