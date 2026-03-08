# Copy-Editor Notes

---

## Layer 1: The Feedback Loop

---

**Issue 1**

- Location: Layer 1, diagram (above bullet list)
- Issue type: Self-containment
- Original text: `classify_task.py  →  intent.sh dialog`
- Suggested revision: The diagram introduces `intent.sh` without any prior mention. A first-time reader sees it in the diagram before the prose explains it. The prose paragraph that follows does explain it, but the diagram precedes that explanation. Consider adding a parenthetical label in the diagram, e.g., `intent.sh dialog  (intent session)`, or reorder so the prose definition comes first and the diagram follows.

---

**Issue 2**

- Location: Layer 1, diagram
- Issue type: Self-containment / wording
- Original text: `filtered up 4 levels`
- Suggested revision: "4 levels" is unexplained in Layer 1. The reader is told filtering happens across four levels but has no sense of what those levels are until Layer 3. Either drop the count here ("filtered upward through the memory hierarchy") or add a one-phrase gloss ("four levels of memory hierarchy — dispatch through global"). The prose paragraph later in Layer 1 does say "four levels of memory hierarchy," which is better; the diagram label should match that language.

---

**Issue 3**

- Location: Layer 1, bullet list
- Issue type: Wording / style consistency
- Original text: `**INTENT.md** — per-task, forward-looking ('what should happen')` / `**MEMORY.md** — cross-task, backward-looking ('what has worked')`
- Suggested revision: The parenthetical glosses use single quotation marks. The surrounding prose uses standard double quotation marks. Standardize to double quotes throughout for consistency: `("what should happen")` / `("what has worked")`.

---

**Issue 4**

- Location: Layer 1, paragraph 1 ("Every task begins with...")
- Issue type: Clarity
- Original text: "adjusting its tier classification and routing posture based on what `MEMORY.md` records about what has worked"
- Suggested revision: "routing posture" is undefined here and never defined explicitly in Layer 1. A reader unfamiliar with this system will not know whether "posture" is a technical term or a metaphor. Consider: "adjusting its tier classification and approach to routing tasks." If "routing posture" is a term of art used consistently elsewhere in the system, a brief parenthetical definition would help: "routing posture (the system's default stance on which agents or tiers to prefer)."

---

**Issue 5**

- Location: Layer 1, paragraph 1 ("Every task begins with...")
- Issue type: Clarity
- Original text: "That warm-started classification then drives the `intent.sh` dialog, which produces `INTENT.md`: the per-task artifact that captures what should happen, what assumptions are live, and what needs confirmation."
- Suggested revision: "assumptions are live" is an unusual phrase. "Live" could mean active, unresolved, or currently in effect. Suggest: "what assumptions are currently in play" or "what assumptions are still open."

---

**Issue 6**

- Location: Layer 1, paragraph 2 ("Once `INTENT.md` exists...")
- Issue type: Clarity
- Original text: "The execution streams — agent outputs, tool calls, escalations, decisions — are captured throughout."
- Suggested revision: Minor: "throughout" is slightly vague — throughout what? Suggest: "are captured throughout execution" or "are captured during the dispatch."

---

**Issue 7**

- Location: Layer 1, final paragraph ("That updated `MEMORY.md` is what...")
- Issue type: Wording
- Original text: "The loop closes. Nothing about this is incidental — the design intention is that the system learns from what agents do, not from instructions about what to remember."
- Suggested revision: "design intention" is slightly redundant (a design is by definition intentional). Suggest: "the design goal is that the system learns from what agents do" or simply "the system is designed to learn from what agents do." The second sentence reads more cleanly as: "The loop closes. The system is designed to learn from what agents do, not from instructions about what to remember."

---

## Layer 2: How They Connect — Mechanics

---

**Issue 8**

- Location: Layer 2, "Memory feeding into intent," paragraph 1
- Issue type: Self-containment / abstraction
- Original text: "`ESCALATION.md` holds domain-indexed autonomy calibrations — for example, 'Escalate more in domain X'."
- Suggested revision: "Domain-indexed autonomy calibrations" is dense for a first introduction of `ESCALATION.md`. This file has not appeared in Layer 1 at all. Layer 2 is the first mention. A brief appositive would help: "`ESCALATION.md` — a file that records per-domain guidance on when to escalate — holds autonomy calibrations, for example, 'Escalate more in domain X'." Alternatively, if `ESCALATION.md` belongs in Layer 1's diagram or bullet list as a system artifact, its absence there is a self-containment gap.

---

**Issue 9**

- Location: Layer 2, "Memory feeding into intent," paragraph 1
- Issue type: Clarity
- Original text: "These warm-start the tier classification: the CLASSIFY_PROMPT literally includes the instruction 'MEMORY WARM-START: If ESCALATION.md shows Escalate more for this domain, push tier up.'"
- Suggested revision: The inline quote from `CLASSIFY_PROMPT` is useful evidence but its formatting breaks reading flow. The phrase "push tier up" is jargon that has not been defined. Suggest either adding a brief gloss — "push tier up (assign a higher-autonomy tier)" — or setting off the prompt excerpt more clearly as a block quote rather than running it into the sentence.

---

**Issue 10**

- Location: Layer 2, "Memory feeding into intent," future capability note
- Issue type: Abstraction / wording
- Original text: "*Future capability (not yet fully active):* `memory_indexer.py` will retrieve top-k relevant memory chunks via BM25 + embeddings and inject them as additional context into the intent agent's prompt at session start."
- Suggested revision: The italicized parenthetical label is fine, but "top-k" and "BM25 + embeddings" are retrieval-system terms that may lose readers who are not familiar with information retrieval. Since this is a forward-looking note, a lighter gloss would serve better: "will retrieve the most relevant memory excerpts (using a combination of keyword and semantic search) and inject them as context into the intent agent's prompt at session start." If the technical specifics are important to keep, retain them but add the gloss in parentheses.

---

**Issue 11**

- Location: Layer 2, "Intent recording for learning," paragraph 1
- Issue type: Self-containment
- Original text: "`retroactive_extract.py` reads this stream and populates two files: `OBSERVATIONS.md` (human preference signals inferred from the dialog) and `ESCALATION.md` (autonomy calibrations derived from how the human pushed back or agreed)."
- Suggested revision: `retroactive_extract.py` is introduced here with no prior mention. Its name implies it was a late addition or operates after the fact, but the "retroactive" in the name is not explained. A one-clause description would help: "`retroactive_extract.py` (which analyzes the recorded dialog after the session ends) reads this stream and populates..." Also note that `OBSERVATIONS.md` is introduced here and does not appear elsewhere in the three layers. If it plays no further role, the reader is left wondering whether it feeds back into the loop. A clarifying phrase would close that gap: "These two files feed back into the next `classify_task.py` run" — which the paragraph does say, but the sentence connecting `OBSERVATIONS.md` specifically to that feedback is absent. Suggest: "...and `ESCALATION.md` (autonomy calibrations derived from how the human pushed back or agreed). Both files feed back into the next `classify_task.py` run — the loop closes."

---

**Issue 12**

- Location: Layer 2, "How execution produces memory," paragraph 1
- Issue type: Clarity / wording
- Original text: "Each dispatch: `relay.sh` asynchronously calls `summarize_session.py --scope team` on the exec stream after the dispatch completes."
- Suggested revision: "Each dispatch:" is an incomplete sentence used as a label. This is grammatically unconventional and could be smoothed: "After each dispatch, `relay.sh` asynchronously calls `summarize_session.py --scope team` on the exec stream." Alternatively, if the colon-label style is intentional for parallel structure with other sections, apply it consistently; currently this is the only section that uses it.

---

**Issue 13**

- Location: Layer 2, "How execution produces memory," paragraph 1
- Issue type: Abstraction / self-containment
- Original text: "Learnings are promoted up four levels via `promote_learnings.sh`: dispatch → team → session → project → global."
- Suggested revision: This inline chain lists five items but says "four levels." The count refers to the number of transitions (four steps between five levels), not the number of levels. This will confuse readers. Suggest: "Learnings are promoted upward through five levels via `promote_learnings.sh`: dispatch → team → session → project → global. Each transition filters for greater generality." Or, if the intent is to count levels above dispatch: "promoted up through four levels above dispatch." The ambiguity should be resolved here, since the same "four levels" phrasing appears in Layer 1 and Layer 3 uses "five levels" explicitly.

---

**Issue 14**

- Location: Layer 2, "How execution produces memory," paragraph 2 (quality gate)
- Issue type: Clarity
- Original text: "Quality gate: only structured `## [DATE] Type` entries survive."
- Suggested revision: "Quality gate:" is another colon-label fragment. Consistent with the note in Issue 12, either normalize these to full sentences or apply the label style uniformly. Suggest: "A quality gate ensures that only structured `## [DATE] Type` entries survive."

---

**Issue 15**

- Location: Layer 2, "How execution produces memory," final paragraph
- Issue type: Wording / clarity
- Original text: "Learning is structural — extracted from exec streams post-run by claude-haiku."
- Suggested revision: "claude-haiku" appears here with no prior introduction. A reader who does not know the model ecosystem will not understand what this refers to. Suggest adding a brief identification: "extracted from exec streams post-run by claude-haiku (the model used for summarization)." Also, "structural" here is doing conceptual work — it means "built into the process, not prompted" — but that meaning is not immediately apparent. The sentence that follows clarifies it, but the word itself may cause a momentary stumble. Consider: "Learning is emergent from structure — extracted from exec streams post-run by claude-haiku. Agents see no memory instructions in their prompts; the system learns from what they do, not from what they're told to remember."

---

## Layer 3: Architecture — Deeper Connections

---

**Issue 16**

- Location: Layer 3, "INTENT.md as a living hypothesis," paragraph 1
- Issue type: Clarity / wording
- Original text: "`INTENT.md` is not a finished spec — it uses provisional framing throughout: 'current assumption:', 'to be confirmed:', 'best guess:'."
- Suggested revision: The colon after each label in the list ("'current assumption:'") makes it look like these are syntactic prefixes used literally in the file, which is probably accurate and worth making explicit. Suggest: "...it uses provisional framing throughout, with labels such as `current assumption:`, `to be confirmed:`, and `best guess:`." Using code formatting (backticks) rather than quotation marks would signal more clearly that these are literal strings appearing in the file.

---

**Issue 17**

- Location: Layer 3, "INTENT.md as a living hypothesis," paragraph 1
- Issue type: Clarity
- Original text: "The `<\!-- INTENT VERSION: v0.1 ... -->` header is auto-maintained."
- Suggested revision: "Auto-maintained" is ambiguous — maintained by what? By the agent? By a script? By the intent session? Suggest: "The `<!-- INTENT VERSION: v0.1 ... -->` header is maintained automatically by the intent session." Also note the backslash before the exclamation mark (`<\!--`) appears to be an artifact of Markdown escaping in the source. The rendered output would show `<!--`, which is correct, but authors should verify this renders as intended.

---

**Issue 18**

- Location: Layer 3, "INTENT.md as a living hypothesis," paragraph 1
- Issue type: Clarity / wording
- Original text: "This framing is itself a learning pattern — the system has 'learned' (by design) not to commit prematurely."
- Suggested revision: The scare quotes around "learned" and the parenthetical "(by design)" are doing the same work — both signal that "learned" is being used loosely. Pick one device. Suggest: "This framing is itself a design pattern — the system is built not to commit prematurely." Or, if the intended point is that it mirrors learning behavior: "This framing mirrors a learning pattern: the system is designed not to commit prematurely."

---

**Issue 19**

- Location: Layer 3, "The Memory Hierarchy," numbered list
- Issue type: Clarity / consistency
- Original text: "3. Session-level `MEMORY.md` — cross-team coordination learnings (team-internal details filtered out)"
- Suggested revision: The parenthetical "(team-internal details filtered out)" follows a different pattern from the other list items, which describe what the level contains rather than what is removed. This creates a slight asymmetry. Suggest: "cross-team coordination learnings, with team-internal details stripped" — or restructure to parallel the others: "patterns from cross-team coordination (team-internal details excluded)."

---

**Issue 20**

- Location: Layer 3, "The Memory Hierarchy," final paragraph
- Issue type: Wording
- Original text: "`MEMORY.md` files are gitignored — they live in `.sessions/` and `.worktrees/`, never on main. Infrastructure doesn't pollute the code history."
- Suggested revision: "Infrastructure doesn't pollute the code history" reads as casual commentary. In a technical explanation, a more neutral phrasing fits better: "This keeps infrastructure concerns out of the code history." Or: "Memory files are excluded from version control so they do not appear in the project's commit history."

---

**Issue 21**

- Location: Layer 3, "Four Temporal Moments," paragraph 1
- Issue type: Clarity / self-containment
- Original text: "The system integrates memory at four distinct moments in a task's lifetime. Two are currently active; two are designed but not yet wired:"
- Suggested revision: This is clear. However, the table that follows labels one column "Status" with values "Active" and "Designed (future)." The introductory sentence uses "designed but not yet wired," which does not match the table's "Designed (future)" label exactly. Standardize the language: either use "designed but not yet wired" in the table, or use "designed (future)" in the prose.

---

**Issue 22**

- Location: Layer 3, "Four Temporal Moments," table — "Corrective" row
- Issue type: Clarity
- Original text: "Real-time extraction at moment of error or escalation"
- Suggested revision: "At moment of" is slightly awkward. Suggest: "Real-time extraction at the moment of an error or escalation." Minor, but worth a light fix.

---

**Issue 23**

- Location: Layer 3, "Four Temporal Moments," final paragraph
- Issue type: Wording
- Original text: "The architecture is built to receive them when they are."
- Suggested revision: The sentence ends abruptly — "when they are" is an incomplete clause ("when they are [wired]" or "when they are [ready]"). Suggest completing it: "The architecture is built to receive them when they are wired in." Or: "The architecture is built to accommodate them."

---

## Cross-Layer Issues

---

**Issue 24**

- Location: Layer 1 vs. Layer 3 — "four levels" vs. "five levels"
- Issue type: Clarity / consistency
- Original text: Layer 1: "promoting it upward through four levels of memory hierarchy"; Layer 2: "promoted up four levels via `promote_learnings.sh`: dispatch → team → session → project → global"; Layer 3: "Five levels, each more abstract than the last"
- Suggested revision: The count is inconsistent. Layer 3 is unambiguous: there are five named levels. Layers 1 and 2 say "four levels" but list five. The reconciliation is probably that "four levels" refers to four transitions (the number of promotion steps) rather than the number of levels. If so, Layer 1 and Layer 2 should say "four promotion steps" or "up through four tiers above the dispatch level." Alternatively, all three layers should use "five levels." This should be resolved for consistency regardless of which framing is correct.

---

**Issue 25**

- Location: Layer 1 (absent) vs. Layer 2 ("Intent recording for learning")
- Issue type: Self-containment / abstraction
- Original text: Layer 2 introduces `.intent-stream.jsonl` and `retroactive_extract.py` with no preparation in Layer 1.
- Suggested revision: Flag only. Layer 1 describes the dialog producing `INTENT.md` but does not mention that the dialog itself is recorded. A reader who reads only Layer 1 has an incomplete picture of what happens after the dialog ends (the recording and extraction step is entirely invisible). If Layer 1 is intended to be self-contained, a single sentence would close this gap: "The dialog session itself is recorded for later analysis." No mechanism details needed at Layer 1.

---

**Issue 26**

- Location: Layer 2 ("Intent recording for learning") vs. Layer 1
- Issue type: Self-containment
- Original text: `OBSERVATIONS.md` appears only in Layer 2 and is not mentioned again.
- Suggested revision: Flag only. `OBSERVATIONS.md` is introduced, briefly glossed, and then dropped. It is not referenced in Layer 3. The reader is left uncertain whether it feeds into something further or is simply consumed by the next `classify_task.py` run. If its role ends at feeding back into classification, a closing phrase in Layer 2 would confirm this and prevent the reader from wondering about it.
