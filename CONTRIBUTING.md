# Contributing to TeaParty

TeaParty is a research platform for durable, scalable agent coordination. We are building toward a future where teams of humans and AI agents work together on increasingly difficult projects. The platform eats its own dogfood: the documentation, design artifacts, and implementation are produced by hierarchical agent teams running the TeaParty POC.

## How We Work

### Use TeaParty to Build TeaParty

Wherever possible, use the TeaParty orchestrator to implement new features. This is not a suggestion — it is the primary way the platform gets tested and improved. Every session produces learnings that feed back into the system. If a task can be expressed as a natural-language request to the orchestrator, it should be.

```bash
uv run python -m projects.POC.orchestrator "Your task description"
```

When the orchestrator cannot handle a task (tooling gaps, permission issues, tasks that require human judgment throughout), work directly — but note what the orchestrator could not do and why. Those observations are research data.

### Branching Strategy

We follow gitflow:

- **`main`** — latest stable release. Squash-merged from develop with a descriptive commit message. Never commit directly to main.
- **`develop`** — integration branch. Feature work merges here first. All tests must pass.
- **`fix/issue-<number>`** or **`feature/<name>`** — working branches. One branch per issue. Branch from develop, merge back to develop.

### Pull Requests and Human Approval

**No work merges to develop or main without a pull request and human approval.** This is not negotiable. Agent-produced code, documentation, and design changes all require human review before integration. The PR description should explain what changed and why.

### Worktrees

Each issue gets its own git worktree. This provides process-level isolation — concurrent work on different issues does not interfere.

```bash
git worktree add ../teaparty-fix-<number> -b fix/issue-<number> develop
```

Subteam dispatches within a session create child worktrees branched from the parent session's worktree. Completed work is squash-merged back up.

## Coding Standards

### Philosophy

- **Conceptual clarity always.** If you cannot explain what the code does in plain language, it is not ready.
- **Agents are agents** — autonomous, not scripted. No prescriptive prompts, no retry loops for tool use. Agent output is never truncated.
- **Workflows are advisory, not mandatory** — agents follow them by choice, not enforcement.
- **No over-engineering.** Only make changes that are directly requested or clearly necessary. Three similar lines of code is better than a premature abstraction.
- **No silent fallbacks.** Silent fallbacks are errors. They give the illusion code is working when it is not. If a component fails, the failure must be visible.
- **No historical artifacts.** No dead code, no stale docs, no historical comments. That is what git history is for. If something is no longer accurate or relevant, delete it.

### Python

- The active codebase is `projects/POC/orchestrator/`.
- All agent invocations go through `claude -p` (Claude Code CLI in pipe mode).
- Use best-in-class libraries over bespoke code. Never defend hand-rolled implementations just because they work.

### Tests

- **`unittest.TestCase`** with `_make_*()` factory helpers. Not pytest fixtures. No `conftest.py`.
- Tests live in `projects/POC/orchestrator/tests/`.
- Write failing tests first, then fix. Every bug fix commit should include a test that would have caught it.

```bash
uv run pytest projects/POC/orchestrator/tests/ --tb=short -q
```

### Documentation

Documentation follows an academic paper structure. The mkdocs site (`uv run mkdocs serve`) is the authoritative rendered form.

| Section | Purpose | Directory |
|---------|---------|-----------|
| Introduction | What TeaParty is, the problem, contributions | `docs/index.md`, `docs/overview.md` |
| Background | Narrative essays positioning our work | `docs/background/` |
| Conceptual Design | What and why — the four pillars | `docs/conceptual-design/` |
| Detailed Design | How — maps concepts to code | `docs/detailed-design/` |
| Evaluation | Experimental results and ablations | `docs/experimental-results/` |
| Discussion | Observed behaviors, UX | `docs/reference/` |
| Building Blocks | Vanilla technology references (ACT-R, Soar) | `docs/research/` |
| End-to-End Walkthrough | Case studies | `docs/e2e/` |
| Future Work | Proposals and research directions | `docs/proposals/`, `docs/reference/` |

**Background essays are narratives, not bullet-point lists.** They tell a story: here is the intellectual landscape, here is what exists, here is the gap we address. See `docs/background/` for the standard.

**Building Blocks are vanilla technology references.** They describe things we use but did not invent, with no TeaParty-specific content. Our adaptations go in Detailed Design.

**Proposals are intellectually honest.** If a design is not implemented, it lives in `docs/proposals/`, not in conceptual or detailed design. Conceptual design contains only designs with corresponding implementations.

### Commit Messages

Line 1: `Issue #<number>: <short description>` (or a descriptive summary if no issue).
Remaining lines: describe the work in detail — what changed and why.

## Tools and Skills

The `.claude/` directory contains skills and agent definitions that automate common workflows:

- `/audit` — multidimensional code review with parallel subagent reviewers
- `/refine` — dialectical refinement of design documents
- `/fix-issue <number>` — systematic issue investigation and resolution
- `/research <topic>` — deep academic and technical research

These skills use subagent isolation to prevent context window exhaustion. Each reviewer or role runs in its own context window, communicating through the filesystem.

## Getting Started

```bash
git clone https://github.com/dlewissandy/teaparty.git
cd teaparty
uv sync
uv run pytest projects/POC/orchestrator/tests/ --tb=short -q   # verify tests pass
uv run mkdocs serve                                              # browse docs at localhost:8000
```

Read `docs/index.md` for the research overview, then `docs/overview.md` for the system architecture. The background essays in `docs/background/` provide the intellectual context.
