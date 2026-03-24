---
name: refine
description: Dialectical Refinement. Iteratively refine a design document through structured critique, research, argument, and synthesis using parallel subagents. Each round produces a better draft while preserving the original intent.
argument-hint: <path-to-root-document> [--rounds N]
user-invocable: true
---

# Dialectical Refinement

Iteratively refine a design document (and its linked sub-documents) through structured critique, research, argument, and synthesis. Each round produces a better draft while preserving the original intent.

Every role runs as an independent subagent with a fresh context window. Roles communicate exclusively through the filesystem — never through conversation history. This keeps the orchestrator lean and prevents context exhaustion across rounds.

## Arguments

- `$0` — path to the root document (required)
- `--rounds N` — maximum number of rounds (default: 3)

## Setup

```
ROOT = $0
SLUG = basename of ROOT without extension
WORKDIR = refinement/${SLUG}
```

### Clean Previous Run

If `${WORKDIR}` exists from a prior run, delete it entirely. Stale artifacts contaminate the new run.

```
rm -rf ${WORKDIR}
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

### Step 1: Critics (parallel subagents)

Launch all five critics as parallel subagents. Each gets a fresh context with only the role prompt and the file paths it needs.

Launch these five agents **in a single message** so they run concurrently:

1. **Visionary Critic** — Read the role prompt from `role-critic-vision.md`. Pass the agent:
   - The full text of `role-critic-vision.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

2. **Hegelian Critic** — Read the role prompt from `role-critic-logic.md`. Pass the agent:
   - The full text of `role-critic-logic.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

3. **Fact Checker** — Read the role prompt from `role-factcheck.md`. Pass the agent:
   - The full text of `role-factcheck.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

4. **AI Smell Critic** — Read the role prompt from `role-critic-ai.md`. Pass the agent:
   - The full text of `role-critic-ai.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

5. **Engineering Critic** — Read the role prompt from `role-critic-eng.md`. Pass the agent:
   - The full text of `role-critic-eng.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

Each agent uses `subagent_type: "general-purpose"`. Each writes its output to `${WORKDIR}/round-${N}/` as specified in its role prompt.

**Wait for all five to complete before proceeding.**

After they complete, verify all five output files exist:
- `round-${N}/critic-vision.md`
- `round-${N}/critic-logic.md`
- `round-${N}/factcheck.md`
- `round-${N}/critic-ai.md`
- `round-${N}/critic-eng.md`

### Step 2: Responses (parallel subagents)

Launch researcher and proponent as parallel subagents:

1. **Researcher** — Read the role prompt from `role-researcher.md`. Pass the agent:
   - The full text of `role-researcher.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

2. **Proponent** — Read the role prompt from `role-proponent.md`. Pass the agent:
   - The full text of `role-proponent.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

**Wait for both to complete before proceeding.**

Verify output files exist:
- `round-${N}/researcher.md`
- `round-${N}/proponent.md`

### Step 3: Synthesis (single subagent)

Launch the synthesist as a single subagent:

1. **Synthesist** — Read the role prompt from `role-synthesist.md`. Pass the agent:
   - The full text of `role-synthesist.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

**Wait for completion.**

Verify output:
- `draft-${N}/` directory exists with at least the root document
- `round-${N}/synthesis-changelog.md` exists

### Step 4: Evaluation (parallel subagents)

Launch both evaluators as parallel subagents:

1. **Drift Evaluator** — Read the role prompt from `role-drift.md`. Pass the agent:
   - The full text of `role-drift.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

2. **Quality Evaluator** — Read the role prompt from `role-quality.md`. Pass the agent:
   - The full text of `role-quality.md`
   - `WORKDIR = ${WORKDIR}`, `ROUND = ${N}`

**Wait for both to complete.**

Verify output files exist:
- `round-${N}/eval-drift.md`
- `round-${N}/eval-quality.md`

### Step 5: Decision

Read both evaluator outputs yourself (in the orchestrator context). Look for the `## Verdict:` line.

- **Both PASS** — print summary, advance to round N+1
- **Drift FAIL** — re-run Step 3 (synthesist) with a note about drift flags, then re-run Step 4. Max 2 retries per round.
- **Quality FAIL** — re-run Step 3 (synthesist) with a note about quality concerns, then re-run Step 4. Max 2 retries per round.
- **Both FAIL** — re-run Step 3 with both flags, then re-run Step 4. Max 2 retries per round.

### Convergence

Stop early if:
- Critics in round N produce no new concerns (only re-raises of previously addressed items)
- Both evaluators pass with no flags

## Completion

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

Commit the result with a message referencing the refinement. Push the current branch upstream.

## How to Launch a Subagent

Read the role prompt file from the skill directory, then launch an agent with the full role prompt text and the working parameters. Example pattern:

```
Agent(
    subagent_type="general-purpose",
    description="Visionary critic round 1",
    prompt="""
    <role prompt text read from role-critic-vision.md>

    ---
    WORKDIR = refinement/act-r-proxy-memory
    ROUND = 1
    """
)
```

The role prompt files are in the same directory as this SKILL.md file. Use Glob to find them:
```
.claude/skills/refine/role-*.md
```

Each role prompt contains everything the subagent needs: what to read, what to evaluate, and where to write output. The orchestrator's only job is to read these files, inject the WORKDIR and ROUND parameters, launch agents, wait for results, and make pass/fail decisions.

## Principles

- **Context isolation is the point.** Each role gets a fresh context window. The orchestrator never accumulates critic/researcher/synthesist output in its own context — it only reads the short verdict lines from evaluators.
- **The filesystem is the message bus.** All communication between roles happens through files in the WORKDIR. This is durable, inspectable, and context-free.
- **Parallel when independent, sequential when dependent.** Critics are independent of each other. Researcher and proponent are independent. But synthesis depends on all prior outputs, and evaluation depends on synthesis.
- **The orchestrator stays lean.** It manages lifecycle, not content. It reads role prompts, launches agents, checks for output files, reads verdicts, and decides what to do next.
