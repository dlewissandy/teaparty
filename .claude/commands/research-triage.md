# Research Triage

Evaluate digested research ideas for relevance and impact to the TeaParty project.

## What To Do

1. **Find the latest digest.** Read the most recent file in `intake/digests/` (by date in filename). If an argument is provided, use that as the digest path instead.

2. **Read project context.** Read `docs/ARCHITECTURE.md` and `docs/cfa-state-machine.md` to ground your analysis in what TeaParty actually is and does. Skim other docs under `docs/` as needed for specific topics.

3. **For each idea in the digest, evaluate two dimensions:**

   - **Relevance** (High / Medium / Low) — How directly does this idea connect to TeaParty's concerns? High = directly addresses agent coordination, human proxy, CfA protocol, learning systems, or hierarchical teams. Medium = adjacent domain with clear transfer potential. Low = interesting but tangential.

   - **Impact** (High / Medium / Low) — If adopted, how much would this improve TeaParty? High = changes how a core system works or enables something currently impossible. Medium = meaningful improvement to an existing capability. Low = minor optimization or polish.

4. **For each idea, also identify:**
   - **What could be added** — Specific feature, mechanism, or change this idea suggests for TeaParty
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
**Relevance:** High | Medium | Low — <one-sentence justification>
**Impact:** High | Medium | Low — <one-sentence justification>

### What Could Be Added
<specific feature or change for TeaParty>

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
