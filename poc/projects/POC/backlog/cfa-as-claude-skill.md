# CfA as a Claude Skill

## Problem

The CfA lifecycle is currently implemented as a shell orchestration layer:
`run.sh` → `intent.sh` → `plan-execute.sh` → `chrome.sh`, with Python helper
scripts (`classify_review.py`, `generate_review_bridge.py`,
`generate_dialog_response.py`, `human_proxy.py`, `cfa_state.py`) handling
classification, bridging, dialog, proxy confidence, and state transitions.

This works, but it's fundamentally a scripted pipeline driving agents from the
outside. The shell decides when to call Claude, what to pass, when to loop,
when to escalate, and when to stop. The agents inside those calls are ephemeral
— they appear for one turn, produce output, and vanish. They don't own the
conversation. They can't decide to ask a follow-up question, revisit an earlier
decision, or adapt their approach mid-flight. The orchestration layer makes
those decisions for them.

This inverts the "agents are agents" principle. The CfA state machine —
intent alignment, planning, execution, review gates, backtracking — should be
something the agent *understands and navigates*, not something imposed on it
from the outside by bash control flow.

## Vision

Repackage the CfA protocol as a Claude skill (slash command) that the agent
internalizes. Instead of shell scripts driving Claude through states, the agent
itself holds the state machine, decides when to transition, when to escalate,
when to backtrack, and when to consult the human proxy. The skill provides the
protocol knowledge; the agent provides the judgment.

A human types `/cfa "build a REST API for the inventory system"` and the agent
takes it from there — gathering intent, planning, executing, presenting
artifacts for review, handling dialog, backtracking when corrected — all as an
autonomous conversation, not a scripted pipeline.

## What Changes

### What moves into the skill

The skill encapsulates the *protocol* — the CfA state machine and the
conventions for how phases work:

- **State machine knowledge.** The 29-state transition table from
  `cfa_state.py` becomes part of the skill's context. The agent knows what
  states exist, what transitions are valid, what actor owns each transition,
  and when cross-phase backtracking is appropriate.

- **Phase protocol.** The three-phase structure (Intent → Planning →
  Execution) with its review gates (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT)
  and escalation paths (INTENT_ESCALATE, PLANNING_ESCALATE, TASK_ESCALATE).
  The agent knows that intent precedes planning, planning precedes execution,
  and that review gates require human judgment (or proxy confidence).

- **Review gate behavior.** At assertion states, the agent presents its
  artifact, invites review, classifies the response, and takes the appropriate
  action (approve, correct, dialog, withdraw, backtrack). This replaces the
  `cfa_review_loop` in `chrome.sh` and the `classify_review.py` /
  `generate_dialog_response.py` / `generate_review_bridge.py` helper scripts.

- **Human proxy integration.** The agent calls `human_proxy.py` (or its
  successor) to check confidence before escalating to the human. If the proxy
  is confident, the agent auto-approves. If not, it escalates. The proxy model
  and its EMA/regret/staleness mechanics remain external — the skill knows
  *when* to consult the proxy, not *how* the proxy works internally.

- **Backtracking conventions.** When the human says "go back to the intent" at
  PLAN_ASSERT, the agent knows this maps to refine-intent and re-enters
  INTENT_RESPONSE. The cross-phase backtracking paths are part of the protocol.

### What stays external

- **Human proxy model.** `human_proxy.py` with its confidence entries, EMA,
  asymmetric regret, staleness, and exploration logic. The skill calls it; it
  doesn't contain it. The proxy is a service, not protocol knowledge.

- **CfA state persistence.** `cfa_state.py` provides the transition table and
  persistence layer. The skill may use it for state tracking, or the agent may
  track state in-context. Either way, the validated transition logic stays as
  a Python module.

- **Memory system.** `memory_indexer.py`, `summarize_session.py`, and the
  learning promotion chain. These are post-session concerns, not mid-protocol
  decisions.

- **Team hierarchy.** `relay.sh` and the uber/subteam dispatch model. The
  skill governs one CfA conversation; hierarchical delegation is an outer
  concern.

- **Chrome presentation layer.** `chrome.sh` formatting (banners, bridges,
  heavy lines) is UI chrome, not protocol. The skill may emit structured
  markers that a presentation layer formats, but it doesn't own the rendering.

### What gets deleted

The shell orchestration in `intent.sh` and `plan-execute.sh` — the while
loops, case statements, review loops, state tracking via `cfa_set` /
`cfa_transition`, and the subprocess calls to classification and bridging
scripts. All of this is the agent doing its job, delegated to bash by
historical accident.

The Python helper scripts that exist solely to work around agent-in-a-box
limitations: `classify_review.py` (the agent can classify a review response
itself), `generate_review_bridge.py` (the agent can present its own artifact),
`generate_dialog_response.py` (the agent can have a conversation). These are
compensation for not letting the agent be the agent.

## How the Skill Works

### Skill definition

The skill is a markdown file (e.g., `.claude/commands/cfa.md`) that describes
the CfA protocol in enough detail for the agent to navigate it autonomously.
It includes:

1. **The state machine** — all 29 states, valid transitions per state, actor
   ownership, phase membership, and backtracking rules. Derived from
   `cfa_state.py` but expressed as protocol knowledge, not code.

2. **Phase protocols** — what the agent does in each phase:
   - *Intent:* Research the problem space. Bring solutions, not questions.
     Produce INTENT.md. Present for human review.
   - *Planning:* Given approved intent, produce a plan. Use plan mode.
     Present for human review.
   - *Execution:* Given approved plan, execute. Present deliverables for
     human review.

3. **Review gate protocol** — at each assertion state:
   - Check proxy confidence (call `human_proxy.py`).
   - If auto-approve: transition and continue.
   - If escalate: present the artifact, invite free-text review.
   - Classify the response: approve, correct, dialog, withdraw, backtrack.
   - For dialog: respond, then re-invite review.
   - For correct: incorporate feedback, re-enter the phase.
   - For backtrack: re-enter the earlier phase at the response state.

4. **Conventions** from the spec:
   - Bring solutions, not questions.
   - Every sentence must earn its place.
   - The agent earns autonomy through demonstrated alignment.
   - Escalation is least-regret, not least-effort.

### Invocation

```
/cfa "build a REST API for the inventory system"
```

The agent begins at IDEA, transitions to PROPOSAL, and autonomously navigates
the full CfA lifecycle. It uses tools (Read, Write, Bash, web search) as
needed during each phase. It calls `human_proxy.py` at review gates. It
presents artifacts and handles multi-turn dialog at assertion states. It
backtracks when corrected.

The conversation is one continuous session — no subprocess spawning, no
ephemeral agents, no state reassembly between shell calls. The agent holds
full context from intent through execution.

## Migration Path

### Phase 1: Skill prototype alongside shell scripts

Write the skill markdown. Test it with simple tasks. The shell pipeline
continues to run production work. Compare outcomes.

Key validation: does the agent reliably navigate review gates, respect proxy
confidence, and backtrack correctly without shell orchestration?

### Phase 2: Unified single-level CfA

Replace `intent.sh` and `plan-execute.sh` for single-team (non-hierarchical)
tasks. `run.sh` invokes the skill instead of the shell pipeline. The Python
helpers (`classify_review.py`, `generate_review_bridge.py`,
`generate_dialog_response.py`) are retired.

What remains: `human_proxy.py`, `cfa_state.py` (for persistence/audit),
`memory_indexer.py`, `summarize_session.py`, and the presentation layer.

### Phase 3: Hierarchical delegation

Extend to multi-team scenarios. The uber-level agent runs the CfA skill,
and delegates to subteam agents (which also run the CfA skill at
`depth + 1` with intent pre-approved). This replaces `relay.sh` dispatch.

This phase depends on Claude's team primitives (SendMessage, agent pools)
being able to support recursive CfA — each subteam agent needs its own
skill invocation with its own state.

## Risks and Open Questions

**Skill context budget.** The full 29-state transition table, phase protocols,
review gate behavior, and conventions may consume significant context. How
much of the protocol can the agent internalize from skill context vs. needing
tool access to query the state machine?

**State persistence.** In the shell model, `cfa_state.py` tracks state in a
JSON file and the shell reads it back between calls. In the skill model, the
agent holds state in-context. If the session crashes, state is lost. Should
the agent persist state to disk at each transition? Should it resume from
persisted state?

**Proxy integration boundary.** The agent needs to call `human_proxy.py` at
review gates. Currently this is a CLI call (`python3 human_proxy.py --state
PLAN_ASSERT --task-type my-project`). In the skill model, the agent would
make this call via Bash tool. Is that sufficient, or does the proxy need to
become a more integrated service?

**Multi-turn dialog at review gates.** In the shell model, dialog loops are
handled by `cfa_review_loop` calling `classify_review.py` and
`generate_dialog_response.py` in a loop. In the skill model, the agent *is*
the dialog participant. It reads the human's response, decides whether it's
an approval/correction/question, and responds naturally. This should be
strictly better — but it removes the structured classification. Does the loss
of `classify_review.py`'s deterministic parsing matter for proxy learning?

**Hierarchical recursion.** Can a skill invoke itself recursively for
subteams? Or does each depth level need a separate skill instance? This is
a Claude platform question more than a design question.

## Reference Documents

| Document | Path | Relevance |
|----------|------|-----------|
| CfA state machine | `scripts/cfa_state.py` | 29-state transition table, phase membership, backtracking detection, persistence |
| Intent engineering spec | `intent-engineering-spec.md` | Why intent alignment exists; least-regret escalation; success criteria; three governing principles |
| Intent engineering detailed design | `intent-engineering-detailed-design.md` | Conversation protocol, cold-start/warm-start behavior, turn structure, agent prompt specifications |
| Human proxy | `scripts/human_proxy.py` | Confidence model: Laplace smoothing, EMA with asymmetric regret, staleness guard, exploration floor |
| POC architecture | `POC.md` | Two-level hierarchy, relay.sh bridge, process model, git worktree isolation, stream-json parsing |
| Context-aware proxy (backlog) | `backlog/context-aware-proxy.md` | Future: proxy reads artifacts for content-informed decisions |
| Reference-based info passing (backlog) | `backlog/reference-based-information-passing.md` | Future: path-based references replace inline content |
| TeaParty workflows | `../../docs/workflows.md` | Skill context embedding pattern: workflows embedded in agent prompts as available skills |
| Agent dispatch | `../../docs/agent-dispatch.md` | Routing table, team sessions, lead agent designation |
| Hierarchical teams | `../../docs/hierarchical-teams.md` | Project/engagement team architecture, SendMessage delegation, context isolation |
| TeaParty architecture | `../../docs/ARCHITECTURE.md` | Corporate hierarchy, work hierarchy, conversation kinds |
| CfA spec (original) | `agentic-cfa-spec.docx` | Six-role recursive state machine, phase definitions, escalation learning |
