# Dialectical Refinement

Iteratively refine a design document (and its linked sub-documents) through structured critique, research, argument, and synthesis. Each round produces a better draft while preserving the original intent.

## Argument

The path to the root document: `/refine docs/detailed-design/act-r-proxy-memory.md`

Optional: `--rounds N` (default: 3)

## Setup

```
ROOT = <argument>
SLUG = basename of root document without extension
WORKDIR = refinement/${SLUG}
```

### Discover the Document Set

Starting from ROOT, follow all relative markdown links (`[text](path.md)`) to find the full set of documents. Only follow links to `.md` files within the same directory or subdirectories. This produces a document set — the root plus all linked sub-documents.

### Create the Anchor and Draft-0

```
mkdir -p ${WORKDIR}/anchor
mkdir -p ${WORKDIR}/draft-0
mkdir -p ${WORKDIR}/round-1

for each file in the document set:
    preserve relative path from ROOT's directory
    copy to ${WORKDIR}/anchor/<relative-path>
    copy to ${WORKDIR}/draft-0/<relative-path>
```

The anchor directory is never modified. It is the source of truth for intent.

Example for `act-r-proxy-memory.md`:
```
refinement/act-r-proxy-memory/
  anchor/
    act-r-proxy-memory.md
    act-r.md
    act-r-proxy-mapping.md
    act-r-proxy-sensorium.md
  draft-0/
    (same four files)
```

## Round Loop

For each round N from 1 to max_rounds:

### Step 1: Critics (parallel)

Run all five critics in parallel. Each reads the anchor directory, the current draft directory, and prior round history.

- `/refine-critic-vision ${WORKDIR} ${N}` — Vision, feasibility, and strategic concerns
- `/refine-critic-logic ${WORKDIR} ${N}` — Hegelian contradictions
- `/refine-factcheck ${WORKDIR} ${N}` — Claim verification
- `/refine-critic-ai ${WORKDIR} ${N}` — AI writing smell detection
- `/refine-critic-eng ${WORKDIR} ${N}` — Engineering actionability and implementability

Critics should read ALL files in the document set, noting which file each concern references.

### Step 2: Responses (parallel)

Run researcher and proponent in parallel. Each reads the critic outputs.

- `/refine-researcher ${WORKDIR} ${N}` — Addresses factual concerns
- `/refine-proponent ${WORKDIR} ${N}` — Argues against logical and evaluative concerns

### Step 3: Synthesis

Run the synthesist. Reads everything, produces the new draft directory.

- `/refine-synthesist ${WORKDIR} ${N}` — Produces draft-N/ directory + changelog

The synthesist may revise any file in the document set. Files that don't need changes are copied unchanged from draft-(N-1). Cross-references between files must remain valid.

### Step 4: Evaluation

Run both evaluators. Each reads the anchor directory, prior draft directory, and new draft directory.

- `/refine-drift ${WORKDIR} ${N}` — Does draft-N preserve the anchor's intent?
- `/refine-quality ${WORKDIR} ${N}` — Is draft-N better than draft-(N-1)?

Evaluators should compare corresponding files across directories, not just the root document.

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

Copy the final accepted draft directory back to the original locations:

```
for each file in draft-${FINAL_N}/:
    copy back to its original path (relative to ROOT's directory)
```

Print:
- Number of rounds completed
- Summary of concerns raised, addressed, rejected
- Drift assessment of final vs anchor
- List of files modified

Commit the result with a message referencing the refinement.
