---
name: fix-issue
description: Software-development-lead workflow — resolve a GitHub issue end-to-end via delegation. Mirrors the user-facing fix-issue phase shape (understand, risk, tests, fix, resolution, self-review, audit) but every phase is a Delegate to a subordinate workgroup-lead, never direct work.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__Delegate, mcp__teaparty-config__Send, mcp__teaparty-config__AskQuestion, mcp__teaparty-config__CloseConversation, mcp__teaparty-config__ListTeamMembers
user-invocable: false
argument-hint: <issue_number>
---

# fix-issue (software-development-lead)

You received a Delegate naming a GitHub issue. Drive it through the seven phases below. You are the orchestrator — you do not write code, write tests, or audit anything yourself. Each phase ends with `Delegate(<lead>, <task>, skill='attempt-task')` to the team member whose tools cover that phase, then `CloseConversation` on the reply to merge the deliverable into your worktree.

## Phase sequence

`phase-understand.md` → `phase-risk.md` → `phase-tests.md` → `phase-fix.md` → `phase-resolution.md` → `phase-self-review.md` → `phase-audit.md`

The audit phase is a guarded cycle: `PARTIAL` loops back to `phase-fix.md`, two rounds maximum, then escalate.

## Why these seven and not nine

User-facing fix-issue has nine phases — `worktree` and `close` bookend the seven you see here. Both are framework-mediated in this context:

- **Worktree** comes with the `Delegate` that launched you. There is no `git worktree add` to run.
- **Close** is owned by your originator's `CloseConversation` on your dispatch thread, which fires `commit_all_pending` on your worktree before squash-merging. There is no merge step for you to drive.

You compose deliverables and DELIVER; the lifecycle handles the bookends.

## Team

You delegate only to your team's workgroup-leads. Read the live roster with `mcp__teaparty-config__ListTeamMembers` once at the start; do not memorize names. Typical mapping (your phases will tell you which lead to call):

- **coding-lead** — reading the issue, planning the change, listing risks, implementing, regression-checking, self-reviewing.
- **quality-control-lead** — writing acceptance-aligned failing tests, verifying coverage and regression behavior.
- **quality-assurance-lead** — intent-fidelity audit against the issue and any referenced design docs.

Every dispatch is `Delegate(<lead>, <task>, skill='attempt-task')` — the skill prefix is what makes the recipient run their workflow rail rather than improvising.

## Start

Read `phase-understand.md` in this skill directory.
