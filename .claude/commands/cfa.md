# Conversation for Action (CfA)

You are navigating the CfA protocol — a three-phase lifecycle for turning a human's idea into completed work. You hold the state machine. You decide when to transition, when to escalate, when to backtrack. The skill provides the protocol; you provide the judgment.

## Argument

The user provides a task description: `/cfa "build a REST API for the inventory system"`

## Three Phases

### Phase 1: Intent Alignment

**Goal**: Produce INTENT.md — a document capturing what the human actually wants.

1. Research the problem space. Read referenced files. Understand context.
2. Produce INTENT.md with these sections: Objective, Success Criteria, Decision Boundaries, Constraints, Open Questions.
3. Present INTENT.md for review (→ INTENT_ASSERT).

**Bring solutions, not questions.** Do the research. Present a complete intent document, not a list of clarifying questions. If you must escalate, write your best understanding first, then ask focused questions (max 3) in a separate escalation file.

### Phase 2: Planning

**Goal**: Produce a plan that implements the approved intent.

1. Given approved intent, explore the codebase and design an approach.
2. Use plan mode (EnterPlanMode) to propose your plan.
3. Present the plan for review (→ PLAN_ASSERT).

### Phase 3: Execution

**Goal**: Execute the approved plan and deliver completed work.

1. Implement the plan. Use tools as needed (Read, Write, Edit, Bash).
2. Break work into tasks. Complete each task, then synthesize.
3. Present completed work for review (→ WORK_ASSERT).

## State Machine

The full state machine is defined in `projects/POC/cfa-state-machine.json` — the single source of truth for all 29 states, valid transitions, actors, and backtrack markers. Read that file at the start of a CfA session to load the transition table.

You are always in one of these states. Track your current state and transition explicitly.

**Phases**: intent (IDEA → INTENT), planning (INTENT → PLAN), execution (PLAN → COMPLETED_WORK)

**Terminal states**: COMPLETED_WORK (success), WITHDRAWN (cancelled)

**Key transitions to know by heart:**
- ASSERT states (INTENT_ASSERT, PLAN_ASSERT, TASK_ASSERT, WORK_ASSERT) → review gates where the human or proxy approves/corrects
- Backtrack transitions (marked `"backtrack": true` in JSON) re-enter earlier phases at RESPONSE or QUESTION states
- WORK_ASSERT has the widest fan-out: approve, correct, revise-plan, refine-intent, withdraw

## Review Gates

At every ASSERT state (INTENT_ASSERT, PLAN_ASSERT, TASK_ASSERT, WORK_ASSERT):

1. **Check proxy confidence** by running:
   ```
   python3 projects/POC/scripts/approval_gate.py --decide \
     --state <STATE> --task-type <project-slug> \
     --model projects/POC/.proxy-confidence.json \
     [--artifact <path-to-artifact>]
   ```
2. If proxy says `auto-approve`: transition and continue.
3. If proxy says `escalate`: present the artifact to the human.
4. Classify the human's response:
   - **approve** → transition to approved state
   - **correct** → incorporate feedback, re-enter the phase at RESPONSE state
   - **dialog** → respond to the question, then re-invite review
   - **withdraw** → transition to WITHDRAWN
   - **backtrack** → re-enter the earlier phase (only at WORK_ASSERT or DRAFT)
5. **Record the outcome** for proxy learning:
   ```
   python3 projects/POC/scripts/approval_gate.py --record \
     --state <STATE> --task-type <project-slug> \
     --outcome <approve|correct|reject|withdraw|clarify> \
     --model projects/POC/.proxy-confidence.json \
     [--diff "summary of what changed"] \
     [--reason "why it needed to change"]
   ```

## Backtracking

Cross-phase backtracking is how the system corrects itself:

- **DRAFT → refine-intent**: During planning, you realize the intent is incomplete or wrong. Go back to INTENT_RESPONSE and rework.
- **WORK_ASSERT → revise-plan**: During final review, the human identifies a plan-level flaw. Go back to PLANNING_RESPONSE.
- **WORK_ASSERT → refine-intent**: During final review, the human identifies an intent-level misunderstanding. Go back to INTENT_RESPONSE.
- **FAILED_TASK → backtrack**: A task fails in a way that suggests the plan is wrong. Go back to PLANNING_QUESTION.

Backtracking always re-enters at RESPONSE or QUESTION states (the synthesis funnel), never at decision states. This ensures corrections go through the same synthesis process as fresh work.

## Intent Revision Authority

When you discover mid-flight that the intent needs revision, use this decision tree:

1. Is the change reversible? **NO** → escalate to human.
2. Does it affect more than 1 downstream task? **YES** → notify human and wait.
3. Does it affect confirmed deliverables? **YES** → notify human.
4. Does it cross team boundaries? **YES** → notify human.
5. Otherwise → proceed, note the change in your next checkpoint.

## Conventions

- **Every sentence must earn its place.** No filler, no boilerplate.
- **Escalation is least-regret, not least-effort.** When in doubt, escalate — the cost of rubber-stamping bad work is much higher than the cost of asking.
- **The agent earns autonomy through demonstrated alignment.** The proxy model tracks your approval rate. Consistent quality leads to auto-approval.
- **Track state explicitly.** At each transition, state where you are and why you're transitioning.

## State Persistence

Optionally persist your state for crash recovery:
```
python3 projects/POC/scripts/cfa_state.py --transition \
  --state-file .cfa-state.json --action <action>
```

Or initialize fresh:
```
python3 projects/POC/scripts/cfa_state.py --init \
  --output .cfa-state.json --task-id <id>
```
