# CfA Backtrack Effectiveness

*Pillar: Conversation for Action*

## Hypothesis

Cross-phase backtracks (e.g., Execution → Intent, Planning → Intent) reduce terminal rework — cases where the human rejects the final output and the entire task must be redone. Forward-only systems compound mid-stream errors because they have no mechanism to reconsider foundational assumptions.

**H1:** Tasks run with backtracks enabled produce higher final-acceptance rates than tasks run forward-only.

**H2:** The total cost (including backtrack overhead) is lower than the cost of terminal rework in the forward-only condition.

## Why This Matters

Most agent frameworks treat execution as a forward march: plan, execute, deliver. When the plan was built on a flawed understanding of intent, the result is wasted work. The CfA state machine's seven backtrack transitions are designed to catch these errors early — but backtracks are expensive (they discard partial work). The question is whether the cost of early correction is less than the cost of late discovery.

## Method

### Conditions

| Condition | Description |
|-----------|-------------|
| **Backtrack** (treatment) | Full CfA state machine with all 7 cross-phase backtrack transitions enabled |
| **Forward-only** (control) | CfA state machine with backtrack transitions disabled — phases can only move forward |

### Task Selection

20 tasks from the Medium and Complex tiers of the shared corpus. Tasks are selected to include ambiguous requirements (where intent misalignment is likely) and clear requirements (where backtracks should be unnecessary).

### Procedure

1. Each task is run twice — once per condition, with order counterbalanced
2. Same human evaluator for both conditions (blind to condition where possible)
3. The human provides the same initial request for both runs
4. Backtrack condition: orchestrator may trigger backtracks when agents detect misalignment
5. Forward-only condition: orchestrator proceeds through Intent → Planning → Execution without revisiting prior phases

### Measurements

| Metric | Description | Source |
|--------|-------------|--------|
| **Final acceptance rate** | Binary: human accepts output without requesting rework | Human judgment |
| **Rework count** | Number of times human requests changes after final delivery | Human judgment |
| **Quality score** | 1-5 composite across correctness, completeness, coherence, quality, alignment | Human judgment |
| **Backtrack count** | Number of cross-phase backtracks triggered | CfA state log |
| **Backtrack trigger distribution** | Which of the 7 backtrack types fired, and how often | CfA state log |
| **Total tokens** | Sum of all tokens consumed across all agents and phases | Token counter |
| **Total cost** | Dollar cost of LLM calls | Token counter |
| **Wall-clock time** | End-to-end duration | Timestamps |

### Analysis Plan

- Paired comparison on final acceptance rate (McNemar's test)
- Paired comparison on quality scores (Wilcoxon signed-rank)
- Cost comparison: total cost in backtrack condition vs. (initial cost + rework cost) in forward-only condition
- Subgroup analysis: ambiguous vs. clear tasks (backtracks should primarily help on ambiguous tasks)

## Results

*Experiment not yet run. This section will be populated with data tables, effect sizes, and statistical tests.*

### Expected Findings

Based on the design rationale, we expect:

- Higher acceptance rates for the backtrack condition, primarily on ambiguous tasks
- Modest token overhead for backtracks (10-30% more tokens per run), offset by elimination of full-task rework
- Backtrack triggers concentrated in Planning → Intent (plan reveals intent was wrong) and Execution → Planning (execution reveals plan was wrong)
- Clear tasks should show no significant difference between conditions (backtracks should not fire when requirements are unambiguous)

### Threats to Validity

- **Evaluator bias:** The human may unconsciously adjust expectations between conditions. Mitigation: blind evaluation where possible; inter-rater reliability with second evaluator on subset.
- **Task selection bias:** If tasks are too clear, backtracks never fire and the experiment is uninformative. If too ambiguous, the forward-only condition fails trivially. Mitigation: balanced selection with pre-screening.
- **Order effects:** Running the same task twice may prime the human. Mitigation: counterbalanced ordering, minimum 48-hour gap between runs of same task.
