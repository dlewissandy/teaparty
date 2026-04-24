# CfA Orchestration

CfA Orchestration is TeaParty's state-machine engine for agentic Conversations for Action. It drives every session through three phases — Intent, Planning, Execution — with explicit approval gates between them and backtrack transitions that let the system revisit earlier decisions when new information demands it.

## Why it exists

Winograd and Flores's original Conversation for Action framework models work as a negotiation between two actors: A requests, B fulfills, and both share enough context to close the loop directly. That model breaks down for agentic work. A raw idea has to be refined into a specification before it can be planned; a specification has to be decomposed before it can be executed; and at every boundary someone has to decide whether the work still aligns with the human's actual intent.

Two failure modes motivate the design:

- **Intent gap.** When agents skip straight from prompt to execution, they optimize against a reading of the prompt that may not match what the human actually wanted. The misalignment only surfaces at the end, when the deliverable is wrong.
- **Backtrack failures.** When plans meet reality, execution routinely reveals flaws in the plan — or in the intent the plan was built on. Without a first-class way to return to an earlier phase, the system's only options are to ship wrong work or to start over.

Making the protocol a formal state machine — rather than a prompt convention — means these transitions are auditable. Every gate, every backtrack, every withdrawal is a logged, counted event visible in the system, not something implied by agent behavior.

## How it works

Each phase produces one artifact through a synthesis loop that refines it until it converges or is withdrawn:

- **Intent.** The intent lead transforms a raw idea into an approved `INTENT.md`. The proxy frames the final review as alignment validation: *Do you recognize this as your idea, completely and accurately articulated?*
- **Planning.** The project lead transforms approved intent into a strategic `PLAN.md` — a reusable workflow shape, not task-specific details. The proxy asks: *Do you recognize this as a strategic plan to operationalize your idea well?*
- **Execution.** The project lead dispatches tasks to workgroup agents (coding, research, writing, and others), each running in its own process and git worktree. Two nested loops govern the phase: an inner loop refines individual tasks, an outer loop assembles completed work. The proxy's final review compares deliverables against both intent and plan, so alignment failures are attributed to the correct phase. Execution produces `WORK_SUMMARY.md` as its convergence artifact.

### Phase artifacts

The phase configuration is `teaparty/cfa/phase-config.json`. Each phase declares the artifact it produces and the gate it advances through:

| Phase | Lead agent | Stream file | Artifact | Approval state |
|---|---|---|---|---|
| Intent | `intent-lead` | `.intent-stream.jsonl` | `INTENT.md` | `INTENT_ASSERT` |
| Planning | `project-lead` (using `uber.md`) | `.plan-stream.jsonl` | `PLAN.md` | `PLAN_ASSERT` |
| Execution | `project-lead` (using `uber.md`) | `.exec-stream.jsonl` | `WORK_SUMMARY.md` | `WORK_ASSERT` |

The artifacts are free-form Markdown — no enforced schema — but a usable `INTENT.md` reads as something the human would have written if they had time and discipline to make every implicit assumption explicit. The [case study INTENT.md](../../case-study/artifacts/INTENT.md) is a representative example: Objective, Structure, Voice & Tone, Success Criteria, Constraints, Open Questions. `PLAN.md` is similarly free-form but is expected to operationalize the intent — phasing, success conditions per phase, dispatch decomposition. `WORK_SUMMARY.md` reports outcomes against both prior artifacts. All three live at the worktree root and persist with the session; INTENT.md and PLAN.md are propagated into per-task worktrees by `session.py`.

Between phases, approval gates involve the human proxy — a learned model of the human's preferences that decides whether to approve on the human's behalf or escalate. Backtracks cross phase boundaries in either direction: planning can return to intent when the specification turns out to be flawed; execution can return to planning (or all the way to intent) when reality contradicts what was approved earlier. Each backtrack increments a counter on the state, so rework is measurable, not hidden.

Two orthogonal human controls sit on top of the state machine. **INTERVENE** delivers a course correction at the next turn boundary — advisory by default, authoritative from the decider. **WITHDRAW** is a kill signal that cascades immediately through the dispatch hierarchy and terminates the work.

The engine lives in `teaparty/cfa/`. The transition table is a Python dict (`TRANSITIONS`) at the top of `teaparty/cfa/statemachine/cfa_state.py` — literal constants, no JSON, no third-party state-machine library. `cfa_state.py` implements immutable transitions; `engine.py` drives the loop; `actors.py` is the runner that invokes the project lead through each phase's skill; and `gates/` implements the escalation and intervention machinery. The proxy confidence model lives in [`teaparty/proxy/approval_gate.py`](../human-proxy/approval-gate.md) — approval is a proxy-system responsibility that skills invoke via `AskQuestion`, not a CfA-internal concern.

## Status

Operational:

- Three-phase state machine with all documented states and transitions, defined as Python constants.
- Immutable `transition(state, action)` with append-only history and `.cfa-state.json` persistence per session.
- Cross-phase backtracks with counted transitions.
- Approval gates at INTENT_ASSERT, PLAN_ASSERT, and WORK_ASSERT, wired to the human proxy.
- Intervention (advisory/authoritative) and withdrawal (cascading) at turn boundaries.
- Child CfA instances for dispatched subteams, entering at the planning phase.

In progress / designed:

- Subteam observability in the dashboard. Now that the state machine has no task-level substates, the visible unit during execution is the message flow between the project-lead and its workgroups rather than a per-task state.
- Intent re-validation at narrower scope for deep subteams.
- Engagement orchestration (org-lead negotiation, decomposition of engagements into jobs, feedback bubble-up) — partial; single-level dispatch is operational, recursive spawn tracked separately in the `recursive-dispatch` proposal.

## Deeper topics

- [state-machine](state-machine.md) — full specification: states, transitions, backtracks, and the JSON transition table.
- [intent-engineering](intent-engineering.md) — how the intent phase negotiates a raw idea into an approved specification.
- [planning](planning.md) — strategic vs. tactical planning and how the planning synthesis loop works.
- [context-budget](context-budget.md) — how context is compressed across Send boundaries so dispatched agents don't inherit unbounded history.

Related systems:

- [human-proxy](../human-proxy/index.md) — the learned model of the human that participates in every phase and decides at every gate.
- Case study walkthrough of a real session through the three phases: [dialog](../../case-study/dialog.md), [execution](../../case-study/execution.md), [results](../../case-study/results.md).
