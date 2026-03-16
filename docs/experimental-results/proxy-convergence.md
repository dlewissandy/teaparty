# Proxy Convergence

!!! warning "Experiment not yet run"
    This page describes the experiment design. The harness is built but results have not been collected.

*Pillar: Human Proxy*

## Hypothesis

The dual-signal confidence model (Laplace estimate + EMA) converges toward accurate prediction of human approval decisions. As the proxy observes more human decisions, its escalation rate decreases and its prediction accuracy increases — without increasing the false approval rate.

**H1:** Proxy prediction accuracy improves monotonically over the first 30 observations per (state, task-type) pair.

**H2:** Escalation rate decreases from ~100% (cold start) to a stable plateau below 40% within 20 observations.

**H3:** False approval rate remains below 5% throughout convergence, due to asymmetric regret weighting.

## Why This Matters

The human proxy is the mechanism that makes agent autonomy tractable. If it doesn't converge, the human remains a permanent bottleneck. If it converges too aggressively (false approvals), it produces unreviewed bad work. The dual-signal design with asymmetric regret is intended to thread this needle — but we need to verify it empirically, especially the convergence rate and the false-approval floor.

## Method

### Setup

A single human works with the same proxy across 50 sequential tasks, providing feedback at each approval gate. Tasks are drawn from a single domain to allow learning to accumulate (cross-domain convergence is a separate question).

### Conditions

| Condition | Description |
|-----------|-------------|
| **Dual-signal** (treatment) | Laplace + EMA, min of both, REGRET_WEIGHT=3 |
| **Laplace-only** (ablation) | Laplace estimate only, same REGRET_WEIGHT |
| **EMA-only** (ablation) | EMA only, same REGRET_WEIGHT |
| **No proxy** (control) | Always escalate to human |

### Measurements

| Metric | Description | Source |
|--------|-------------|--------|
| **Prediction accuracy** | Did proxy predict human's decision correctly? | Proxy log vs. human response |
| **Escalation rate** | Fraction of gates where proxy escalates to human | Proxy log |
| **False approval rate** | Proxy approved but human would have rejected | Proxy log + human post-hoc review |
| **False escalation rate** | Proxy escalated but human would have approved | Proxy log + human judgment |
| **Confidence score trajectory** | Raw confidence values over time per (state, task-type) | Proxy log |
| **Human time per task** | Wall-clock time human spends on approvals | Timestamps |
| **Exploration trigger rate** | Fraction of escalations caused by forced exploration (15%) vs. low confidence | Proxy log |

### Procedure

1. Run 50 tasks sequentially with the same human
2. At each approval gate, log the proxy's prediction and confidence score before showing to human
3. Human provides genuine approval/rejection (not simulated)
4. After all 50 tasks, human does post-hoc review of proxy-approved items to catch false approvals the proxy masked

### Analysis Plan

- Plot accuracy, escalation rate, and false approval rate as time series over 50 tasks
- Identify convergence point: first task after which escalation rate stays within 5% of its final value
- Compare convergence curves between dual-signal, Laplace-only, and EMA-only conditions
- Human time savings: compare human time per task in dual-signal vs. no-proxy condition

## Results

*Experiment not yet run.*

### Expected Findings

- **Cold start (tasks 1-5):** 100% escalation rate for all conditions, by design
- **Calibrating (tasks 5-20):** Rapid decrease in escalation rate. EMA-only may converge faster but oscillate more. Laplace-only converges slower but more smoothly. Dual-signal should track the more conservative (slower) of the two.
- **Warm start (tasks 20-50):** Escalation rate stabilizes. Dual-signal expected to plateau at 20-35% (15% floor from forced exploration + genuine uncertainty).
- **False approval rate:** Should remain below 5% for dual-signal across all phases. EMA-only may spike during rapid convergence.
- **Human time savings:** Expected 50-70% reduction in human time per task at warm start vs. cold start.

### Threats to Validity

- **Human consistency.** If the human's preferences drift over 50 tasks, the proxy is chasing a moving target. Mitigation: use a well-defined domain where preferences are relatively stable.
- **Task homogeneity.** 50 tasks in one domain may overstate convergence speed. Real usage spans multiple domains.
- **Simulated vs. genuine stakes.** Experimental approval decisions may not carry the same weight as production decisions. Mitigation: use real project tasks, not toy problems.
