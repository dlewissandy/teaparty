# CfA Spec vs. Implementation: Discrepancy Audit
Generated: 2026-03-08

---

## Audit Limitations

> `docs/agentic-cfa-spec.docx` (21KB) could not be read during this audit. The `python-docx` library is not available in the execution environment and no plain-text rendering was found. Discrepancies attributed to this document — particularly the claimed "six-role recursive state machine" — are unverified and marked *alleged* rather than confirmed. A complete audit requires either: (a) converting the docx to markdown/text, or (b) extracting its content via a platform with Word support.

---

## Summary Table

| ID | Title | Severity | Spec Source | Code Source |
|----|-------|----------|-------------|-------------|
| D1 | State count: 25 actual vs. 29 claimed | Structural | backlog/cfa-as-claude-skill.md, lines 48 and 119 | cfa-state-machine.json, phases block; scripts/cfa_state.py |
| D2 | Actor count: 7 actual vs. alleged 6-role model | Structural (alleged) | docs/agentic-cfa-spec.docx (unreadable) | cfa-state-machine.json, transitions block lines 19–127 |
| D3 | Depth constraint: prose-only, not enforced | Structural | docs/POC.md, line 495 | scripts/cfa_state.py lines 77–130 |
| D4 | `--set-state` bypass is the dominant orchestration pattern | Structural | docs/GLOSSARY.md lines 1–15; cfa-state-machine.json | scripts/cfa_state.py lines 293–325; worktree intent.sh, plan-execute.sh |
| D5 | WORK_ASSERT: approval_gate as sole actor with no human escape path | Structural | docs/GLOSSARY.md lines 29–34; docs/intent-engineering-detailed-design.md | cfa-state-machine.json lines 118–124 |
| D6 | `--no-plan` flag bypasses planning phase with no spec authorization | Behavioral | docs/GLOSSARY.md; docs/intent-engineering-spec.md; docs/POC.md (no mention) | worktree plan-execute.sh lines 41, 61, 575–581, 725, 894–899 |
| D7 | Section 8.1 warm-start behavior: spec written, not implemented | Behavioral | docs/intent-engineering-detailed-design.md, Section 8.1, approx. line 451 | worktree intent.sh line 52 (comment only) |
| D8 | WORK_ESCALATE absent: work-aggregate level has no escalation path | Behavioral | cfa-state-machine.json (implicit symmetry with TASK_ESCALATE) | cfa-state-machine.json execution phase; scripts/approval_gate.py lines 70–74 |
| D9 | CfA acronym expansion: three incompatible definitions | Naming | docs/GLOSSARY.md, first definition line | cfa-state-machine.json; scripts/cfa_state.py line 2; backlog/cfa-as-claude-skill.md |
| D10 | `human_proxy.py` referenced but file is `approval_gate.py` | Naming | docs/PROXY_WIRE_TASK.md, lines 12, 14, 31, 56 | scripts/approval_gate.py (present); human_proxy.py (absent) |
| D11 | Context-aware proxy Phase 3 (LLM-assisted review) not implemented | [BACKLOG] | backlog/context-aware-proxy.md, approx. line 78 | scripts/approval_gate.py (full implementation) |
| D12 | Deletion targets still present | [BACKLOG] | backlog/cfa-as-claude-skill.md, lines 102–106 | scripts/classify_review.py; scripts/generate_review_bridge.py; scripts/generate_dialog_response.py |
| D13 | PROXY_WIRE_TASK.md describes a gap that no longer exists | [BACKLOG] | docs/PROXY_WIRE_TASK.md | worktree ui.sh lines 412–445; worktree intent.sh line 232 |

---

## Structural Discrepancies

### D1 — State count: 25 actual vs. 29 claimed

**Spec says**: "29 states" — *backlog/cfa-as-claude-skill.md, lines 48 and 119 (stated twice)*

**Code does**: `cfa-state-machine.json` defines exactly 25 states across three phases: Intent (7: IDEA, PROPOSAL, INTENT_QUESTION, INTENT_ESCALATE, INTENT_ASSERT, INTENT_RESPONSE, INTENT), Planning (6: DRAFT, PLANNING_QUESTION, PLANNING_ESCALATE, PLAN_ASSERT, PLANNING_RESPONSE, PLAN), Execution (12: TASK, TASK_IN_PROGRESS, TASK_QUESTION, TASK_ESCALATE, TASK_ASSERT, TASK_RESPONSE, FAILED_TASK, COMPLETED_TASK, WORK_IN_PROGRESS, WORK_ASSERT, COMPLETED_WORK, WITHDRAWN). `cfa_state.py` loads entirely from this JSON — the runtime total is 25. — *cfa-state-machine.json, phases block lines 5–15; scripts/cfa_state.py*

**Gap**: Four states claimed in the vision doc do not exist in the JSON or runtime state machine.

**Severity**: Structural

---

### D2 — Actor count: 7 actual vs. alleged 6-role model

**Spec says**: "six-role recursive state machine" — *docs/agentic-cfa-spec.docx (alleged; document unreadable — see Audit Limitations)*

**Code does**: `cfa-state-machine.json` transitions use 7 distinct actor values: `human`, `intent_team`, `research_team`, `planning_team`, `execution_lead`, `execution_worker`, `approval_gate`. The seventh actor (`approval_gate`) appears in TASK_ESCALATE, TASK_IN_PROGRESS, FAILED_TASK, WORK_IN_PROGRESS, and WORK_ASSERT. — *cfa-state-machine.json, all `actor` fields in transitions block lines 19–127*

**Gap**: If the docx "six-role" model is accurate, the `approval_gate` actor is either undocumented or miscounted; any role-based access or audit reasoning based on a six-role model will miss the seventh actor.

**Severity**: Structural (pending docx access — claim is alleged)

---

### D3 — Depth constraint: prose-only, not enforced

**Spec says**: "Two levels only (uber + subteams). No recursive hierarchies." — *docs/POC.md, line 495*

**Code does**: `CfaState` dataclass has `depth: int = 0` field (cfa_state.py line 88); `make_child_state()` (lines 108–130) increments `depth` with `depth=parent.depth + 1` and imposes no maximum. No assertion, guard, or conditional check prevents depth from exceeding 1. — *scripts/cfa_state.py lines 77–130*

**Gap**: The two-level architectural invariant is documented as a hard constraint but is not enforced in the state machine; a caller can create depth-2 or deeper child states without code-level rejection.

**Severity**: Structural

---

### D4 — `--set-state` bypass is the dominant orchestration pattern

**Spec says**: CfA is defined as "a three-phase state machine" with explicit validated transitions — *docs/GLOSSARY.md, lines 1–15; cfa-state-machine.json (transition table with actor/action/to fields)*. No spec document describes or authorizes bypassing the transition table.

**Code does**: `cfa_state.py` lines 293–325 define `set_state_direct()`, described in its own docstring as "the pragmatic escape hatch for the shell orchestration layer" that "bypasses transition validation." `ui.sh` wraps it as `cfa_set()` (lines 400–405) and `intent.sh` wraps it as `intent_cfa_set()` (lines 110–116), both calling `python3 cfa_state.py --set-state`. This bypass is used at approximately 9+ call sites in `intent.sh` and throughout `plan-execute.sh` — it is the **dominant** state-advancement pattern. Validated `--transition` calls exist but are secondary. Most CfA state changes are logged as synthetic `'action': 'set-state'` history entries, not as validated transitions. — *scripts/cfa_state.py lines 293–325, 558–572; worktree ui.sh lines 400–405; worktree intent.sh lines 110–116, call sites at approx. lines 229, 326, 343, 364, 380, 386, 394, 452, 458*

**Gap**: The state machine's transition validation layer — which enforces actor/action/target rules — is largely bypassed in practice. The transition table's invariants are enforced by shell code structure and timing, not by the state machine's own validation logic.

**Severity**: Structural

---

### D5 — WORK_ASSERT: approval_gate as sole actor with no human escape path

**Spec says**: `docs/intent-engineering-detailed-design.md` contains **no mention of WORK_ASSERT** anywhere. `docs/GLOSSARY.md` (lines 29–34) describes the Approval Gate as "a learned confidence model... that predicts whether a human would approve a given plan or result. Used to auto-route decisions when confidence is high, and escalate to the human when confidence is low." — framed as a routing/prediction component, not a first-class actor with decision authority.

**Code does**: `cfa-state-machine.json` lines 118–124 list `approval_gate` as the sole actor for all five WORK_ASSERT transitions: `approve → COMPLETED_WORK`, `correct → TASK_RESPONSE`, `revise-plan → PLANNING_RESPONSE` (backtrack), `refine-intent → INTENT_RESPONSE` (backtrack), `withdraw → WITHDRAWN`. There is no `human` actor path out of WORK_ASSERT — the gate cannot escalate to a human at this state. — *cfa-state-machine.json lines 118–124; docs/GLOSSARY.md lines 29–34; docs/intent-engineering-detailed-design.md (no WORK_ASSERT mention)*

**Gap**: The design spec is entirely silent on WORK_ASSERT; the JSON gives approval_gate full and exclusive decision authority over the final work review gate (including backtracking and withdrawal), which is irreconcilable with the GLOSSARY's framing of it as a confidence-based routing aid that escalates to humans when uncertain.

**Severity**: Structural

---

## Behavioral Discrepancies

### D6 — `--no-plan` flag bypasses planning phase with no spec authorization

**Spec says**: CfA is defined as a mandatory three-phase lifecycle (Intent → Planning → Execution) with required review gates. No spec document (GLOSSARY.md, intent-engineering-spec.md, intent-engineering-detailed-design.md, POC.md) mentions, authorizes, or describes a planning bypass mode. Sole documentation: a completed-checkbox line in `docs/IMPLEMENTATION_PROGRESS.md` line 24: `- [x] [2D] plan-execute.sh — add --no-plan flag`. — *docs/GLOSSARY.md, docs/intent-engineering-spec.md, docs/intent-engineering-detailed-design.md, docs/POC.md (no matches); docs/IMPLEMENTATION_PROGRESS.md line 24 (only mention)*

**Code does**: `plan-execute.sh` (line 61) accepts `--no-plan`. When set: (1) the planning agent is never invoked and `plan.md` is never produced (lines 575–581), (2) `PLAN_ASSERT` and its approval gate are skipped (line 725), (3) execution proceeds using the original task string as the prompt (lines 894–899). The script sets state directly to `PLAN` via `cfa_set` without running the planning phase. — *worktree plan-execute.sh lines 41, 61, 575–581, 725, 894–899*

**Gap**: A full CfA phase (planning) and its approval gate (PLAN_ASSERT) can be eliminated at invocation time with no spec authorization, no rationale, and no documented constraints on when this bypass is appropriate.

**Severity**: Behavioral

---

### D7 — Section 8.1 warm-start behavior: spec written, not implemented

**Spec says**: Section 8.1 "intent.sh Changes Required" in `docs/intent-engineering-detailed-design.md` (approximately line 451) specifies: "When warm-start context is present and confidence is high (mean confidence of pre-populated observations > 0.75), the max rounds should be reduced from 10 to 6." The section describes querying `memory_indexer.py` to retrieve warm-start observations. — *docs/intent-engineering-detailed-design.md, Section 8.1, approx. line 451*

**Code does**: `intent.sh` (worktree line 52) has a `# ── Build initial prompt with warm-start context ──` comment and inlines context files passed via `--context-file` flags. No `memory_indexer.py` invocation exists. The round reduction (10 → 6) is present but the triggering condition (memory_indexer query + confidence threshold) is not implemented. — *worktree intent.sh line 52 (comment only, no memory_indexer call)*

**Gap**: The warm-start behavior defined in Section 8.1 (memory query + confidence-gated round reduction) is documented in the spec but not implemented in the shell script; the round reduction may happen but through a simpler heuristic, not the specified confidence-based mechanism.

**Severity**: Behavioral

---

### D8 — WORK_ESCALATE absent: work-aggregate level has no escalation path

**Spec says**: The CfA review gate model implies symmetry: each phase has assertion and escalation states. TASK_ESCALATE exists for mid-execution escalation. By analogy, a work-aggregate escalation state would be expected. — *cfa-state-machine.json (implicit: TASK_ESCALATE present)*

**Code does**: The JSON defines no `WORK_ESCALATE` state. At the work-aggregate level (WORK_ASSERT), the agent can only approve, correct, revise-plan, refine-intent, or withdraw — there is no mid-review escalation or clarification path. The `GENERATIVE_STATES` set in `approval_gate.py` (lines 70–74) correctly omits WORK_ESCALATE (consistent with the JSON). — *cfa-state-machine.json execution phase, lines 13–14; scripts/approval_gate.py lines 70–74*

**Gap**: The work review gate is more constrained than other review gates — agents cannot seek targeted clarification on specific work items before committing to approve or reject; they must decide with the information available.

**Severity**: Behavioral (design asymmetry — may be intentional, but undocumented)

---

## Naming / Terminology

### D9 — CfA acronym expansion: three incompatible definitions

**Spec says**: "CfA (Confidence-for-Action)" — *docs/GLOSSARY.md, first definition line*

**Code does**: `cfa-state-machine.json` description field: "Conversation for Action (CfA)"; `scripts/cfa_state.py` module docstring: "Conversation for Action (CfA)"; `backlog/cfa-as-claude-skill.md` throughout: "Conversation-for-Agentic-Action" — *cfa-state-machine.json description; scripts/cfa_state.py line 2; backlog/cfa-as-claude-skill.md passim*

**Gap**: Three different acronym expansions appear across documents — "Confidence-for-Action" (GLOSSARY), "Conversation for Action" (JSON + Python), "Conversation-for-Agentic-Action" (backlog vision doc). The same acronym "CfA" means different things depending on which document you read.

**Severity**: Naming

---

### D10 — `human_proxy.py` referenced but file is `approval_gate.py`

**Spec says**: "DO NOT MODIFY scripts/human_proxy.py"; canonical file name is `scripts/human_proxy.py` — *docs/PROXY_WIRE_TASK.md, lines 12, 14, 31, 56*

**Code does**: The implementation file is `scripts/approval_gate.py` (39KB, fully implemented). `human_proxy.py` does not exist in `scripts/`. `docs/GLOSSARY.md` correctly names the file `approval_gate.py`. — *Glob of projects/POC/scripts/*.py — human_proxy.py absent; docs/GLOSSARY.md lines 29–34*

**Gap**: PROXY_WIRE_TASK.md was written against an old filename; any tooling, CI reference, or future doc that invokes `scripts/human_proxy.py` by name will fail to find the file.

**Severity**: Naming (stale doc reference; implementation is complete and functional under the correct filename)

---

## Backlog Items

### D11 — Context-aware proxy Phase 3 (LLM-assisted review) not implemented

**Spec says**: "Phase 3: LLM-assisted content review (optional, future)" — *backlog/context-aware-proxy.md, approximately line 78*

**Code does**: Phases 1 (structural content checking) and 2a/2b (differential pattern matching) are implemented in `approval_gate.py`. No LLM call exists in the proxy. — *scripts/approval_gate.py (full implementation)*

**Gap**: Phase 3 is explicitly described as "optional, future" in the backlog vision doc — this is a known-planned gap, not an unintended discrepancy.

**Severity**: [BACKLOG]

---

### D12 — Deletion targets still present

**Spec says**: `classify_review.py`, `generate_review_bridge.py`, `generate_dialog_response.py` should be deleted as "compensation for not letting the agent be the agent" once CfA becomes a Claude skill — *backlog/cfa-as-claude-skill.md, lines 102–106*

**Code does**: All three files exist and are fully implemented in `scripts/`. They are used actively by the shell orchestration layer. — *scripts/classify_review.py (12KB), scripts/generate_review_bridge.py (7KB), scripts/generate_dialog_response.py (6.1KB)*

**Gap**: The backlog vision proposes retiring these files as part of the CfA-as-skill refactor; they remain active until that migration occurs.

**Severity**: [BACKLOG]

---

### D13 — PROXY_WIRE_TASK.md describes a gap that no longer exists

**Spec says**: PROXY_WIRE_TASK.md describes `proxy_decide()` and `proxy_record()` wiring as an outstanding implementation task — *docs/PROXY_WIRE_TASK.md*

**Code does**: Both functions are fully wired in the current worktree. `proxy_decide()` (ui.sh line 412) accepts and passes an `--artifact` path argument. `proxy_record()` (ui.sh line 428) passes `--artifact-length` and full context. `intent.sh` correctly calls `proxy_decide "INTENT_ASSERT" "$intent_path"` at line 232. — *worktree ui.sh lines 412–445; worktree intent.sh line 232*

**Gap**: The implementation task is complete; PROXY_WIRE_TASK.md has not been updated to reflect completion. The doc describes a state of affairs that no longer exists.

**Severity**: [BACKLOG] (doc hygiene — task is done, mark it closed)

---

## Design Observations

*No severity rating — informational notes worth flagging.*

### O1 — Validated transitions exist but are secondary to bypass

The state machine provides both a validated `--transition` path and a bypass `--set-state` path. The validated path enforces actor/action/target rules. However, `--set-state` (bypass) is the dominant orchestration pattern. This is not necessarily wrong — shell orchestration has already performed the actor/phase checks externally — but it means the state machine's internal invariants are only as strong as the shell's discipline, not self-enforcing. Future integrations (e.g., CfA-as-Claude-skill) may need to rebuild transition validation inside the agent layer.

### O2 — cfa-state-machine.json is the sole source of truth; Python loads it dynamically

`cfa_state.py` loads state definitions and transition rules entirely from `cfa-state-machine.json` at runtime. There are no hardcoded state names or transition rules in the Python. This is a clean architecture — but it means any documentation claiming specific state names must be kept in sync with the JSON, not with the Python source.

### O3 — WORK_ASSERT is the only assert state where the human has no direct role

At INTENT_ASSERT, PLAN_ASSERT, and TASK_ASSERT, both `human` and `approval_gate` appear as actors across different transitions. At WORK_ASSERT, only `approval_gate` appears. Combined with the absence of WORK_ESCALATE, the final work review gate is the least human-accessible point in the entire CfA lifecycle — which may be intentional (proxy auto-approves or auto-rejects work) but is not documented as a deliberate design choice anywhere.
