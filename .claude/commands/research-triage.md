# Research Triage

Evaluate digested research ideas for relevance and impact to the TeaParty project.

## What To Do

1. **Find the latest digest.** Read the most recent file in `intake/digests/` (by date in filename). If an argument is provided, use that as the digest path instead.

2. **Read project context.** Read these files to ground your analysis:
   - `intake/priorities.md` — current research priorities and focus areas (READ THIS FIRST)
   - `docs/ARCHITECTURE.md` — system architecture
   - `docs/cfa-state-machine.md` — CfA protocol specification
   - `docs/human-proxies.md` — human proxy agent design

3. **For each idea in the digest, evaluate two dimensions:**

   - **Relevance** (High / Medium / Low) — How directly does this idea connect to TeaParty's current priorities (listed in `priorities.md`)? High = directly addresses an active focus area or "what we're looking for" item. Medium = adjacent domain with clear transfer potential. Low = interesting but not actionable for our current work.

   - **Impact** (High / Medium / Low) — If adopted, how much would this improve TeaParty? High = solves a known gap or enables something currently impossible. Medium = meaningful improvement to an existing capability. Low = minor optimization or polish.

4. **Devil's advocate check.** Before marking anything Explore, answer honestly: "Could I have written this triage entry by reading only the title and knowing our priorities?" If yes, the analysis is too shallow. Go back to the source content file (listed in the manifest) and re-read it. Find the specific mechanism that matters, or downgrade to Watch. "We have learning, this paper is about learning" is a Skip, not an Explore.

5. **For each idea, also identify:**
   - **What could be added** — Specific feature, mechanism, or change this idea suggests for TeaParty. Name the technique from the source, not just the topic area.
   - **How it differs from what we already do** — If you can't articulate the difference, it's not actionable.
   - **Pros** — Why this would be valuable
   - **Cons** — Why this might not work, what it would cost, what risks it introduces

5. **Write the analysis** to `intake/analysis/analysis-<YYYY-MM-DD>.md` using today's date.

## Output Format

```markdown
# Research Triage — <YYYY-MM-DD>

Source digest: <digest filename>

## Summary Matrix

| # | Idea | Relevance | Impact | Verdict |
|---|------|-----------|--------|---------|
| 1 | ... | High | Medium | Explore |
| 2 | ... | Low | Low | Skip |

---

## 1. <Idea name>
**Source:** <source title and URL>
**Relevance:** High | Medium | Low — <one-sentence justification tied to a specific priority from priorities.md>
**Impact:** High | Medium | Low — <one-sentence justification>

### What Could Be Added
<specific feature or change for TeaParty — name the mechanism, not the topic>

### How It Differs From What We Have
<what makes this NOT a restatement of something TeaParty already does or plans to do>

### Pros
- ...

### Cons
- ...

### Verdict
Explore | Watch | Skip — <one sentence>

---

## 2. <next idea>
...
```

## Verdict Categories

- **Explore** — High enough relevance and impact to warrant creating an idea file. This will feed the ideation skill.
- **Watch** — Interesting but not actionable now. Worth revisiting if the project's needs shift.
- **Skip** — Not relevant or impactful enough to pursue.

## Important

- Ground every relevance judgment in a specific priority from `intake/priorities.md`. Don't say "relevant to agent coordination" — say "relevant to proxy preference learning (priority #1)."
- If nothing in the digest is relevant, say so. An empty analysis is better than forced relevance.
- If the digest's Applicability block is vague or missing, re-read the source content file before triaging. The manifest has the file paths. Don't triage from a summary you don't trust.
