# Cost-Quality Frontier

*Cross-cutting*

## Hypothesis

TeaParty's architectural choices (CfA protocol, hierarchical teams, human proxy, learning retrieval) have different cost-quality tradeoffs at different task complexity levels. There exists a configuration frontier — the set of architectural configurations that achieve the best quality for a given cost budget.

**H1:** The full TeaParty stack (all pillars enabled) dominates simpler configurations on Complex tasks but is dominated by simpler configurations on Simple tasks.

**H2:** Each pillar contributes positive marginal quality, but with diminishing returns — the first pillar enabled provides more lift than the fourth.

**H3:** Learning retrieval has the highest quality-per-dollar of any individual pillar, because it reuses prior work rather than generating new computation.

## Why This Matters

Multi-agent hierarchical systems are expensive. A hiring manager's first question is: "Is it worth the cost?" This experiment answers that question directly by mapping the cost-quality surface across configurations and task complexities. It also identifies which architectural components provide the most value per dollar — critical for prioritizing implementation work and for making practical deployment recommendations.

## Method

### Configurations

| Config | CfA | Hierarchy | Proxy | Learning | Description |
|--------|-----|-----------|-------|----------|-------------|
| **Baseline** | No | No | No | No | Single agent, single prompt, no protocol |
| **+CfA** | Yes | No | No | No | Three-phase protocol, flat team |
| **+Hierarchy** | Yes | Yes | No | No | Hierarchical teams, always escalate |
| **+Proxy** | Yes | Yes | Yes | No | Proxy-mediated approval |
| **Full** | Yes | Yes | Yes | Yes | All pillars enabled |
| **Learning only** | No | No | No | Yes | Baseline + learning retrieval |
| **Proxy only** | No | No | Yes | No | Baseline + proxy approval |

### Task Selection

45 tasks: 15 per tier (Simple, Medium, Complex). Each task has a reference solution and an estimated "ideal cost" (tokens required by an expert human giving direct instructions to a single agent).

### Measurements

| Metric | Description |
|--------|-------------|
| **Quality score** | 1-5 composite |
| **Total cost ($)** | Dollar cost of all LLM calls |
| **Total tokens** | Input + output across all agents |
| **Cost efficiency** | Quality / cost |
| **Overhead ratio** | Total cost / ideal cost (how much more expensive than minimal) |
| **Human time** | Minutes the human spends on approvals, feedback, rework |
| **Combined cost** | LLM cost + (human time * hourly rate) |

### Analysis Plan

- **Frontier construction:** For each task tier, plot quality vs. cost for all configurations. Identify the Pareto frontier — configurations where no other config achieves higher quality at equal or lower cost.
- **Marginal contribution:** For each pillar, compute the quality gain from adding it to the configuration that has everything except it. Rank pillars by marginal contribution per tier.
- **Scaling analysis:** Regress cost on task complexity for each configuration. Compare scaling exponents — does hierarchy bend the cost curve?
- **Break-even analysis:** At what task complexity does the full stack become cheaper than baseline + rework? (Include rework cost in the baseline.)
- **Human cost inclusion:** Re-compute frontiers with combined cost (LLM + human time). Does proxy shift the frontier by reducing human time?

## Results

*Experiment not yet run.*

### Expected Findings

- **Simple tasks:** Baseline is cheapest and sufficient. Each additional pillar adds cost without quality improvement. The overhead ratio for Full config is 5-10x.
- **Medium tasks:** CfA provides the largest quality lift. Hierarchy is marginally helpful. Proxy saves human time. Overhead ratio for Full config is 2-4x.
- **Complex tasks:** Full config dominates. Baseline requires extensive rework (2-3 iterations), making its effective cost higher than Full config despite lower per-run cost. Hierarchy provides the largest quality lift by enabling parallel execution and preventing context exhaustion.
- **Learning retrieval:** Highest quality-per-dollar across all tiers because retrieval cost is negligible compared to generation cost. Even on Simple tasks, relevant learnings prevent known mistakes.
- **Break-even:** Full stack breaks even with baseline around the Medium/Complex boundary when rework costs are included.

### Threats to Validity

- **Configuration interactions.** Pillars may interact non-additively (e.g., proxy is more valuable when learning is enabled). The factorial design partially addresses this but 7 configs * 45 tasks = 315 runs is already expensive.
- **Reference solution bias.** Quality is rated against reference solutions, which may reflect one valid approach. Alternative correct solutions may be scored lower.
- **Cost variability.** LLM costs depend on model, caching, prompt length. Results are specific to current pricing and model capabilities.
- **Human time estimation.** Human time per task varies by evaluator speed and domain familiarity. Mitigation: use consistent evaluators and report inter-evaluator variance.
