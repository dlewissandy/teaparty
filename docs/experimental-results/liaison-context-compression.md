# Liaison Context Compression

!!! warning "Experiment not yet run"
    This page describes the experiment design. The harness is built but results have not been collected.

*Pillar: Hierarchical Teams*

## Hypothesis

Liaison agents compress context at hierarchy boundaries — translating high-level tasks into scoped job descriptions (downward) and summarizing subteam output for the upper team (upward). This compression preserves decision-relevant information while discarding implementation details that would pollute the upper team's context.

**H1:** Liaison-mediated context reduces token volume by 60-80% at each hierarchy boundary.

**H2:** Decision-relevant information (as judged by the upper team's subsequent actions) is preserved at a rate > 90%.

**H3:** The upper team makes equivalent or better strategic decisions with liaison-compressed context vs. full context.

## Why This Matters

Context compression is the mechanism that makes hierarchy scalable. Without it, the uber team would need to ingest all raw output from all subteams — defeating the purpose of hierarchical isolation. But compression is lossy. If liaisons drop critical information, the uber team makes uninformed decisions. This experiment quantifies the information loss and tests whether it matters.

## Method

### Conditions

| Condition | Description |
|-----------|-------------|
| **Liaison-compressed** (treatment) | Upper team receives subteam output via liaison summaries |
| **Full context** (control) | Upper team receives raw subteam output (no liaison compression) |
| **Abstract only** (ablation) | Upper team receives only task completion status (success/fail), no content |

### Task Selection

10 Complex tasks requiring coordination across 2-3 subteams. Tasks are chosen so that the upper team must make at least one strategic decision based on subteam output (e.g., revise plan, reassign work, integrate conflicting results).

### Procedure

1. Subteams execute their assigned work (identical across conditions)
2. Subteam output is presented to the upper team in one of three forms (per condition)
3. Upper team makes strategic decisions based on the information received
4. Human evaluates: did the upper team have enough information to make a good decision?

### Measurements

| Metric | Description |
|--------|-------------|
| **Compression ratio** | Liaison output tokens / raw subteam output tokens |
| **Information preservation** | Fraction of human-tagged "decision-relevant facts" present in liaison summary |
| **Decision quality** | Human rating of upper team's strategic decisions (1-5) |
| **Upper team context size** | Peak context window usage for uber lead |
| **Decision time** | How long the upper team deliberates before acting |
| **Error attribution** | When upper team makes a bad decision, was it due to missing information? |

### Information Tagging Protocol

Before running the experiment, a human annotator reads each subteam's raw output and tags spans as:
- **Decision-critical** — upper team cannot make a correct decision without this
- **Decision-relevant** — informs the decision but not strictly necessary
- **Implementation detail** — irrelevant to upper team's strategic role

Information preservation is measured against the decision-critical and decision-relevant tags.

### Analysis Plan

- Compression ratio distribution across tasks
- Information preservation rate: decision-critical vs. decision-relevant (critical should be near 100%; relevant may be lower)
- Decision quality comparison across conditions (Friedman test for 3 conditions)
- Context efficiency: decision quality per context token consumed
- Qualitative analysis of information loss cases — what gets dropped and when does it matter?

## Results

*Experiment not yet run.*

### Expected Findings

- **Compression ratio:** 70-85% reduction. Subteam output contains extensive implementation detail (code diffs, tool invocations, internal deliberation) that liaisons correctly discard.
- **Information preservation:** > 95% for decision-critical facts, 70-85% for decision-relevant facts. Liaisons occasionally drop nuances that turn out to matter.
- **Decision quality:** Liaison-compressed and full-context conditions expected to be comparable. Full context may actually hurt — information overload degrades upper team reasoning on complex coordination tasks.
- **Abstract-only baseline:** Measurably worse decisions, establishing that liaisons add value beyond simple status reporting.

### Threats to Validity

- **Information tagging subjectivity.** What counts as "decision-critical" is partly determined by the decision the upper team makes, which varies by condition. Mitigation: tag before running experiments; use two independent taggers.
- **Liaison quality variance.** Different liaison agents may compress differently. The experiment tests the pattern, not any specific liaison's skill.
- **Full context overload.** If the full-context condition exceeds the upper team's context window, the comparison is unfair. Mitigation: truncate full context at the same window limit, noting when this happens.
