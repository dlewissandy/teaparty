# Agent Message Broker

## Problem

Multi-agent execution in the POC was broken. The CLI's `-p` (pipe) mode exits after the starting agent produces output, so `SendMessage` calls to other agents were acknowledged but recipients never activated. The alternative — the `Task` tool — creates a star topology where the lead spawns ephemeral sub-agents, which hangs and prevents lateral communication between team members.

What we want is how real teams work: people send messages to each other, work concurrently, and check their inbox when they're ready.

## Core Idea

Replace the direct CLI invocation for multi-agent execution with a **message broker** that sits between agents.

Each agent has:
- An **inbox** — messages from other agents, in arrival order
- A **pending list** — messages it sent that haven't been responded to yet

The broker delivers messages. It does not prioritize, reorder, or filter. When an agent has messages waiting and isn't busy, the broker wakes it up and shows it everything: its inbox and its pending list. The agent decides what's important, what's blocked, and what to act on — the same way a person checks their messages and todo list.

## What Changes for Agents

**Before:** The lead ran once, dispatched to liaisons, and blocked until all of them returned. The lead was idle whenever any liaison was working. Liaisons couldn't talk to each other except through the lead.

**After:** The lead dispatches to liaisons and continues to receive results as they arrive — not in a batch, but one at a time as each finishes. When the lead is woken up, it sees which results are in, what's still outstanding, and can immediately react: update the plan, dispatch follow-up work, escalate, or just acknowledge and wait for more. New dispatches run alongside anything still in progress.

Liaisons can message each other directly. A lateral message between liaisons is delivered the same way as any other message — it goes in the recipient's inbox and they see it when they're next woken up.

## What the Agent Sees

When an agent is woken up, its input looks like:

```
From research-liaison:
Completed: produced research-summary.md with 3 source analyses.
Files: research-summary.md, source-comparison-matrix.md

---

From coding-liaison:
backtrack_planning: The API schema in the spec doesn't match the
actual endpoint responses. Need revised schema before proceeding.

[PENDING — 2 dispatches outstanding]
  - writing-liaison: "Write product descriptions" (8m ago)
  - editorial-liaison: "Review draft v2" (3m ago)
```

The agent reads this the same way a person reads their inbox. The research result is in. The coding team hit a problem. Writing and editorial are still working. The agent decides what to do.

## Point, Don't Copy

Messages between agents carry **references to artifacts, not the artifacts themselves**. If an agent wants feedback on a document, it names the file path — it doesn't paste the contents into the message. The recipient reads the file directly from the shared worktree.

This matters for two reasons:

1. **Context management.** Agent context windows are finite. A message that says "Review `deliverables/product-copy.md`, specifically the pricing section" costs a few tokens. Pasting the entire document into the message body burns context on content the recipient may only need to skim — or may need to re-read from disk anyway to see it in full fidelity.

2. **Directed attention.** When a sender says *which part* of a document matters — "the error handling in `src/api/auth.py` lines 40-80" or "the second paragraph of the executive summary" — the recipient can read selectively. This produces better feedback because the recipient focuses on what the sender actually cares about, rather than ingesting the whole file and guessing what's relevant.

The pattern is: **the message is a pointer with context, not a payload.** Say what you need, say where to look, say what to pay attention to. Let the recipient pull exactly what it needs.

## Concurrency Model

All agents that have work to do run concurrently. If the lead dispatches to three liaisons, all three start immediately and work in parallel. As each finishes, its response lands in the lead's inbox and the lead is woken up to process it — while the others are still running.

The lead can dispatch new work at any time. A new dispatch starts running alongside anything already in progress. The lead is never idle when there's something to react to.

## Termination

The system is done when three conditions are met:
1. All inboxes are empty — no unread messages
2. No agents are currently running
3. The lead has no pending dispatches — nothing outstanding

This is natural completion. Nobody has anything to say, nobody is working, and nobody is waiting for anything.

## What This Is Not

- Not a task queue or job scheduler. Agents are not workers pulling from a shared queue.
- Not a priority system. The broker doesn't decide what's urgent. The agent does.
- Not a workflow engine. There's no predefined sequence. Agents communicate and self-organize.
- Not a replacement for the CfA state machine. CfA still governs the outer plan-execute lifecycle. The broker operates within the execution phase, handling inter-agent communication that CfA's execution step previously couldn't support in `-p` mode.

## Relationship to Experimental Agent Teams

Claude Code has `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` which enables `SendMessage` and related tools. The broker intercepts these tool calls from the JSONL stream and delivers them, replacing the built-in routing that doesn't work in `-p` mode. From the agent's perspective, `SendMessage` works exactly as documented — the broker is invisible infrastructure.
