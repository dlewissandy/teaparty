# Intent Team Improvements

## Problem

After 20+ sessions through the POC, the intent phase is producing documents
that look complete but consistently fail in ways that don't show up until
execution is underway. The alignment analyses tell the story:

The pythonify session assumed a greenfield conversion and didn't notice that
`projects/POC/orchestrator/` already had substantial Python modules from prior
work. The scrollable prompt session wrote an intent targeting the web frontend
but execution silently pivoted to the TUI — the intent even flagged the
ambiguity as an open question, but nobody resolved it before charging ahead.
The orphan recovery session had thorough open questions about resume-vs-abandon
per CfA state, but execution implicitly chose "abandon only" without ever
answering the questions or escalating the decision.

The pattern is: the intent-lead produces a plausible document, the proxy
approves it, and then planning or execution discovers that something important
was missing, ambiguous, or wrong. By then the work is in flight and the cost
of correction is high.

The governing quality principle we need is this:

> Someone who never spoke to the requester should be able to read this
> document and produce work the requester would recognize as their own
> idea, well executed.

We are not meeting that bar. The documents describe the problem space
competently but leave gaps that a human author wouldn't have left — because a
human author would have checked their own notes, searched for prior art,
and pinned down the scope before committing to paper.

## What Needs to Change

### Capabilities the intent-lead is missing

**Historical session retrieval.** The intent-lead has no way to ask "has
anything like this been attempted before?" The pythonify session would have
gone differently if the intent-lead had found the prior orchestrator work.
Continuation sessions (like 20260311-141241, which inherited an incomplete
7-wave plan) need to retrieve the prior session's INTENT.md, alignment
observations, and unresolved open questions — not just re-read the old file.

**Direct web research.** The intent-lead has WebSearch/WebFetch in its settings
overlay but the prompt routes all research through the research-liaison, which
dispatches via `dispatch.sh`. That's a subprocess chain for what's usually a
single lookup. Let the intent-lead do quick factual searches directly; reserve
the liaison for deep multi-query research.

**Intent delta for continuation sessions.** When a task explicitly references a
prior session, the intent phase should produce a delta: what was completed, what
remains, what open questions were never resolved, and what new information
changes the picture. The continuation session inherited a full INTENT.md and
PLAN.md but had no structured way to identify what had changed since.

**Graduated escalation.** Right now it's binary: write INTENT.md (assert) or
write `.intent-escalation.md` (max 3 questions). There's no way to say "here's
a solid draft, but I want to flag two things I'm not certain about." An
assert-with-flags mode — INTENT.md with inline `[CONFIRM: ...]` markers that
the approval gate surfaces to the human — would catch the "plausible but
uncertain" cases that currently sail through.

**Proxy flag awareness.** If the intent-lead flags something for confirmation,
the proxy must not auto-approve. Flags mean "a human needs to see this,"
full stop.

### Quality guidance the prompt is missing

**What, not how.** The scrollable prompt intent specified exact CSS values
(`max-height: calc(4 * 1.6 * 0.875rem)`) and source file line numbers. That's
planning-level detail. The intent should describe the outcome, not the
implementation path.

**Scope locking.** State which component and codebase directory this work
targets, explicitly enough that the execution team cannot accidentally pivot.
"This work targets `web/` (the vanilla JS SPA), NOT `projects/POC/tui/`."

**Every sentence pulls its weight.** If removing a sentence wouldn't change
the reader's ability to proceed, remove it.

**Point, don't paste.** Reference files by name; don't reproduce their content.

**Bring solutions, not questions.** Every open question must include researched
alternatives and a recommendation.

### Structural change: open questions must be tracked

Open questions in INTENT.md are currently advisory prose. Planning reads them
but isn't required to resolve them. Multiple sessions show open questions that
became dead letters — silently decided during execution or just worked around.

Open questions should be structured (numbered, tagged) so the planning phase
can explicitly mark each as "resolved by [decision]" or "deferred with
[reason]." If an open question reaches execution unresolved, that's a
trackable gap, not an invisible one.

## What This Is Not

This is not a redesign of the CfA state machine or the phase architecture.
The intent-lead's job stays the same: understand what the human wants and
write it down clearly. These improvements are about giving it better tools
to do that job and clearer standards for what "clearly" means.

This also overlaps with the intent-team-composition backlog item, which
proposes specialist agents (retrieval, voice calibration). The capabilities
listed here could be implemented as tools on the existing intent-lead, as
new teammates, or as skills — the mechanism matters less than the outcome.

## Relationship to Other Backlog Items

**intent-team-composition.md** — That item proposes structural changes to the
team (retrieval specialist, voice calibration). This item focuses on
capabilities and quality standards that are needed regardless of team
structure.

**context-aware-proxy.md** — The graduated escalation and proxy flag awareness
here interact directly with the proxy's decision logic. If the proxy becomes
content-aware (per that item), it should also respect intent-lead flags as
mandatory escalation signals.

**reference-based-information-passing.md** — Historical session retrieval and
intent deltas are both information-passing problems. The artifact_reader
patterns proposed there would serve the intent-lead's retrieval needs.
