# Task Tiers: Why Uniform Workflow Rigor Is a Form of Waste

## The Problem with Uniform Rigor

The instinct to apply consistent process to every task feels responsible. It is not. Uniform rigor is a category error: it confuses thoroughness with appropriateness. A workflow calibrated for complex multi-team projects will actively harm simple interactions, and a workflow optimized for speed will fail catastrophically when the task demands deliberate planning. The cost is not merely efficiency — it is trust, and trust compounds in both directions.

The first failure mode is over-engineering trivial requests. When a system initiates a full intent-capture session in response to "what is the current status?", it signals something damaging: the system does not understand the user. This is not a minor inefficiency. It is a trust erosion event. The user asked a simple retrieval question and received a protocol response. The mismatch between the weight of the response and the weight of the request communicates that the system treats every interaction identically — which means it is not reading context, not using memory, not adapting. Trust is asymmetric: one interaction like this can undo a long run of useful, well-calibrated responses. Users do not average their experience; they remember the moments of friction.

The second failure mode is the mirror image. Under-engineering complex projects creates a different kind of damage — expensive misalignment that only surfaces late. A task involving multi-file changes, evolving requirements, or cross-team coordination requires a planning pass precisely because the cost of divergence grows with execution time. Skipping that pass does not save time; it defers the cost and multiplies it. A misaligned implementation that runs for three hours before a verification gate catches the error is far more expensive than the twenty minutes of upfront intent capture that would have prevented it.

The third failure mode is subtler: entering the workflow at the wrong stage. Even a team that has chosen the right general tier can misplace the starting point. Jumping into execution when planning is incomplete produces work that must be discarded. Spending time on planning when the task is already fully understood wastes cycles on ceremony. The workflow is not just a question of how much rigor — it is a question of which instruments apply at which moments. Wrong tool for the job, even when the effort level is correct, still produces waste.

## A 4-Tier Model

The solution is explicit tier classification before any workflow machinery starts. Four tiers cover the practical range of task complexity encountered in the POC.

- **Tier 0: Conversational** — direct response, no workflow overhead. Status queries, clarification questions, "what does X mean?", "show me what has been done". Response happens inline. No session is created. No scripts are invoked. The system reads, retrieves, and replies.

- **Tier 1: Simple Task** — intent inferred from context plus memory, direct execution with output verification. Single-file edits, adding comments, fixing typos, running known scripts. The pattern is recognizable, the scope is bounded, the output is checkable. No formal planning pass is needed and inserting one would be pure friction.

- **Tier 2: Standard Task** — the current full pipeline: intent capture, plan, execute, verify. Multi-file changes, new features, tasks that contain some ambiguity about scope or approach. This is the default tier when signals are mixed and the cost of misalignment is non-trivial.

- **Tier 3: Complex Project** — iterative: intent may be revisited after partial execution, planning may occur multiple times, execution proceeds in phases with intermediate verification gates. Multi-team work, evolving requirements, projects where the full picture only becomes legible through partial execution. Tier 3 tasks are not just bigger Tier 2 tasks — they have a fundamentally different epistemological structure. You do not know what you need to know until you have started.

## Classification Signals

Five signals, in order of discriminating power, determine tier assignment.

1. **Reversibility (primary signal)**: Can this action be undone easily? Irreversible actions always push the tier upward. The escalation model in the POC already uses a 4-point reversibility scale crossed with a 4-point organizational impact scale as its primary cost signals. Tier classification should use the same inputs. A destructive database migration and a documentation edit are not the same category of task regardless of their apparent simplicity.

2. **Organizational impact**: How many teams, files, or interfaces does this touch? A change confined to one file with no external dependencies is a strong Tier 1 signal. A change that crosses team boundaries or modifies shared interfaces is at minimum Tier 2.

3. **Ambiguity markers**: The presence of words like "feel", "style", "better", "appropriate", or "improve" in a task description is a reliable signal of under-specified intent. These words indicate that the user has a preference they have not yet articulated. That gap needs to be surfaced before execution, which means Tier 2 at minimum.

4. **Novelty versus known pattern**: A task class that has been executed before can be tier-classified from memory. Warm-start pattern recognition is a meaningful efficiency gain — if the system has classified and successfully executed ten similar requests at Tier 1, the eleventh does not require re-evaluation from first principles.

5. **Cross-team scope**: Any task requiring coordination with multiple liaisons is Tier 2 at minimum and Tier 3 if the coordination itself is part of what needs to be planned. Single-liaison work can live at Tier 1 when the pattern is familiar.

## The Classification Decision Itself

Classification is a least-regret decision under asymmetric costs. The error function is not symmetric: misclassifying a Tier 3 project as Tier 1 is potentially catastrophic, producing expensive rework and wasted execution time. Over-classifying a Tier 0 query as Tier 2 is merely annoying — it adds friction, erodes trust incrementally, but produces no destroyed work. This asymmetry directly implies that the classifier should bias toward escalation in ambiguous cases. The same logic governs the escalation model's act-or-ask decisions: when uncertainty is high and costs are asymmetric, escalation is the rational default.

The decision matrix makes this concrete. Irreversible action combined with local impact maps to "escalate unless confidence exceeds 0.8". Irreversible action combined with external or cross-team impact maps to "always escalate". The tier classifier should apply this matrix as a floor: the reversibility and impact signals can only push the tier upward from the initial estimate, never downward.

Memory-backed warm-start reduces the cost of this conservatism. For recurring task classes, the system already has evidence about appropriate tier assignments. A task that has been correctly classified and executed ten times at Tier 1 has accumulated evidence that lowers the re-evaluation burden. The classifier does not need to treat every interaction as a novel case. This is how the conservative bias remains tractable — not by lowering the threshold, but by reducing the number of cases that require active classification at all.

## Implementation Sketch

The POC already has the right scaffolding. The concrete change is extending `classify_task.py` with a tier-assignment step that runs before session creation. The file already calls `claude-haiku` for project classification; the same call can return tier alongside project type. This keeps the overhead minimal — one additional field in an inference call that is already happening.

The tier assignment then determines which instruments activate. For Tier 0 and Tier 1, `plan-execute.sh` is bypassed entirely. The system reads context, applies memory, and produces output directly. For Tier 2, the full pipeline runs: `intent.sh` captures and confirms intent, a planning phase is inserted, execution follows, verification closes the loop. For Tier 3, intermediate relay checkpoints are scheduled — the orchestrator does not hand off a single long-running execution block but instead inserts synchronization points where plan state can be updated as understanding evolves.

Tier classification is stored in session metadata from the moment of assignment. This is not bookkeeping for its own sake — it is the input to a learning loop. Retrospective calibration compares assigned tier to actual execution complexity. Cases where a Tier 1 task required significant rework are evidence that the classifier under-estimated ambiguity or irreversibility. Over time, the classifier gets better not through manual tuning but through accumulated signal from its own decisions. The tier field in session metadata is where that signal lives.

The implementation does not require new infrastructure. It requires discipline about where tier classification sits in the flow — before session creation, not after — and commitment to using the tier to actually gate workflow stages rather than running the full pipeline by default and treating simplicity as an optimization rather than a design constraint.
