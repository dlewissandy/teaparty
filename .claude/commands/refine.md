# Dialectical Refinement

Iteratively refine a design document through structured critique, research, argument, and synthesis. Each round produces a better draft while preserving the original intent.

## Argument

The path to the document to refine: `/refine docs/detailed-design/act-r-proxy-memory.md`

Optional: `--rounds N` (default: 3)

## Setup

```
DOCUMENT = <argument>
SLUG = basename of document without extension
WORKDIR = refinement/${SLUG}
```

Create the working directory and anchor:

```bash
mkdir -p ${WORKDIR}/round-1
cp ${DOCUMENT} ${WORKDIR}/anchor.md
cp ${DOCUMENT} ${WORKDIR}/draft-0.md
```

## Round Loop

For each round N from 1 to max_rounds:

### Step 1: Critics (parallel)

Run all three critics in parallel. Each reads the anchor, the current draft, and prior round history.

- `/refine-critic-hm ${WORKDIR} ${N}` — Hiring manager concerns
- `/refine-critic-logic ${WORKDIR} ${N}` — Hegelian contradictions
- `/refine-factcheck ${WORKDIR} ${N}` — Claim verification

### Step 2: Responses (parallel)

Run researcher and proponent in parallel. Each reads the critic outputs.

- `/refine-researcher ${WORKDIR} ${N}` — Addresses factual concerns
- `/refine-proponent ${WORKDIR} ${N}` — Argues against logical and evaluative concerns

### Step 3: Synthesis

Run the synthesist. Reads everything, produces the new draft.

- `/refine-synthesist ${WORKDIR} ${N}` — Produces draft-N.md + changelog

### Step 4: Evaluation

Run both evaluators. Each reads the anchor, prior draft, and new draft.

- `/refine-drift ${WORKDIR} ${N}` — Does draft-N preserve the anchor's intent?
- `/refine-quality ${WORKDIR} ${N}` — Is draft-N better than draft-(N-1)?

### Step 5: Decision

Read both evaluator outputs.

- **Both pass** → print summary, advance to round N+1
- **Drift fails** → reject to synthesist with drift flags, re-run step 3 and 4 (max 2 retries)
- **Quality fails** → reject to synthesist with quality notes, re-run step 3 and 4 (max 2 retries)
- **Both fail** → reject with both, re-run step 3 and 4

### Convergence

Stop early if:
- The critics in round N produce no new concerns (only re-raises of previously addressed items)
- The evaluators both pass with no flags

### Completion

Copy the final accepted draft back to the original document path:

```bash
cp ${WORKDIR}/draft-${FINAL_N}.md ${DOCUMENT}
```

Print:
- Number of rounds completed
- Summary of concerns raised, addressed, rejected
- Drift assessment of final vs anchor
- Commit the result with a message referencing the refinement
