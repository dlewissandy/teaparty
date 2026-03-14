# Experimental Results

This section presents empirical evaluations of TeaParty's four research pillars. Each experiment isolates a specific architectural claim, describes the methodology for testing it, and reports results.

## Motivation

The conceptual design makes strong structural claims: that cross-phase backtracks reduce terminal rework, that hierarchical teams outperform flat ones at scale, that asymmetric regret weighting calibrates autonomy better than symmetric approaches, and that scoped retrieval beats flat retrieval for agent coordination. These claims need evidence.

The experiments below are designed to be:

- **Ablative** — each experiment isolates one architectural choice and compares the system with and without it
- **Reproducible** — tasks, prompts, and evaluation criteria are specified precisely enough to rerun
- **Cost-aware** — token usage and dollar cost are first-class metrics alongside quality

## Experimental Infrastructure

All experiments use the TeaParty POC orchestrator with instrumented logging. Key instrumentation points:

- **Token counters** per agent, per hierarchy level, per CfA phase
- **State transition logs** from the CfA state machine (timestamps, transition type, trigger)
- **Proxy decision logs** from the approval gate (confidence scores, decision, human response)
- **Learning retrieval logs** (query, results, relevance judgments)
- **Task outcome ratings** (human-judged quality on 1-5 Likert scale, plus binary accept/rework)

### Task Corpus

Experiments draw from a shared corpus of tasks spanning three complexity tiers:

| Tier | Description | Example | Expected agents |
|------|-------------|---------|-----------------|
| **Simple** | Single-file, single-domain | Fix a bug in one module | 1-2 |
| **Medium** | Multi-file, single-domain | Add a feature with tests | 3-5 |
| **Complex** | Multi-file, cross-domain | Design and implement a new subsystem | 5-10+ |

Each tier contains 15-20 tasks with known-good reference solutions for quality comparison.

### Evaluation Methodology

**Quality scoring.** Each output is rated by a human evaluator on five dimensions:
1. **Correctness** — does it do what was asked?
2. **Completeness** — are all requirements addressed?
3. **Coherence** — do the parts fit together?
4. **Code quality** — is the implementation clean and idiomatic?
5. **Alignment** — does it reflect the spirit of the request, not just the letter?

**Statistical approach.** Paired comparisons (treatment vs. control on same task) with Wilcoxon signed-rank tests for ordinal quality scores. Bootstrap confidence intervals for cost and token metrics. Effect sizes reported as Cohen's d or rank-biserial correlation.

---

## Experiments

### Pillar 1: Conversation for Action

- [CfA Backtrack Effectiveness](cfa-backtrack-effectiveness.md) — Do cross-phase backtracks reduce terminal rework compared to forward-only execution?

### Pillar 2: Hierarchical Teams

- [Hierarchical vs. Flat Coordination](hierarchical-vs-flat-coordination.md) — Does hierarchical dispatch with liaison-mediated context compression outperform flat single-team execution?
- [Liaison Context Compression](liaison-context-compression.md) — How much information is preserved vs. lost at each hierarchy boundary?

### Pillar 3: Human Proxy

- [Proxy Convergence](proxy-convergence.md) — Does the dual-signal confidence model converge toward accurate human preference prediction?
- [Asymmetric Regret Calibration](asymmetric-regret-calibration.md) — Is REGRET_WEIGHT=3 near-optimal, and how sensitive are outcomes to this parameter?

### Pillar 4: Learning System

- [Scoped vs. Flat Retrieval](scoped-vs-flat-retrieval.md) — Does team-scoped retrieval produce more relevant context than undifferentiated global retrieval?

### Cross-Cutting

- [Cost-Quality Frontier](cost-quality-frontier.md) — How do cost and quality scale with task complexity across architectural configurations?
