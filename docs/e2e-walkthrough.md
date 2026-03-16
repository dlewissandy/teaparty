# End-to-End Walkthrough

!!! note "Live session"
    This walkthrough follows a real TeaParty session: project **humor-book**, session **20260315-171017**. The session orchestrated a multi-chapter popular non-fiction book on the universal nature of humor.

This page traces a single session from the user's one-sentence prompt through intent capture, planning, hierarchical dispatch, and execution — showing how the four pillars (CfA protocol, hierarchical teams, human proxy, and learning system) work together in practice.

---

## The Prompt

The session began with a single natural-language request:

> *I would like a book on the universal nature of humor. There are certain types of humor that transcend time, culture and language (e.g. comedy wildlife photos, physical humor, affiliative humor, etc). This is a 5-7 chapter book, targeting armchair enthusiasts, and should explore this phenomena across cultural, temporal, language, belief, and technological boundaries. Thesis: Humor is what unites us.*

From this, the orchestrator ran the full CfA lifecycle.

---

## Phase 1: Intent Capture

The CfA state machine began at **IDEA** and the intent team's job was to turn the prompt into a complete [INTENT.md](e2e/INTENT.md) — a document precise enough that a planning team could work from it without guessing, but scoped only to *what* and *why*, never *how*.

The intent agent checked for prior work (none — clean slate), then engaged the human with two targeted questions via `AskQuestion`. Notice the agent does not ask a battery of questions. It identifies the two most consequential structural ambiguities in the prompt, asks them one at a time, and writes the intent as soon as it has what it needs.

### Dialog

**Agent:** *No prior work to build on — clean slate. Let me engage you directly on the most consequential structural question before writing the intent.*

> **Agent asks (AskQuestion):**
>
> The most important structural decision for this book is how to organize its chapters — and two very different architectures are possible:
>
> **Option A — Organized by *type* of humor** (each chapter = a category of universal comedy)
> e.g., Ch1: Physical/slapstick, Ch2: Absurdism, Ch3: Affiliative/in-group humor...
> Each chapter then explores *why* that type travels across cultures, time, and language.
>
> **Option B — Organized by *boundary crossed*** (each chapter = a dimension of universality)
> e.g., Ch1: Humor across cultures, Ch2: Humor across time, Ch3: Humor across language...
> Each chapter draws on many *types* of humor to make its case about that particular boundary.
>
> **Option C — Hybrid:** A framing chapter + thematic core + boundary-crossing synthesis.
>
> Which architecture feels right to you — or is there a different structure you had in mind?

**Human:** I think organized by type works.

> **Agent asks (AskQuestion):**
>
> Should the book *itself* be funny — written with wit, comic asides, and a playful voice (think Bill Bryson or Mary Roach) — or is it a warm but more straightforwardly analytical exploration, letting the *subject matter* carry the humor (think Malcolm Gladwell or Jonathan Haidt)?
>
> The former asks the writer to perform the thesis. The latter asks them to argue it. Both work — but they're very different briefs.

**Human:** I think playful like Mary Roach.

**Agent:** *Perfect. I have what I need. Writing the intent now.*

### What the intent team added

From a four-sentence prompt, the intent team produced a [complete intent document](e2e/INTENT.md) that added:

- **Structural constraint:** Humor types are the organizing principle; boundaries are the lens through which each type is examined, not the chapter headings.
- **Voice model:** Mary Roach — warm, irreverent, rigorous but never stiff. The book performs its own thesis.
- **Success criteria:** Each chapter must include a non-Western example, a pre-20th-century example, and a counterexample that challenges its own premise.
- **Five open questions** surfaced for the planning team to resolve: chapter lineup, prologue structure, word count, title, and visuals.

The intent phase took approximately 5 minutes. The agent asked two questions. Both were *consequential* — they resolved ambiguities that would have produced fundamentally different books. The remaining decisions (chapter lineup, word count, title) were correctly deferred to the planning team as open questions.

**CfA transitions:** IDEA → PROPOSAL → INTENT_ASSERT (approved) → INTENT

---

## Phase 2: Planning

With the intent approved, the planning team produced a [PLAN.md](e2e/PLAN.md) that resolved all five open questions and defined a five-phase execution strategy.

The planning agent read the intent, identified the open questions, and engaged the human in a focused dialog to resolve them. Like the intent agent, it brought proposals — not open-ended questions. Each question presented the agent's analysis and recommendation, asking the human to confirm or redirect.

### Dialog

> **Agent asks (AskQuestion):**
>
> I've read the brief carefully. The bones are excellent. [...] Here's what I'm seeing:
>
> *Strong candidates for the open slots:*
> - **The First Joke** — peekaboo, object permanence, rats that laugh when tickled
> - **The Pratfall of Power** — comedy of the powerful brought low
> - **Gallows Humor** — challenges the universality thesis most directly, then vindicates it
> - **Nonsense / Absurdism** — humor that operates below language
> - **The World's Oldest Joke** — threaded through the archaeology of humor
>
> Three questions: (1) Which 2-3 of these excite you? (2) Are visuals in scope? (3) Title and prologue preference?

**Human:** Concretely, what is your first question?

The human pushed back on the bundled question. The agent unbundled and asked them one at a time:

> **Agent asks:** Of the open-slot chapter candidates, which 2-3 excite you most?

**Human:** That all looks good. Spam spam spam is a good example of absurdism.

> **Agent asks:** The comedy wildlife photography chapter practically invites real photographs. Are visuals in scope, or is this a straight prose narrative?

**Human:** Prose narrative. I think we can group it with visual humor (editorial cartoons), the "I got your back" stick figure tee shirt image, etc.

> **Agent asks:** Two quick structural questions: (1) Prologue vs. Chapter 1? My instinct is a short prologue that opens in the middle of something funny — joke first, thesis second. (2) Title: do you want the team to develop options?

**Human:** Yes. Knock, knock...

The human's "knock, knock..." was both an approval and a creative direction — the prologue opens mid-joke, and the knock-knock format is itself a universal joke structure. The agent recognized both signals.

### What the planning team produced

The [PLAN.md](e2e/PLAN.md) resolved all five open questions:

| # | Question | Resolution |
|---|----------|------------|
| 1 | Chapter lineup | 7 chapters confirmed (see below) |
| 2 | Prologue/epilogue | Short prologue, opens mid-joke ("knock, knock...") |
| 3 | Word count | ~7,000-9,000 words per chapter |
| 4 | Title | Team to develop 3-5 alternatives |
| 5 | Visuals | Prose narrative only |

**Chapter lineup:**

| # | Working Title | Humor Type | Primary Boundary |
|---|---|---|---|
| P | *(Prologue)* | Setup/punchline as universal form | Cultural |
| 1 | Born Laughing | Biology of laughter; peekaboo; rats | Cultural (pre-cultural) |
| 2 | The Oldest Joke in the World | Archaeology of humor; Sumerian to Roman | Temporal |
| 3 | Banana Peels and Power | Slapstick + status reversal | Cultural + temporal |
| 4 | You Had to Be There | Affiliative/in-group; roasting; belonging | Belief |
| 5 | The Last Laugh | Gallows humor; comedy from disaster | Belief + cultural |
| 6 | Silence Is Funny | Visual humor: wildlife photos, cartoons, wordless gags | Linguistic + technological |
| 7 | Spam Spam Spam | Absurdism/nonsense; humor below language | Linguistic; synthesis |

The plan defined a five-phase execution strategy: Research → Specification → Production → Editorial → Verification. Each phase has explicit done-criteria and escalation conditions.

The planning phase took approximately 16 minutes. The proxy approved the plan at PLAN_ASSERT.

**CfA transitions:** INTENT → DRAFT → PLAN_ASSERT (approved) → PLAN

---

## Phase 3: Execution — Hierarchical Dispatch

With the plan approved, the state machine transitioned to PLAN → TASK via `delegate`, triggering hierarchical dispatch. The uber team decomposed Phase 1 (Research) into eight parallel research tracks — one per chapter including the prologue — and dispatched each to its own worktree.

Each research dispatch:

- Created an isolated git worktree for its work
- Ran its own CfA cycle (intent → plan → execute) within that worktree
- Used the proxy for all assert gates (`never_escalate=True`) — no human involvement
- Received a scoped task brief from the uber team (context compression at the hierarchy boundary)

The screenshot below shows the TUI workspace during the execution phase. The top pane displays the original prompt and the session's CfA state history — each transition from IDEA through PLAN is visible. The middle pane shows the uber team's execution stream: it has read the approved plan, decomposed Phase 1 (Research) into eight parallel tracks, and is dispatching each to its own worktree. The system confirmations show the proxy evaluating and approving each research brief's intent and plan autonomously — no human involvement. The status bar at the bottom shows the session in the TASK state with eight active dispatches.

![TUI workspace showing eight parallel research dispatches running](e2e/e2e workspace.png)

### Research dispatches

| Dispatch | Chapter | Task |
|---|---|---|
| 20260315-173223 | Prologue | Research brief: cognitive mechanisms, cross-cultural examples, opening joke candidates |
| 20260315-173232 | Ch 1: Born Laughing | Research brief: biology of laughter, infant laughter, Panksepp rat experiments |
| 20260315-173240 | Ch 2: The Oldest Joke | Research brief: archaeology of humor, Sumerian to Roman |
| 20260315-173257 | Ch 3: Banana Peels and Power | Research brief: slapstick, status reversal |
| 20260315-173303 | Ch 4: You Had to Be There | Research brief: affiliative humor, in-group bonding |
| 20260315-173318 | Ch 5: The Last Laugh | Research brief: gallows humor, comedy from disaster |
| 20260315-173351 | Ch 6: Silence Is Funny | Research brief: visual humor, wordless comedy |
| 20260315-173433 | Ch 7: Spam Spam Spam | Research brief: absurdism, nonsense traditions |

<!-- TODO: Add results as research dispatches complete — sample research brief,
     proxy decisions at TASK_ASSERT, worktree merge details -->

---

## Phase 4: Results

<!-- TODO: Show what the research teams produced.
     Include:
     - Sample research brief (pick the most interesting chapter)
     - How worktree merges brought results back to the session branch
     - Any proxy decisions at TASK_ASSERT (approved/corrected)
     - Token usage and cost across the full session
-->

---

## CfA State Machine Trace

The session's full state history, from the CfA log:

| Time (UTC) | State | Action | Actor |
|---|---|---|---|
| 00:10:17 | IDEA | propose | human |
| 00:14:56 | PROPOSAL | assert | human |
| 00:15:54 | INTENT_ASSERT | approve | intent_team |
| 00:15:59 | INTENT | plan | human |
| 00:29:27 | DRAFT | assert | planning_team |
| 00:31:51 | PLAN_ASSERT | approve | planning_team |
| 00:31:51 | PLAN | delegate | human |

<!-- TODO: Add execution-phase transitions as they complete -->

---

## What This Demonstrates

<!-- TODO: Tie the walkthrough back to the four pillars:
     1. CfA Protocol — how the state machine guided the session through intent -> plan -> execution
        without prescriptive prompts; the agents chose their own transitions
     2. Hierarchical Teams — how 8 parallel research teams worked independently in worktrees,
        coordinated by the uber team, with context compression at boundaries
     3. Human Proxy — how the proxy agent handled assert gates autonomously for subteams
        (never_escalate), while the top-level gates involved the human
     4. Learning System — what learnings were extracted post-session and how they'll inform
        future sessions on similar tasks
-->
