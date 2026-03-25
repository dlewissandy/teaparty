# Research Directions

These are active research and design questions across the TeaParty system. They are not gaps or deferrals -- they are where the interesting work is. Each question has a recommended direction noted where one exists; the recommendation is a starting point, not a decision.

Questions are grouped by theme rather than by source document. For the open questions section of any individual document, see [the pointer in that document](research-directions.md).

---

## Cross-Organization Collaboration

**Contract-based visibility implementation** *(Engagements)*: File-level ACLs? Separate namespaces with explicit sharing? Read-only projections? The `deliverables/` directory is clearly visible to both parties, but the `workspace/` directory needs a concrete visibility model.

**Partnership revocation during active engagement** *(Engagements)*: Grace period? Forced cancellation? Continue existing engagements but block new ones? The current model has no defined behavior for this transition.

**Engagement pricing and payments** *(Engagements)*: The current model has `agreed_price_credits` and `payment_status` fields. How do credits flow? Escrow? Per-milestone payments?

**Cycle prevention mechanics** *(Architecture)*: Graph traversal at engagement creation time? Depth limits? How is the engagement chain stored and propagated through nested engagements?

**Home agent discovery** *(Architecture)*: How does the home agent discover available org templates? Is there a system-level registry of organization types and starting configurations?

**Legacy model cleanup** *(Architecture)*: The codebase contains `CrossGroupTask`, `CrossGroupTaskMessage`, and `AgentTask` models that predate the current engagement and job architecture. These should be evaluated for removal or migration as the engagement model is revised in Phase 1.

---

## Sandbox and Code Execution

**Container orchestration** *(Sandbox)*: Docker directly, or use something like Docker Compose / Podman / Kubernetes? Starting with raw Docker API keeps it simple. Can layer orchestration later if needed.

**Claude Code invocation mode** *(Sandbox)*: `--print` mode for single-shot, or the Claude Code SDK (`@anthropic-ai/claude-code` npm package) for deeper integration? Start with `--print` for simplicity -- it returns structured JSON output and handles its own tool loop internally.

**Conflict resolution** *(Sandbox)*: When merging job to main, conflicts can arise. Options: (a) reject the merge and show conflicts in the UI, (b) let an agent resolve conflicts via `sandbox_exec`, (c) create a conflict-resolution job. Start with (a), add (b) later.

**File browser source of truth** *(Sandbox)*: For teams with repos, should the file browser read from `workgroup.files` (cached, potentially stale) or from the filesystem (live, requires API call)? Recommendation: read from filesystem for the active job's worktree, from `workgroup.files` for the main branch overview.

**Cost attribution** *(Sandbox)*: Claude Code CLI usage inside sandboxes consumes API tokens. How to attribute this to specific users/agents for budget tracking? The container's API key usage can be tracked via Anthropic's API usage endpoints, or by parsing Claude Code's `--output-format json` output which includes token counts.

**Warm pool sizing** *(Sandbox)*: How many warm containers to maintain? Default to 0 for development (containers created on demand), configurable for production.

---

## Learning System and Memory

**Embedding model choice** *(Learning)*: memsearch uses a local embedding model. The quality of fuzzy retrieval depends on embedding quality. Trade-off: better embeddings cost more; local embeddings are fast but less capable.

**Scope multiplier calibration** *(Learning)*: Team-level chunks should score higher than global chunks at equal similarity, but by how much? This needs empirical tuning across real task histories.

**Cross-type retrieval** *(Learning)*: Should an institutional learning ever inform task-based retrieval, or vice versa? The current design keeps them strictly separate. There may be cases where institutional norms are relevant to task execution that fuzzy retrieval within the task store would miss.

**Proxy model validation** *(Learning)*: How do you know the proxy model is accurate? Escalation calibration provides one signal (act/ask outcomes), but there is no direct "would the human have made this decision?" validation for low-risk decisions the proxy handles autonomously.

**Cold start rate** *(Learning)*: A new project/team/human has no learnings. The system defaults to escalation (conservative) per the intent engineering spec. But how quickly can the stores accumulate enough signal to be useful? The four learning moments (especially corrective) help, but the rate of useful learning per session is an empirical question.

---

## Intent Engineering and Escalation

**Learning from downstream outcomes** *(Intent)*: The system must learn whether completed work actually satisfied the intent, without requiring the human to fill out a survey. Three approaches worth evaluating: instrument output delivery points (file acceptance, edits, rejections, rollbacks); compare intent.md success criteria against observable outcomes; use lightweight periodic check-ins at natural breakpoints. Recommendation: start with delivery-point instrumentation -- it requires no human effort and produces signal immediately.

**Divergence between stated and revealed preferences** *(Intent)*: The human may say they want X but consistently correct toward Y. Recommendation: surface the contradiction explicitly during the next intent gathering session rather than auto-correcting silently. Silent auto-correction risks masking a real change in organizational direction.

**Minimum viable memory architecture for warm-start** *(Intent)*: Three scoping options: start with the escalation model only; start with per-user key-value observations stored in markdown alongside the escalation model; start with full hybrid search from day one. Recommendation: the second option -- the escalation model alone is too narrow to demonstrate warm-start value, but full hybrid search is premature before the observation corpus is large enough to need it.

**Domain segmentation for escalation** *(Intent)*: The escalation model must be domain-indexed -- a human may grant broad autonomy for coding but narrow autonomy for communications. Recommendation: start with project-level categorization as the domain index (immediately available, no upfront taxonomy) and evolve toward emergent clustering as data accumulates.
