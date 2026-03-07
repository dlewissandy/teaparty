# Intent Team Composition and Cross-Phase Specialist Agents

## Problem

The intent-lead agent does everything itself: reads referenced files, interprets
the human's request, understands implicit assumptions, structures the document,
and writes INTENT.md in the human's voice. The only teammate is a
research-liaison that relays to an external subteam.

This solo-performer pattern has three consequences:

1. **Retrieval is shallow.** The intent-lead reads files listed in the task
   description. It does not search for related files, cross-reference code
   patterns, check project memory, or discover context the human assumed was
   obvious. A human writing an intent document would grep the codebase, re-read
   their own notes, and check what changed recently. The intent-lead cannot do
   this well because it is also busy structuring a document and managing
   escalation logic.

2. **Voice is generic.** INTENT.md is supposed to read "as if the human wrote
   it themselves." But the intent-lead has no model of the human's writing
   style, vocabulary choices, or level of technical precision. It produces
   competent prose that sounds like an AI summary, not like the human. The
   same problem recurs downstream: plans, work summaries, and escalation
   notes all lack the human's voice.

3. **Specialist work is not reusable across phases.** A retrieval agent that
   learns which files matter during intent could serve the planning agent when
   it needs the same context. A voice-matching agent that calibrates during
   intent could shape plan language and work output. But today, each phase
   starts fresh with a new team that has no specialist continuity.

## Principle

**The intent team should have specialists whose expertise persists across
phases.** These agents are not intent-specific — they are session-level
resources that first appear during intent (where the human's needs are
established) and remain available through planning and execution.

The intent-lead remains the coordinator. It delegates retrieval and voice
work to teammates, the same way the project-lead delegates to liaisons.
The difference: these specialists are not relays to external subteams.
They are direct participants with their own tools and judgment.

## Proposed Specialist Roles

### Retrieval Specialist

Responsible for finding and chunking relevant context from the codebase,
project memory, session history, and referenced documents.

**Why a separate agent:** Retrieval is search-heavy and iterative. The
retrieval agent can run multiple Glob/Grep/Read passes, cross-reference
hits, and assemble a focused context package — while the intent-lead
focuses on interpretation. Separating retrieval from interpretation means
neither task is truncated to make room for the other in a single context
window.

**Capabilities:**
- Deep codebase search (Glob, Grep, Read) — not just files named in the
  task, but related modules, tests, recent changes, and configuration
- Project memory retrieval — past intent documents, correction history,
  recurring patterns the human cares about
- Session context assembly — earlier phases' artifacts, dialog history,
  backtrack reasons from previous iterations
- Chunked delivery — returns relevant excerpts with file references,
  not entire files. The consumer (intent-lead, planning agent) gets
  a curated context package, not a document dump

**Cross-phase value:** The same retrieval specialist serves the planning
agent (finding implementation-relevant code) and the execution agent
(locating files to modify). Context discovered during intent does not
need to be re-discovered during planning.

### Voice Calibration Specialist

Responsible for ensuring that artifacts read as if the human wrote them.

**Why a separate agent:** Voice matching requires studying the human's
existing writing — past INTENT.md documents, corrections, chat messages,
project documentation they authored. This is a distinct skill from
understanding what the human wants. The intent-lead understands the
*substance*; the voice specialist ensures the *expression* matches.

**Capabilities:**
- Analyze the human's writing samples (prior intents, corrections,
  project docs) to identify characteristic patterns: sentence length,
  vocabulary level, use of hedging vs. assertion, technical depth,
  formatting preferences
- Review and adjust draft artifacts before they are finalized —
  the intent-lead writes a draft, the voice specialist reshapes it
- Maintain a running style profile that improves across sessions as
  more writing samples accumulate

**Cross-phase value:** Plans, work summaries, escalation notes, and
review bridges all benefit from matching the human's voice. The voice
specialist calibrates once during intent and serves all downstream
phases.

### Other Potential Specialists

These are less clearly scoped but worth noting as the team grows:

**Quality Reviewer.** Reviews artifacts against the intent's own success
criteria and decision boundaries. Catches internal contradictions, vague
commitments that will cause downstream ambiguity, and criteria that are
not actually testable. Different from the editorial team (which checks
prose quality) — this agent checks *intellectual quality* of the artifact
as a specification.

**Compliance/INFOSEC Reviewer.** Scans intent, plans, and work output
for security implications, data handling concerns, and organizational
policy compliance. Flags when an intent implies storing credentials in
plaintext, when a plan proposes opening network ports, or when work
output includes hardcoded secrets. This agent reads organizational
policy documents (if available) and applies them as constraints that
the other agents may not be aware of.

## Cross-Phase Conservation

Today, each phase spawns a fresh team. The intent team is torn down
before the planning team starts. There is no mechanism for an agent
from the intent phase to participate in planning or execution.

Conservation means: certain agents are instantiated during intent and
remain available (as session-level resources) to subsequent phases.
They do not lead those phases — they serve whoever leads.

### Design Questions

1. **Mechanism.** How does a specialist survive across phases? Options:
   - The specialist runs as a long-lived process that planning and
     execution agents contact via SendMessage (requires the specialist
     to outlive the intent phase)
   - The specialist writes a structured context artifact (style profile,
     retrieval index) that downstream phases consume as a file (simpler,
     but loses the agent's judgment — it becomes a static document)
   - The specialist is re-instantiated in each phase but with its prior
     context loaded from a session artifact (hybrid — agent is fresh
     but has accumulated knowledge)

2. **Addressing.** How does the planning agent know to message a
   retrieval specialist? Currently, teammates are discovered by reading
   the team config. Cross-phase specialists would need to be either:
   - Registered in a session-level config that all phases read
   - Injected into each phase's team config as additional members
   - Accessed through a session-level tool (e.g., `retrieve_context`)
     that hides the agent behind an interface

3. **Cost.** More agents means more model calls. The retrieval specialist
   should use a cheap model (haiku) for search orchestration. The voice
   specialist may need a stronger model (sonnet) for style analysis.
   Cost control comes from scoping: specialists do narrow work, not
   open-ended exploration.

## Current State

### intent-team.json (2 agents)

```
intent-lead     sonnet   Reads files, interprets task, writes INTENT.md
research-liaison haiku   Relays to research subteam via relay.sh
```

The intent-lead's prompt explicitly says "READ THEM FIRST using Read,
Glob, or Grep before writing anything" — retrieval is embedded in the
lead's job description, not delegated.

### No cross-phase agent persistence

Each phase in run.sh spawns a separate claude process with its own
`--agents` config. When the process exits, the agents are gone. There
is no session-level agent registry.

### No style modeling

No agent in the system analyzes or matches the human's writing style.
Artifacts are written in whatever voice the model defaults to.

## Relationship to Other Backlog Items

**reference-based-information-passing.md** — The retrieval specialist
is the natural consumer of the artifact_reader utility proposed there.
Instead of each script rolling its own file-reading logic, the
retrieval specialist uses artifact_reader's strategies (section,
keyword, head, tail) to assemble context packages.

**context-aware-proxy.md** — The quality reviewer overlaps with the
proxy's content novelty detection. The proxy asks "is this artifact
unusual enough to escalate?" The quality reviewer asks "does this
artifact meet its own stated criteria?" These are complementary — the
proxy gates the human's attention, the reviewer gates the artifact's
intellectual integrity.
