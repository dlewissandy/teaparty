#!/bin/bash
cd /Users/darrell/git/teaparty
/Users/darrell/git/teaparty/projects/POC/dispatch.sh --team research --task "Design Evidence Inventory for organizational psychology research paper on AI-human team design. Produce document at projects/POC/.sessions/20260310-102912/research/design-evidence.md

Read the following source files and extract verbatim excerpts, constants, and structural patterns needed to support nine diagram/pseudocode blocks in the paper. Diagrams must be accurate to the actual implementation.

FILE 1: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/scripts/human_proxy.py
Extract: all constants (COLD_START_THRESHOLD, EXPLORE_RATE, STALENESS_DAYS, EMA_ALPHA, REGRET_WEIGHT, ARTIFACT_LENGTH_RATIO_LOW, ARTIFACT_LENGTH_RATIO_HIGH, EXPECTATION_MIN_DIFFERENTIALS), the should_escalate() five-rule logic, the compute_confidence() Laplace+EMA formula, the asymmetric regret weighting logic

FILE 2: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/scripts/generate_confidence_posture.py
Extract: the five dimension names and descriptions, the COLD_START_POSTURE block, the function signature

FILE 3: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/poc-workflow/workflow-detailed-design.md
Extract: the four-tier model table (Tier 0-3 with type, workflow, entry gate), the Reasonable User Test description, the four learning moments table (prospective/in-flight/corrective/retrospective with active/designed status)

FILE 4: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/poc-workflow/execution-alignment.md
Extract: the letter vs. spirit problem framing, the intent anchors concept, the drift detection patterns (scope creep, gold-plating, interpretation drift)

FILE 5: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/poc-workflow/living-intent.md
Extract: the four divergence types, the decision rule (magnitude times reversibility), the stated vs. revealed preferences distinction, the blog post example showing four intent revisions

FILE 6: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/poc-workflow/teaparty-intent-pipeline.md
Extract: the five-level memory hierarchy (dispatch through global), the four temporal moments with active/designed status, the feedback loop diagram text

FILE 7: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/agents/uber-team.json
Extract: the disallowedTools for project-lead and all liaison roles

FILE 8: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/agents/intent-team.json
Extract: the disallowedTools for intent-lead and research-liaison roles

FILE 9: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc/projects/POC/scripts/classify_task.py
Determine: does this implement binary or four-tier classification? Extract the tier logic.

For each source file, report: file read successfully (yes/no), and exact excerpts needed.

CRITICAL SECTION REQUIRED: Include a section confirming which of the four temporal learning moments (prospective/in-flight/corrective/retrospective) are currently ACTIVE vs. DESIGNED-BUT-NOT-YET-WIRED. This distinction is critical for accuracy in the paper.

Also confirm: does classify_task.py currently implement binary or four-tier classification?

Output file: projects/POC/.sessions/20260310-102912/research/design-evidence.md
Working directory: /Users/darrell/git/teaparty/projects/poc/.worktrees/session-0fe8c6f5--there-is-a-document-in-projects-poc-poc"
