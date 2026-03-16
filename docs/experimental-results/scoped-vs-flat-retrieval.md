# Scoped vs. Flat Retrieval

!!! warning "Experiment not yet run"
    This page describes the experiment design. The harness is built but results have not been collected.

*Pillar: Learning System*

## Hypothesis

Team-scoped retrieval — where learnings are weighted by proximity to the requesting agent's scope in the organizational hierarchy — produces more relevant context than undifferentiated global retrieval.

**H1:** Scoped retrieval produces higher precision@5 (fraction of top-5 retrieved learnings rated relevant) than flat retrieval.

**H2:** Agents using scoped retrieval make fewer errors attributable to irrelevant or misleading context.

**H3:** The proximity weighting (team > project > global) correctly reflects the actual relevance distribution.

## Why This Matters

The learning system's scoped retrieval is the mechanism that bridges the scoping-blindness tradeoff. Without it, context isolation (the hierarchical team structure) prevents agents from accessing organizational knowledge that should inform their work. But naive "retrieve everything" doesn't work either — irrelevant learnings are noise. The scope multiplier is the architectural bet that spatial proximity in the org hierarchy correlates with relevance. This experiment tests that bet.

## Method

### Conditions

| Condition | Description |
|-----------|-------------|
| **Scoped** (treatment) | Retrieval with proximity weighting: `prominence = importance * recency_decay * (1 + reinforcement_count) * scope_multiplier` |
| **Flat** (control) | Same retrieval formula but `scope_multiplier = 1.0` for all learnings regardless of scope |
| **No retrieval** (baseline) | Agents receive no historical learnings |

### Learning Corpus

Pre-populated learning store with:
- 50 institutional learnings (org-wide conventions)
- 100 task learnings across 5 workgroups (20 per workgroup)
- 30 proxy learnings (human preferences)

Learnings are seeded from actual TeaParty POC sessions to ensure realistic content and quality distribution.

### Task Selection

20 tasks across 3 workgroups. Each task is chosen to have at least 3 relevant learnings in the corpus (verified by human pre-labeling) and at least 10 irrelevant learnings that a naive retriever might surface.

### Procedure

1. For each task, run retrieval under both scoped and flat conditions
2. Human judges rate each retrieved learning as: **relevant**, **marginally relevant**, or **irrelevant**
3. For the agent-performance comparison: run tasks end-to-end with scoped, flat, and no-retrieval conditions
4. Human rates output quality and identifies errors attributable to misleading context

### Measurements

| Metric | Description |
|--------|-------------|
| **Precision@5** | Fraction of top-5 retrieved learnings rated relevant |
| **Precision@10** | Fraction of top-10 rated relevant |
| **Recall@10** | Fraction of all relevant learnings appearing in top-10 |
| **Scope correlation** | Spearman correlation between scope proximity and human relevance rating |
| **Noise-induced errors** | Errors in agent output attributable to irrelevant retrieved context |
| **Task quality** | 1-5 composite quality score |
| **Context efficiency** | Relevant tokens / total retrieved tokens |

### Analysis Plan

- Precision/recall comparison between scoped and flat retrieval (paired by task)
- Correlation analysis: does scope proximity predict human-judged relevance?
- Error analysis: categorize agent errors as context-induced vs. independent
- Ablation: compare no-retrieval baseline to quantify the value of learning retrieval at all

## Results

*Experiment not yet run.*

### Expected Findings

- **Precision@5:** Scoped retrieval expected to achieve 0.7-0.8 vs. flat at 0.4-0.5. Team-level learnings are disproportionately relevant for team-level tasks.
- **Recall@10:** Comparable between conditions — relevant global learnings still surface under scoped retrieval, just ranked lower.
- **Scope correlation:** Moderate positive correlation (r = 0.3-0.5) between scope proximity and relevance. Not perfect — some global learnings are highly relevant to specific teams, and some team learnings generalize poorly.
- **No retrieval baseline:** Measurably worse quality on tasks where relevant learnings exist, establishing that retrieval adds value.
- **Noise-induced errors:** Flat retrieval expected to produce 2-3x more noise-induced errors than scoped.

### Threats to Validity

- **Corpus quality.** Seeded learnings may not represent natural learning accumulation. Real learnings may be noisier, more redundant, or differently distributed.
- **Scope structure.** The experiment assumes a specific org hierarchy. Different structures may change the optimal scope multipliers.
- **Cold start.** With only 180 total learnings, retrieval may not be challenging enough to differentiate conditions. Larger corpus needed for production-like evaluation.
- **Human labeling.** Relevance is subjective. Mitigation: inter-rater reliability on subset; clear labeling rubric.
