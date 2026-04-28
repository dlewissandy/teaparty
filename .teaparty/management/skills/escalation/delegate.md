# Delegate

A teammate is stuck and needs clarification.  The project has delegated this decision to you — the human trusts you to answer on their behalf, without consulting them.  Your job is to read the question, consult your memory of how the human thinks, decide, and relay the decision to your teammate with the rationale they need to act on it.

Your ACT-R memory introspection is in your prompt: activation levels, behavioral patterns, prediction history.  That is the source of truth for what you know about the human.  Ground every answer there.  Do not invent preferences you cannot trace to memory.


## START

Read `./QUESTION.md`.  It contains your teammate's question and any inline context.

If `QUESTION.md` includes an `## Attachments` section, read every file it lists.  Those are the files your teammate explicitly chose to share, copied verbatim from their worktree at the same relative paths (so a listed `.scratch/research-brief.md` is at `./.scratch/research-brief.md`).  They are part of your briefing, not optional supplementary material.

Weigh what the question is really asking against what your memory tells you the human would say.

- If you infer from your memory that the human would provide an answer, then read `respond.md` in this skill directory and execute it.  
- If you infer from your memory that the human would find this work is unnecessary, read `withdraw.md` in this skill directory and execute it.  
