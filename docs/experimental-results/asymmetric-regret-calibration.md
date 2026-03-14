# Asymmetric Regret Calibration

*Pillar: Human Proxy*

## Hypothesis

The regret weight parameter (REGRET_WEIGHT) controls the tradeoff between false approvals (costly: bad work goes unreviewed) and false escalations (cheap: human reviews work that didn't need review). The current setting of 3 is hypothesized to be near-optimal for minimizing total weighted regret.

**H1:** Total regret is a convex function of REGRET_WEIGHT, with a minimum in the range [2, 5].

**H2:** REGRET_WEIGHT < 2 produces unacceptably high false approval rates (> 10%).

**H3:** REGRET_WEIGHT > 5 produces negligible autonomy gains over always-escalate.

## Why This Matters

REGRET_WEIGHT=3 was chosen from first principles (false approvals are roughly 3x more costly than false escalations). But "roughly 3x" is a guess. If the actual cost ratio is 1.5x, we're over-escalating and wasting human time. If it's 10x, we're under-escalating and producing unreviewed bad work. This experiment maps the sensitivity surface.

## Method

### Conditions

| REGRET_WEIGHT | Expected behavior |
|---------------|-------------------|
| 1 (symmetric) | No bias toward escalation. Highest false approval rate. |
| 2 | Mild bias. Moderate false approval rate. |
| **3 (current)** | **Design point. Expected near-optimal.** |
| 5 | Strong bias. Very few false approvals but many unnecessary escalations. |
| 10 | Extreme bias. Near-always-escalate behavior. |

### Task Selection

30 tasks from Medium tier (where proxy decisions are most consequential — Simple tasks rarely trigger proxy, Complex tasks usually require human review regardless).

### Procedure

1. For each REGRET_WEIGHT value, run 30 tasks with the same proxy (reset between conditions)
2. Proxy warms up over first 10 tasks, measurements taken on tasks 11-30
3. Human provides genuine feedback at each gate
4. Post-hoc review of proxy-approved items to identify false approvals

### Measurements

| Metric | Description |
|--------|-------------|
| **False approval rate** | Proxy approved, human would have rejected |
| **False escalation rate** | Proxy escalated, human would have approved |
| **Total regret** | `(false_approvals * REGRET_WEIGHT) + false_escalations` |
| **Escalation rate** | Overall fraction of gates escalated |
| **Human time** | Total time human spends on approvals |
| **Autonomy ratio** | Fraction of decisions proxy makes without escalation |
| **Outcome quality** | Final task quality score (does over-escalation improve quality?) |

### Analysis Plan

- Plot false approval rate, false escalation rate, and total regret as functions of REGRET_WEIGHT
- Identify the REGRET_WEIGHT that minimizes total regret
- Sensitivity analysis: how much does total regret change per unit change in REGRET_WEIGHT near the optimum?
- Practical tradeoff: plot autonomy ratio vs. false approval rate to find the "efficient frontier"

## Results

*Experiment not yet run.*

### Expected Findings

- **REGRET_WEIGHT=1:** ~15% false approval rate, ~10% false escalation rate, high total regret from false approvals
- **REGRET_WEIGHT=3:** ~3-5% false approval rate, ~25% false escalation rate, near-minimal total regret
- **REGRET_WEIGHT=10:** <1% false approval rate, ~60% false escalation rate, high total regret from excessive escalation
- **Optimal range:** REGRET_WEIGHT between 2 and 5, with a shallow minimum (the system is not highly sensitive to exact value in this range)
- **Quality:** Marginal quality improvement from REGRET_WEIGHT=3 to 10 — over-escalation doesn't improve outcomes much because the proxy is already catching the important cases

### Threats to Validity

- **Cost ratio is task-dependent.** In safety-critical domains, false approval cost is much higher. In low-stakes creative work, the ratio may be close to 1. This experiment tests a single domain — the optimal weight likely varies.
- **Warm-up confound.** With only 10 warm-up tasks per condition, the proxy may not have converged before measurement begins. Mitigation: analyze convergence curves per condition.
- **Human fatigue.** Running 5 conditions * 30 tasks = 150 tasks total. If run with one human, fatigue effects may contaminate later conditions. Mitigation: counterbalance condition order, spread across sessions.
