# Intent & Planning

The first 21 minutes of the session produced two documents ([INTENT.md](./artifacts/INTENT.md) and [PLAN.md](./artifacts/PLAN.md)) from six human dialog turns. The transcripts below show how the agents worked: bringing proposals rather than open-ended questions, recognizing creative direction embedded in brief replies, and deferring decisions they didn't need to make.

---

## Phase 1: Intent Capture

The CfA state machine began at **IDEA** and the intent team's job was to turn the prompt into a complete intent document: precise enough that a planning team could work from it without guessing, but scoped only to *what* and *why*, never *how*.

The intent agent checked for prior work (none — clean slate), then engaged the human with two targeted questions via [`AskQuestion`](../systems/human-proxy/approval-gate.md#escalationlistener-askquestion-mcp-tool) (the MCP tool that routes an agent's question through the proxy to the human). It does not ask a battery of questions. It identifies the two most consequential structural ambiguities in the prompt, asks them one at a time, and writes the intent as soon as it has what it needs.

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

From a four-sentence prompt, the intent team produced a [complete intent document](./artifacts/INTENT.md) that added:

- **Structural constraint:** Humor types are the organizing principle; boundaries are the lens through which each type is examined, not the chapter headings.
- **Voice model:** Mary Roach — warm, irreverent, rigorous but never stiff. The book performs its own thesis.
- **Success criteria:** Each chapter must include a non-Western example, a pre-20th-century example, and a counterexample that challenges its own premise.
- **Five open questions** surfaced for the planning team to resolve: chapter lineup, prologue structure, word count, title, and visuals.

The intent phase took approximately 5 minutes. Both questions were *consequential*: they resolved ambiguities that would have produced fundamentally different books. The remaining decisions were correctly deferred to the planning team as open questions.

**CfA transitions:** IDEA → PROPOSAL → INTENT_ASSERT (approved) → INTENT

---

## Phase 2: Planning

With the intent approved, the planning team produced a [PLAN.md](./artifacts/PLAN.md) that resolved all five open questions and defined a five-phase execution strategy.

The planning agent brought proposals rather than open-ended questions. Each question presented the agent's analysis and recommendation, asking the human to confirm or redirect.

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

The human's "knock, knock..." was both an approval and a creative direction: the prologue opens mid-joke, and the knock-knock format is itself a universal joke structure. The agent recognized both signals.

### What the planning team produced

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
