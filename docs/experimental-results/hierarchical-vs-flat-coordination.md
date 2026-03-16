# Hierarchical vs. Flat Coordination

!!! warning "Experiment not yet run"
    This page describes the experiment design. The harness is built but results have not been collected.

*Pillar: Hierarchical Teams*

## Hypothesis

Hierarchical dispatch with liaison-mediated context compression produces comparable or better task outcomes than flat single-team execution, while consuming fewer context tokens per agent as task complexity increases.

**H1:** At the Complex task tier, hierarchical coordination produces equal or higher quality scores than flat coordination.

**H2:** Hierarchical coordination's context-per-agent grows sublinearly with task complexity, while flat coordination's grows linearly.

**H3:** Hierarchical coordination enables parallelism that reduces wall-clock time on multi-domain tasks.

## Why This Matters

Flat teams are simpler: one context window, no liaison overhead, no information loss at boundaries. The hierarchical design incurs real costs — liaison agents, dispatch overhead, merge conflicts. The bet is that these costs are worth paying at scale, because flat teams hit context limits, lose coherence, and cannot parallelize. This experiment tests where the crossover point is.

## Method

### Conditions

| Condition | Description |
|-----------|-------------|
| **Hierarchical** (treatment) | Uber team + subteams via liaison dispatch. Each subteam runs in its own process with isolated context. |
| **Flat** (control) | Single team with all agents in one context window. No dispatch, no liaisons. |

### Task Selection

30 tasks: 10 Simple, 10 Medium, 10 Complex. All tasks have reference solutions for quality comparison.

### Procedure

1. Each task run once per condition (not paired — different tasks may favor different architectures)
2. Hierarchical condition uses the standard two-level dispatch (uber team + subteams)
3. Flat condition uses a single team with the same agents (minus liaisons) in one session
4. Same human evaluator rates both outputs (blind to condition)

### Measurements

| Metric | Description | Source |
|--------|-------------|--------|
| **Quality score** | 1-5 composite | Human judgment |
| **Context tokens per agent** | Peak context window usage for each agent | Token counter |
| **Total tokens** | Sum across all agents | Token counter |
| **Total cost** | Dollar cost | Token counter |
| **Wall-clock time** | End-to-end duration | Timestamps |
| **Coherence score** | Do outputs from different agents/subteams fit together? | Human judgment |
| **Merge conflicts** | Number of conflicts requiring resolution during result integration | Git log |
| **Agent count** | Total agents involved (hierarchical includes liaisons) | Config |

### Analysis Plan

- Quality comparison by tier (Mann-Whitney U per tier, since tasks differ between conditions)
- Context scaling analysis: regress context-per-agent on task complexity, compare slopes between conditions
- Cost-efficiency frontier: plot quality vs. cost for both conditions across tiers
- Parallelism benefit: wall-clock time comparison on Complex tasks where subteams can work concurrently

## Results

*Experiment not yet run.*

### Expected Findings

- **Simple tier:** Flat outperforms — hierarchical overhead (liaisons, dispatch) is not worth the cost for small tasks
- **Medium tier:** Comparable quality, hierarchical slightly more expensive but better coherence on multi-file tasks
- **Complex tier:** Hierarchical outperforms — flat teams hit context degradation, lose track of cross-cutting concerns, cannot parallelize effectively
- **Crossover point:** Somewhere in the Medium tier, hierarchical becomes cost-effective

### Threats to Validity

- **Confound: agent count.** Hierarchical condition has more agents (liaisons). Controlling for total agent compute is important.
- **Task assignment to tier.** Tier boundaries are subjective. Mitigation: pre-rate tasks by independent judges.
- **Flat team context limit.** On Complex tasks, the flat team may literally exhaust its context window. This is a real architectural limitation, not an experimental artifact — but it means the comparison becomes "works vs. doesn't work" rather than "works better vs. works worse."
